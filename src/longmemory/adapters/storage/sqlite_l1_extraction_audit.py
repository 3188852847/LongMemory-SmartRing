"""日常 L1 提取的脱敏追加账本；正文仍只存在于既有 L0。"""

from dataclasses import dataclass
from datetime import datetime
import re
import sqlite3
from uuid import uuid4


_SHA256 = re.compile(r"[0-9a-f]{64}")
_OUTCOMES = {
    "noop", "added", "reused", "extraction_failed", "persistence_failed",
}


@dataclass(frozen=True, slots=True)
class L1ExtractionAuditMetadata:
    method_version: str
    prompt_version: str | None
    preprocessor_version: str
    prompt_sha256: str | None
    provider: str
    model: str

    def __post_init__(self) -> None:
        values = (self.method_version, self.preprocessor_version, self.provider, self.model)
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError("l1_extraction_audit_metadata_invalid")
        if self.prompt_version is not None and not self.prompt_version.strip():
            raise ValueError("l1_extraction_audit_metadata_invalid")
        if self.prompt_sha256 is not None and _SHA256.fullmatch(self.prompt_sha256) is None:
            raise ValueError("l1_extraction_audit_metadata_invalid")


class SQLiteL1ExtractionAuditStore:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def start(self, *, attempt_id: str, source_message_id: str,
              metadata: L1ExtractionAuditMetadata, occurred_at: datetime) -> None:
        self._insert(
            attempt_id=attempt_id, source_message_id=source_message_id,
            phase="started", outcome_code=None, candidate_count=None,
            added_count=None, metadata=metadata, occurred_at=occurred_at,
            duration_ms=None,
        )

    def finish(self, *, attempt_id: str, source_message_id: str, phase: str,
               outcome_code: str, candidate_count: int, added_count: int,
               metadata: L1ExtractionAuditMetadata, occurred_at: datetime,
               duration_ms: float) -> None:
        if phase not in {"completed", "failed"} or outcome_code not in _OUTCOMES:
            raise ValueError("l1_extraction_audit_outcome_invalid")
        if candidate_count < 0 or added_count < 0 or duration_ms < 0:
            raise ValueError("l1_extraction_audit_outcome_invalid")
        self._insert(
            attempt_id=attempt_id, source_message_id=source_message_id,
            phase=phase, outcome_code=outcome_code,
            candidate_count=candidate_count, added_count=added_count,
            metadata=metadata, occurred_at=occurred_at, duration_ms=duration_ms,
        )

    def list_recent(self, *, limit: int = 50) -> dict:
        """按一次提取尝试聚合开始/终态；不联表读取 L0 正文。"""

        if not 1 <= limit <= 100:
            raise ValueError("l1_extraction_audit_limit_invalid")
        rows = self._connection.execute(
            "SELECT s.attempt_id,s.source_message_id,s.occurred_at,s.method_version,"
            "s.prompt_version,s.preprocessor_version,s.prompt_sha256,s.provider,s.model,"
            "t.phase,t.outcome_code,t.candidate_count,t.added_count,t.occurred_at,t.duration_ms,"
            "NOT EXISTS (SELECT 1 FROM l1_extraction_events newer "
            "WHERE newer.source_message_id=s.source_message_id AND newer.phase='started' "
            "AND (newer.occurred_at>s.occurred_at OR "
            "(newer.occurred_at=s.occurred_at AND newer.rowid>s.rowid))) AS is_latest "
            "FROM l1_extraction_events s LEFT JOIN l1_extraction_events t "
            "ON t.attempt_id=s.attempt_id AND t.phase IN ('completed','failed') "
            "WHERE s.phase='started' ORDER BY s.occurred_at DESC,s.rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        counts = {
            "incomplete": 0, "noop": 0, "added": 0, "reused": 0,
            "extraction_failed": 0, "persistence_failed": 0,
        }
        items = []
        for row in rows:
            outcome = row[10] or "incomplete"
            counts[outcome] += 1
            items.append({
                "attempt_id": row[0], "source_message_id": row[1],
                "started_at": row[2], "method_version": row[3],
                "prompt_version": row[4], "preprocessor_version": row[5],
                "prompt_sha256": row[6], "provider": row[7], "model": row[8],
                "phase": row[9] or "started", "outcome_code": row[10],
                "candidate_count": row[11], "added_count": row[12],
                "finished_at": row[13], "duration_ms": row[14],
                "retryable": bool(row[15]) and outcome in {
                    "extraction_failed", "persistence_failed", "incomplete",
                },
            })
        return {"limit": limit, "counts": counts, "items": items}

    def require_retryable(self, *, source_message_id: str,
                          expected_attempt_id: str) -> None:
        """用最新尝试做乐观并发检查，防止旧页面重复发起模型调用。"""

        row = self._connection.execute(
            "SELECT s.attempt_id,t.outcome_code FROM l1_extraction_events s "
            "LEFT JOIN l1_extraction_events t ON t.attempt_id=s.attempt_id "
            "AND t.phase IN ('completed','failed') "
            "WHERE s.source_message_id=? AND s.phase='started' "
            "ORDER BY s.occurred_at DESC,s.rowid DESC LIMIT 1",
            (source_message_id,),
        ).fetchone()
        if row is None:
            raise ValueError("l1_retry_not_available")
        if row[0] != expected_attempt_id:
            raise ValueError("l1_retry_stale")
        if row[1] not in {None, "extraction_failed", "persistence_failed"}:
            raise ValueError("l1_retry_not_available")

    def _insert(self, **values) -> None:
        metadata = values["metadata"]
        try:
            self._connection.execute(
                "INSERT INTO l1_extraction_events "
                "(id,attempt_id,source_message_id,phase,outcome_code,candidate_count,"
                "added_count,method_version,prompt_version,preprocessor_version,"
                "prompt_sha256,provider,model,occurred_at,duration_ms) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()), values["attempt_id"], values["source_message_id"],
                    values["phase"], values["outcome_code"], values["candidate_count"],
                    values["added_count"], metadata.method_version,
                    metadata.prompt_version, metadata.preprocessor_version,
                    metadata.prompt_sha256, metadata.provider, metadata.model,
                    values["occurred_at"].isoformat(), values["duration_ms"],
                ),
            )
            self._connection.commit()
        except sqlite3.Error:
            # 审计是旁路，但失败事务若不清理，会影响同一连接之后的主业务写入。
            self._connection.rollback()
            raise
