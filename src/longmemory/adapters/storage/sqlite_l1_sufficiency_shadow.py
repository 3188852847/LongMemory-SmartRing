"""SQLite V45 的 L1 证据充分性影子审计与所有者复核。"""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from longmemory.core.memory.retrieval.sufficiency import EvidenceSufficiencyReview
from longmemory.methods.contracts import RetrievedTrace


class SQLiteL1SufficiencyShadowStore:
    """只追加候选指纹和判定；不复制问题、记忆正文或模型自由文本。"""

    def __init__(self, database: Path) -> None:
        self.database = database.resolve()

    def _open(self):
        connection = sqlite3.connect(self.database, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def start(self, *, user_message_id: str,
              candidates: tuple[RetrievedTrace, ...], retrieval_strategy: str,
              reviewer_version: str, prompt_sha256: str, provider: str,
              model: str, requested_at) -> bool:
        if (not user_message_id.strip() or not retrieval_strategy.strip()
                or not reviewer_version.strip() or not provider.strip()
                or not model.strip()
                or re.fullmatch(r"[0-9a-f]{64}", prompt_sha256) is None
                or len({item.item_id for item in candidates}) != len(candidates)):
            raise ValueError("l1_sufficiency_shadow_run_invalid")
        connection = self._open()
        try:
            source = connection.execute(
                "SELECT role FROM conversation_messages WHERE id=?",
                (user_message_id,),
            ).fetchone()
            if source is None or source["role"] != "user":
                raise ValueError("l1_sufficiency_shadow_source_missing")
            existing = connection.execute(
                "SELECT user_message_id FROM l1_sufficiency_shadow_runs "
                "WHERE user_message_id=?", (user_message_id,),
            ).fetchone()
            if existing is not None:
                connection.rollback()
                return False
            connection.execute(
                "INSERT INTO l1_sufficiency_shadow_runs "
                "(user_message_id,retrieval_strategy,reviewer_version,prompt_sha256,"
                "provider,model,status,requested_at) VALUES (?,?,?,?,?,?,'pending',?)",
                (user_message_id, retrieval_strategy, reviewer_version,
                 prompt_sha256, provider, model, requested_at.isoformat()),
            )
            for rank, item in enumerate(candidates, 1):
                connection.execute(
                    "INSERT INTO l1_sufficiency_shadow_candidates "
                    "(user_message_id,memory_id,rank,content_sha256,keyword_score,"
                    "dense_score,fused_score) VALUES (?,?,?,?,?,?,?)",
                    (user_message_id, item.item_id, rank,
                     sha256(item.content.encode("utf-8")).hexdigest(),
                     item.keyword_score, item.dense_score, item.fused_score),
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
                "SELECT memory_id FROM l1_sufficiency_shadow_candidates "
                "WHERE user_message_id=? ORDER BY rank", (user_message_id,),
            ).fetchall()
            expected = tuple(row["memory_id"] for row in rows)
            if tuple(item.item_id for item in review.decisions) != expected:
                raise ValueError("l1_sufficiency_shadow_decisions_mismatch")
            for decision in review.decisions:
                connection.execute(
                    "UPDATE l1_sufficiency_shadow_candidates "
                    "SET supports_answer=?,reason_code=? "
                    "WHERE user_message_id=? AND memory_id=?",
                    (int(decision.supports_answer), decision.reason_code,
                     user_message_id, decision.item_id),
                )
            changed = connection.execute(
                "UPDATE l1_sufficiency_shadow_runs SET status='completed',"
                "completed_at=?,error_code=NULL WHERE user_message_id=? "
                "AND status='pending'",
                (completed_at.isoformat(), user_message_id),
            ).rowcount
            if changed != 1:
                raise ValueError("l1_sufficiency_shadow_state_conflict")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete_empty(self, *, user_message_id: str, completed_at) -> None:
        connection = self._open()
        try:
            count = connection.execute(
                "SELECT count(*) FROM l1_sufficiency_shadow_candidates "
                "WHERE user_message_id=?", (user_message_id,),
            ).fetchone()[0]
            if count:
                raise ValueError("l1_sufficiency_shadow_candidates_not_empty")
            changed = connection.execute(
                "UPDATE l1_sufficiency_shadow_runs SET status='completed',"
                "completed_at=?,error_code=NULL WHERE user_message_id=? "
                "AND status='pending'",
                (completed_at.isoformat(), user_message_id),
            ).rowcount
            if changed != 1:
                raise ValueError("l1_sufficiency_shadow_state_conflict")
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
            error_code = "l1_sufficiency_shadow_failed"
        connection = self._open()
        try:
            changed = connection.execute(
                "UPDATE l1_sufficiency_shadow_runs SET status='failed',"
                "completed_at=?,error_code=? WHERE user_message_id=? "
                "AND status='pending'",
                (completed_at.isoformat(), error_code, user_message_id),
            ).rowcount
            if changed != 1:
                raise ValueError("l1_sufficiency_shadow_state_conflict")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_recent(self, *, limit: int = 50) -> dict:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("l1_sufficiency_shadow_limit_invalid")
        connection = self._open()
        try:
            rows = connection.execute(
                "SELECT r.user_message_id,m.content AS query,r.retrieval_strategy,"
                "r.reviewer_version,r.provider,r.model,r.status,r.requested_at,"
                "r.completed_at,r.error_code,"
                "(SELECT verdict FROM l1_sufficiency_shadow_review_events v "
                " WHERE v.user_message_id=r.user_message_id "
                " ORDER BY v.review_revision DESC LIMIT 1) AS review_verdict,"
                "(SELECT max(review_revision) FROM l1_sufficiency_shadow_review_events v "
                " WHERE v.user_message_id=r.user_message_id) AS review_revision,"
                "(SELECT count(*) FROM l1_sufficiency_shadow_candidates c "
                " WHERE c.user_message_id=r.user_message_id) AS candidate_count,"
                "(SELECT count(*) FROM l1_sufficiency_shadow_candidates c "
                " WHERE c.user_message_id=r.user_message_id AND c.supports_answer=1) "
                "AS supported_count FROM l1_sufficiency_shadow_runs r "
                "JOIN conversation_messages m ON m.id=r.user_message_id "
                "ORDER BY r.requested_at DESC,r.user_message_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            counts = connection.execute(
                "WITH latest AS ("
                " SELECT e.user_message_id,e.verdict FROM l1_sufficiency_shadow_review_events e "
                " JOIN (SELECT user_message_id,max(review_revision) revision "
                "       FROM l1_sufficiency_shadow_review_events GROUP BY user_message_id) x "
                " ON x.user_message_id=e.user_message_id AND x.revision=e.review_revision"
                ") SELECT "
                "sum(CASE WHEN r.status='completed' THEN 1 ELSE 0 END) completed,"
                "sum(CASE WHEN r.status='completed' AND l.verdict IS NULL THEN 1 ELSE 0 END) unreviewed,"
                "sum(CASE WHEN l.verdict='correct' THEN 1 ELSE 0 END) correct,"
                "sum(CASE WHEN l.verdict='incorrect' THEN 1 ELSE 0 END) incorrect,"
                "sum(CASE WHEN l.verdict='uncertain' THEN 1 ELSE 0 END) uncertain "
                "FROM l1_sufficiency_shadow_runs r LEFT JOIN latest l "
                "ON l.user_message_id=r.user_message_id"
            ).fetchone()
            return {
                "items": [dict(row) for row in rows], "limit": limit,
                "review_counts": {
                    key: int(counts[key] or 0)
                    for key in ("completed", "unreviewed", "correct", "incorrect", "uncertain")
                },
            }
        finally:
            connection.close()

    def get(self, user_message_id: str) -> dict | None:
        if not isinstance(user_message_id, str) or not user_message_id.strip():
            raise ValueError("l1_sufficiency_shadow_id_invalid")
        connection = self._open()
        try:
            run = connection.execute(
                "SELECT r.*,m.content AS query FROM l1_sufficiency_shadow_runs r "
                "JOIN conversation_messages m ON m.id=r.user_message_id "
                "WHERE r.user_message_id=?", (user_message_id,),
            ).fetchone()
            if run is None:
                return None
            candidates = []
            for row in connection.execute(
                "SELECT c.*,a.content AS current_content,a.retired_at "
                "FROM l1_sufficiency_shadow_candidates c "
                "LEFT JOIN atomic_memories a ON a.id=c.memory_id "
                "WHERE c.user_message_id=? ORDER BY c.rank", (user_message_id,),
            ).fetchall():
                item = dict(row)
                current = row["current_content"]
                item["current_status"] = (
                    None if current is None else
                    "retired" if row["retired_at"] is not None else "current"
                )
                item["content_matches_snapshot"] = (
                    None if current is None else
                    sha256(current.encode("utf-8")).hexdigest() == row["content_sha256"]
                )
                candidates.append(item)
            payload = dict(run)
            payload["candidates"] = candidates
            review = connection.execute(
                "SELECT verdict,reason_code,review_revision,occurred_at "
                "FROM l1_sufficiency_shadow_review_events WHERE user_message_id=? "
                "ORDER BY review_revision DESC LIMIT 1", (user_message_id,),
            ).fetchone()
            payload["review"] = dict(review) if review is not None else {
                "verdict": None, "reason_code": None,
                "review_revision": 0, "occurred_at": None,
            }
            return payload
        finally:
            connection.close()

    def review(self, *, user_message_id: str, verdict: str, reason_code: str,
               expected_review_revision: int) -> dict:
        allowed = {
            "correct": {"agreement"},
            "incorrect": {"missed_support", "false_support", "stale_content", "other"},
            "uncertain": {"ambiguous_query", "stale_content", "other"},
        }
        if verdict not in allowed or reason_code not in allowed[verdict]:
            raise ValueError("l1_sufficiency_shadow_review_invalid")
        if type(expected_review_revision) is not int or expected_review_revision < 0:
            raise ValueError("l1_sufficiency_shadow_review_invalid")
        connection = self._open()
        try:
            run = connection.execute(
                "SELECT status FROM l1_sufficiency_shadow_runs WHERE user_message_id=?",
                (user_message_id,),
            ).fetchone()
            if run is None:
                raise ValueError("l1_sufficiency_shadow_not_found")
            if run["status"] != "completed":
                raise ValueError("l1_sufficiency_shadow_review_not_ready")
            current = connection.execute(
                "SELECT max(review_revision) FROM l1_sufficiency_shadow_review_events "
                "WHERE user_message_id=?", (user_message_id,),
            ).fetchone()[0] or 0
            if current != expected_review_revision:
                raise ValueError("l1_sufficiency_shadow_review_conflict")
            revision = current + 1
            occurred_at = datetime.now(UTC).isoformat()
            connection.execute(
                "INSERT INTO l1_sufficiency_shadow_review_events "
                "(id,user_message_id,review_revision,verdict,reason_code,occurred_at) "
                "VALUES (?,?,?,?,?,?)",
                (str(uuid4()), user_message_id, revision, verdict,
                 reason_code, occurred_at),
            )
            connection.commit()
            return {
                "verdict": verdict, "reason_code": reason_code,
                "review_revision": revision, "occurred_at": occurred_at,
            }
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
