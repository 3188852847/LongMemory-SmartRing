"""SQLite V42/V43 的 L2 证据充分性影子审计与人工复核存储。"""

from hashlib import sha256
from datetime import UTC, datetime
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from longmemory.application.scenario_recall import ScenarioRecallResult
from longmemory.core.memory.retrieval.sufficiency import EvidenceSufficiencyReview
from longmemory.adapters.storage.sqlite_sufficiency_policy_metrics import (
    calculate_policy_metrics,
)


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
                    "(user_message_id,scenario_id,rank,content_sha256,keyword_score,"
                    "content_characters) VALUES (?,?,?,?,?,?)",
                    (user_message_id, item.scenario_id, rank, digest,
                     item.keyword_score, len(f"{item.title}：{item.summary}")),
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

    def list_recent(self, *, limit: int = 50) -> dict:
        """为本机所有者列出近期运行；正文只从已有 L0 按需读取。"""

        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("l2_sufficiency_shadow_limit_invalid")
        connection = self._open()
        try:
            rows = connection.execute(
                "SELECT r.user_message_id,m.content AS query,r.retrieval_strategy,"
                "r.reviewer_version,r.provider,r.model,r.status,r.requested_at,"
                "r.completed_at,r.error_code,"
                "(SELECT verdict FROM l2_sufficiency_shadow_review_events v "
                " WHERE v.user_message_id=r.user_message_id "
                " ORDER BY v.review_revision DESC LIMIT 1) AS review_verdict,"
                "(SELECT max(review_revision) FROM l2_sufficiency_shadow_review_events v "
                " WHERE v.user_message_id=r.user_message_id) AS review_revision,"
                "(SELECT count(*) FROM l2_sufficiency_shadow_candidates c "
                " WHERE c.user_message_id=r.user_message_id) AS candidate_count,"
                "(SELECT count(*) FROM l2_sufficiency_shadow_candidates c "
                " WHERE c.user_message_id=r.user_message_id AND c.supports_answer=1) "
                "AS supported_count "
                "FROM l2_sufficiency_shadow_runs r "
                "JOIN conversation_messages m ON m.id=r.user_message_id "
                "ORDER BY r.requested_at DESC,r.user_message_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            counts = connection.execute(
                "WITH latest AS ("
                " SELECT e.user_message_id,e.verdict FROM l2_sufficiency_shadow_review_events e "
                " JOIN (SELECT user_message_id,max(review_revision) revision "
                "       FROM l2_sufficiency_shadow_review_events GROUP BY user_message_id) x "
                " ON x.user_message_id=e.user_message_id AND x.revision=e.review_revision"
                ") SELECT "
                "sum(CASE WHEN r.status='completed' THEN 1 ELSE 0 END) completed,"
                "sum(CASE WHEN r.status='completed' AND l.verdict IS NULL THEN 1 ELSE 0 END) unreviewed,"
                "sum(CASE WHEN l.verdict='correct' THEN 1 ELSE 0 END) correct,"
                "sum(CASE WHEN l.verdict='incorrect' THEN 1 ELSE 0 END) incorrect,"
                "sum(CASE WHEN l.verdict='uncertain' THEN 1 ELSE 0 END) uncertain "
                "FROM l2_sufficiency_shadow_runs r LEFT JOIN latest l "
                "ON l.user_message_id=r.user_message_id"
            ).fetchone()
            return {
                "items": [dict(row) for row in rows], "limit": limit,
                "review_counts": {
                    key: int(counts[key] or 0)
                    for key in ("completed", "unreviewed", "correct", "incorrect", "uncertain")
                },
                "policy_metrics": self._policy_metrics(connection),
            }
        finally:
            connection.close()

    @staticmethod
    def _policy_metrics(connection) -> dict:
        return calculate_policy_metrics(
            connection, layer="l2", candidate_id="scenario_id",
        )

    def get(self, user_message_id: str) -> dict | None:
        """读取单轮候选当前正文，并显式标记是否仍与回答时指纹一致。"""

        if not isinstance(user_message_id, str) or not user_message_id.strip():
            raise ValueError("l2_sufficiency_shadow_id_invalid")
        connection = self._open()
        try:
            run = connection.execute(
                "SELECT r.*,m.content AS query FROM l2_sufficiency_shadow_runs r "
                "JOIN conversation_messages m ON m.id=r.user_message_id "
                "WHERE r.user_message_id=?", (user_message_id,),
            ).fetchone()
            if run is None:
                return None
            rows = connection.execute(
                "SELECT c.*,s.title AS current_title,s.summary AS current_summary,"
                "s.status AS current_status FROM l2_sufficiency_shadow_candidates c "
                "LEFT JOIN scenario_memories s ON s.id=c.scenario_id "
                "WHERE c.user_message_id=? ORDER BY c.rank",
                (user_message_id,),
            ).fetchall()
            candidates = []
            for row in rows:
                item = dict(row)
                if row["current_title"] is None or row["current_summary"] is None:
                    item["content_matches_snapshot"] = None
                else:
                    current = f'{row["current_title"]}：{row["current_summary"]}'
                    item["content_matches_snapshot"] = (
                        sha256(current.encode("utf-8")).hexdigest()
                        == row["content_sha256"]
                    )
                candidates.append(item)
            payload = dict(run)
            payload["candidates"] = candidates
            review = connection.execute(
                "SELECT id,verdict,reason_code,review_revision,occurred_at,"
                "support_set_recorded "
                "FROM l2_sufficiency_shadow_review_events "
                "WHERE user_message_id=? ORDER BY review_revision DESC LIMIT 1",
                (user_message_id,),
            ).fetchone()
            if review is not None:
                review_payload = dict(review)
                review_payload["expected_supported_scenario_ids"] = (
                    [row["scenario_id"] for row in connection.execute(
                        "SELECT scenario_id FROM l2_sufficiency_shadow_review_supports "
                        "WHERE review_event_id=? ORDER BY scenario_id", (review["id"],),
                    ).fetchall()] if review["support_set_recorded"] else None
                )
                review_payload.pop("id")
                review_payload.pop("support_set_recorded")
            else:
                review_payload = {
                    "verdict": None, "reason_code": None,
                    "review_revision": 0, "occurred_at": None,
                    "expected_supported_scenario_ids": None,
                }
            payload["review"] = review_payload
            return payload
        finally:
            connection.close()

    def review(self, *, user_message_id: str, verdict: str, reason_code: str,
               expected_review_revision: int,
               expected_supported_scenario_ids: list[str] | None) -> dict:
        """追加所有者复核；机器判定和候选快照保持原样。"""

        allowed_reasons = {
            "correct": {"agreement"},
            "incorrect": {"missed_support", "false_support", "stale_content", "other"},
            "uncertain": {"ambiguous_query", "stale_content", "other"},
        }
        if verdict not in allowed_reasons or reason_code not in allowed_reasons[verdict]:
            raise ValueError("l2_sufficiency_shadow_review_invalid")
        if type(expected_review_revision) is not int or expected_review_revision < 0:
            raise ValueError("l2_sufficiency_shadow_review_invalid")
        if (expected_supported_scenario_ids is not None
                and (not isinstance(expected_supported_scenario_ids, list)
                     or len(expected_supported_scenario_ids) > 100
                     or len(expected_supported_scenario_ids)
                     != len(set(expected_supported_scenario_ids))
                     or any(not isinstance(item, str) or not item.strip()
                            for item in expected_supported_scenario_ids))):
            raise ValueError("l2_sufficiency_shadow_review_invalid")
        if (verdict == "uncertain") != (expected_supported_scenario_ids is None):
            raise ValueError("l2_sufficiency_shadow_review_invalid")
        connection = self._open()
        try:
            run = connection.execute(
                "SELECT status FROM l2_sufficiency_shadow_runs WHERE user_message_id=?",
                (user_message_id,),
            ).fetchone()
            if run is None:
                raise ValueError("l2_sufficiency_shadow_not_found")
            if run["status"] != "completed":
                raise ValueError("l2_sufficiency_shadow_review_not_ready")
            candidates = connection.execute(
                "SELECT scenario_id,supports_answer FROM "
                "l2_sufficiency_shadow_candidates WHERE user_message_id=?",
                (user_message_id,),
            ).fetchall()
            available = {row["scenario_id"] for row in candidates}
            expected = set(expected_supported_scenario_ids or ())
            if not expected <= available:
                raise ValueError("l2_sufficiency_shadow_review_support_invalid")
            predicted = {
                row["scenario_id"] for row in candidates if row["supports_answer"] == 1
            }
            if ((verdict == "correct" and expected != predicted)
                    or (verdict == "incorrect" and expected == predicted)):
                raise ValueError("l2_sufficiency_shadow_review_verdict_mismatch")
            current = connection.execute(
                "SELECT max(review_revision) FROM l2_sufficiency_shadow_review_events "
                "WHERE user_message_id=?", (user_message_id,),
            ).fetchone()[0] or 0
            if current != expected_review_revision:
                raise ValueError("l2_sufficiency_shadow_review_conflict")
            revision = current + 1
            occurred_at = datetime.now(UTC).isoformat()
            review_id = str(uuid4())
            connection.execute(
                "INSERT INTO l2_sufficiency_shadow_review_events "
                "(id,user_message_id,review_revision,verdict,reason_code,"
                "support_set_recorded,occurred_at) VALUES (?,?,?,?,?,?,?)",
                (review_id, user_message_id, revision, verdict, reason_code,
                 int(expected_supported_scenario_ids is not None), occurred_at),
            )
            for scenario_id in expected_supported_scenario_ids or ():
                connection.execute(
                    "INSERT INTO l2_sufficiency_shadow_review_supports "
                    "(review_event_id,user_message_id,scenario_id) VALUES (?,?,?)",
                    (review_id, user_message_id, scenario_id),
                )
            connection.commit()
            return {
                "verdict": verdict, "reason_code": reason_code,
                "review_revision": revision, "occurred_at": occurred_at,
                "expected_supported_scenario_ids": (
                    expected_supported_scenario_ids
                ),
            }
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
