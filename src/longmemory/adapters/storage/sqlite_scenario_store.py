"""L2 场景的 SQLite 事务存储；不负责调用模型或决定候选内容。"""

from datetime import datetime
from sqlite3 import Connection, Row

from longmemory.core.common.identifiers import MemoryId, MemorySubjectId, ScenarioId
from longmemory.core.memory.l2_scenario.models import (
    ScenarioGenerationAudit,
    ScenarioMemory,
    ScenarioReview,
    ScenarioReviewDecision,
    ScenarioSource,
    ScenarioStatus,
)


class SQLiteScenarioStore:
    def __init__(self, connection: Connection, *, commit_changes: bool = True) -> None:
        self._connection = connection
        self._commit_changes = commit_changes

    def save_candidate(
        self,
        scenario: ScenarioMemory,
        sources: tuple[ScenarioSource, ...],
        audit: ScenarioGenerationAudit,
    ) -> None:
        """原子保存候选、来源快照和生成审计，并验证多条独立 L0。"""

        if scenario.status != ScenarioStatus.CANDIDATE:
            raise ValueError("scenario_must_start_as_candidate")
        if audit.scenario_id != scenario.id or any(s.scenario_id != scenario.id for s in sources):
            raise ValueError("scenario_relation_mismatch")
        memory_ids = tuple(dict.fromkeys(str(source.memory_id) for source in sources))
        if len(memory_ids) < 2 or len(memory_ids) != len(sources):
            raise ValueError("scenario_requires_distinct_l1_sources")
        if (
            audit.generator_name != scenario.generator_name
            or audit.generator_version != scenario.generator_version
            or audit.generated_at != scenario.generated_at
            or audit.source_memory_count != len(memory_ids)
        ):
            raise ValueError("scenario_audit_mismatch")

        placeholders = ",".join("?" for _ in memory_ids)
        rows = self._connection.execute(
            f"SELECT id, subject_id, content, retired_at FROM atomic_memories "
            f"WHERE id IN ({placeholders})",
            memory_ids,
        ).fetchall()
        by_id = {row["id"]: row for row in rows}
        if len(by_id) != len(memory_ids):
            raise ValueError("scenario_source_l1_missing")
        for source in sources:
            row = by_id[str(source.memory_id)]
            if row["retired_at"] is not None:
                raise ValueError("scenario_source_l1_retired")
            if row["subject_id"] != str(scenario.subject_id):
                raise ValueError("scenario_source_subject_mismatch")
            if row["content"] != source.memory_content_snapshot:
                raise ValueError("scenario_source_snapshot_mismatch")

        source_message_count = self._connection.execute(
            f"SELECT count(DISTINCT e.source_message_id) FROM memory_evidence e "
            f"JOIN conversation_messages m ON m.id=e.source_message_id "
            f"WHERE m.role='user' AND e.memory_id IN ({placeholders})",
            memory_ids,
        ).fetchone()[0]
        if source_message_count < 2 or audit.source_message_count != source_message_count:
            raise ValueError("scenario_requires_distinct_user_l0_sources")

        try:
            self._connection.execute(
                "INSERT INTO scenario_memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(scenario.id), str(scenario.subject_id), scenario.title.strip(),
                    scenario.summary.strip(), scenario.generated_at.isoformat(),
                    self._time(scenario.valid_from), self._time(scenario.valid_to),
                    scenario.status.value, scenario.generator_name.strip(),
                    scenario.generator_version.strip(), scenario.revision,
                ),
            )
            self._connection.executemany(
                "INSERT INTO scenario_memory_sources VALUES (?, ?, ?, ?)",
                tuple((str(s.scenario_id), str(s.memory_id), s.memory_content_snapshot,
                       s.linked_at.isoformat()) for s in sources),
            )
            self._connection.execute(
                "INSERT INTO scenario_generation_audits VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(audit.id), str(audit.scenario_id), audit.generator_name,
                    audit.generator_version, audit.generated_at.isoformat(),
                    audit.source_memory_count, audit.source_message_count,
                ),
            )
            if self._commit_changes:
                self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def get(self, scenario_id: ScenarioId) -> ScenarioMemory | None:
        row = self._connection.execute(
            "SELECT * FROM scenario_memories WHERE id=?", (str(scenario_id),)
        ).fetchone()
        return None if row is None else self._row_to_scenario(row)

    def list_sources(self, scenario_id: ScenarioId) -> tuple[ScenarioSource, ...]:
        rows = self._connection.execute(
            "SELECT * FROM scenario_memory_sources WHERE scenario_id=? "
            "ORDER BY linked_at, memory_id",
            (str(scenario_id),),
        ).fetchall()
        return tuple(ScenarioSource(
            ScenarioId(row["scenario_id"]), MemoryId(row["memory_id"]),
            row["memory_content_snapshot"], datetime.fromisoformat(row["linked_at"]),
        ) for row in rows)

    def review(self, review: ScenarioReview, *, expected_revision: int) -> ScenarioMemory:
        """仅复核仍为 candidate 的同一 revision；原摘要和来源不改写。"""

        if review.scenario_revision != expected_revision:
            raise ValueError("scenario_review_revision_mismatch")
        status = (
            ScenarioStatus.ACTIVE
            if review.decision == ScenarioReviewDecision.ACCEPTED
            else ScenarioStatus.REJECTED
        )
        try:
            cursor = self._connection.execute(
                "UPDATE scenario_memories SET status=?, revision=revision+1 "
                "WHERE id=? AND status='candidate' AND revision=?",
                (status.value, str(review.scenario_id), expected_revision),
            )
            if cursor.rowcount != 1:
                raise ValueError("scenario_review_conflict")
            self._connection.execute(
                "INSERT INTO scenario_reviews VALUES (?, ?, ?, 'user', ?, ?)",
                (
                    str(review.id), str(review.scenario_id), review.decision.value,
                    review.reviewed_at.isoformat(), review.scenario_revision,
                ),
            )
            if self._commit_changes:
                self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise
        updated = self.get(review.scenario_id)
        if updated is None:  # 同一事务刚更新成功时只可能表示数据库被破坏。
            raise RuntimeError("scenario_missing_after_review")
        return updated

    @staticmethod
    def _time(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _row_to_scenario(row: Row) -> ScenarioMemory:
        return ScenarioMemory(
            ScenarioId(row["id"]), MemorySubjectId(row["subject_id"]),
            row["title"], row["summary"], datetime.fromisoformat(row["generated_at"]),
            ScenarioStatus(row["status"]), row["generator_name"], row["generator_version"],
            datetime.fromisoformat(row["valid_from"]) if row["valid_from"] else None,
            datetime.fromisoformat(row["valid_to"]) if row["valid_to"] else None,
            row["revision"],
        )
