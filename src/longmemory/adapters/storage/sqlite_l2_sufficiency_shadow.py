"""SQLite V42 的 L2 证据充分性影子审计存储。"""

from hashlib import sha256
from pathlib import Path
import re
import sqlite3

from longmemory.application.scenario_recall import ScenarioRecallResult
from longmemory.core.memory.retrieval.sufficiency import EvidenceSufficiencyReview


class SQLiteL2SufficiencyShadowStore:
    """只追加候选快照与结果；不复制问题、场景正文或模型自由文本。"""

    def __init__(self, database: Path) -> None:
        self.database = database.resolve()

    def _open(self):
        connection = sqlite3.connect(self.database, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def start(self, *, user_message_id: str, candidates: ScenarioRecallResult,
              reviewer_version: str, prompt_sha256: str, provider: str,
              model: str, requested_at) -> bool:
        if (not user_message_id.strip() or not reviewer_version.strip()
                or not provider.strip() or not model.strip()
                or re.fullmatch(r"[0-9a-f]{64}", prompt_sha256) is None):
            raise ValueError("l2_sufficiency_shadow_run_invalid")
        connection = self._open()
        try:
            source = connection.execute(
                "SELECT role FROM conversation_messages WHERE id=?",
                (user_message_id,),
            ).fetchone()
            if source is None or source["role"] != "user":
                raise ValueError("l2_sufficiency_shadow_source_missing")
            existing = connection.execute(
                "SELECT user_message_id FROM l2_sufficiency_shadow_runs "
                "WHERE user_message_id=?", (user_message_id,),
            ).fetchone()
            if existing is not None:
                connection.rollback()
                return False
            connection.execute(
                "INSERT INTO l2_sufficiency_shadow_runs "
                "(user_message_id,retrieval_strategy,reviewer_version,prompt_sha256,"
                "provider,model,status,requested_at) VALUES (?,?,?,?,?,?,'pending',?)",
                (user_message_id, candidates.strategy, reviewer_version,
                 prompt_sha256, provider, model, requested_at.isoformat()),
            )
            for rank, item in enumerate(candidates.items, 1):
                digest = sha256(
                    f"{item.title}：{item.summary}".encode("utf-8")
                ).hexdigest()
                connection.execute(
                    "INSERT INTO l2_sufficiency_shadow_candidates "
                    "(user_message_id,scenario_id,rank,content_sha256,keyword_score) "
                    "VALUES (?,?,?,?,?)",
                    (user_message_id, item.scenario_id, rank, digest,
                     item.keyword_score),
                )
            connection.commit()
            return True
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete(self, *, user_message_id: str,
                 review: EvidenceSufficiencyReview, completed_at) -> None:
        connection = self._open()
        try:
            rows = connection.execute(
                "SELECT scenario_id FROM l2_sufficiency_shadow_candidates "
                "WHERE user_message_id=? ORDER BY rank", (user_message_id,),
            ).fetchall()
            expected = tuple(row["scenario_id"] for row in rows)
            if tuple(item.item_id for item in review.decisions) != expected:
                raise ValueError("l2_sufficiency_shadow_decisions_mismatch")
            for decision in review.decisions:
                connection.execute(
                    "UPDATE l2_sufficiency_shadow_candidates "
                    "SET supports_answer=?,reason_code=? "
                    "WHERE user_message_id=? AND scenario_id=?",
                    (int(decision.supports_answer), decision.reason_code,
                     user_message_id, decision.item_id),
                )
            changed = connection.execute(
                "UPDATE l2_sufficiency_shadow_runs SET status='completed',"
                "completed_at=?,error_code=NULL WHERE user_message_id=? "
                "AND status='pending'",
                (completed_at.isoformat(), user_message_id),
            ).rowcount
            if changed != 1:
                raise ValueError("l2_sufficiency_shadow_state_conflict")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete_empty(self, *, user_message_id: str, completed_at) -> None:
        """没有主题候选也是一次完整观测，但不会伪造模型判定。"""

        connection = self._open()
        try:
            candidate_count = connection.execute(
                "SELECT count(*) FROM l2_sufficiency_shadow_candidates "
                "WHERE user_message_id=?", (user_message_id,),
            ).fetchone()[0]
            if candidate_count != 0:
                raise ValueError("l2_sufficiency_shadow_candidates_not_empty")
            changed = connection.execute(
                "UPDATE l2_sufficiency_shadow_runs SET status='completed',"
                "completed_at=?,error_code=NULL WHERE user_message_id=? "
                "AND status='pending'",
                (completed_at.isoformat(), user_message_id),
            ).rowcount
            if changed != 1:
                raise ValueError("l2_sufficiency_shadow_state_conflict")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def fail(self, *, user_message_id: str, error_code: str,
             completed_at) -> None:
        if (not error_code.strip() or len(error_code) > 120
                or re.fullmatch(r"[a-z0-9_]+", error_code) is None):
            error_code = "l2_sufficiency_shadow_failed"
        connection = self._open()
        try:
            changed = connection.execute(
                "UPDATE l2_sufficiency_shadow_runs SET status='failed',"
                "completed_at=?,error_code=? WHERE user_message_id=? "
                "AND status='pending'",
                (completed_at.isoformat(), error_code, user_message_id),
            ).rowcount
            if changed != 1:
                raise ValueError("l2_sufficiency_shadow_state_conflict")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
