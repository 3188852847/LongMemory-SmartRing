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
                    "(user_message_id,memory_id,rank,content_sha256,content_characters,"
                    "keyword_score,dense_score,fused_score) VALUES (?,?,?,?,?,?,?,?)",
                    (user_message_id, item.item_id, rank,
                     sha256(item.content.encode("utf-8")).hexdigest(),
                     len(item.content),
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
                "policy_metrics": self._policy_metrics(connection),
            }
        finally:
            connection.close()

    @staticmethod
    def _policy_metrics(connection) -> dict:
        """只用每轮最新且带精确人工集合的复核计算离线门控代理。"""

        from longmemory.core.memory.quality.l1_gate_readiness import (
            assess_l1_gate_readiness,
        )

        latest = connection.execute(
            "SELECT e.id,e.user_message_id,e.support_set_recorded FROM "
            "l1_sufficiency_shadow_review_events e JOIN ("
            " SELECT user_message_id,max(review_revision) revision "
            " FROM l1_sufficiency_shadow_review_events GROUP BY user_message_id"
            ") x ON x.user_message_id=e.user_message_id "
            "AND x.revision=e.review_revision ORDER BY e.occurred_at,e.id"
        ).fetchall()
        totals = {
            "reviewed_cases": len(latest), "labeled_cases": 0,
            "answerable_labeled_cases": 0, "unsupported_labeled_cases": 0,
            "false_block_cases": 0, "unsupported_pass_cases": 0,
            "incomplete_allow_cases": 0, "overinclusive_allow_cases": 0,
            "original_candidate_count": 0, "kept_candidate_count": 0,
            "true_positive_count": 0, "false_positive_count": 0,
            "missed_support_count": 0, "context_measured_cases": 0,
            "original_context_characters": 0, "kept_context_characters": 0,
        }
        for review in latest:
            if not review["support_set_recorded"]:
                continue
            candidates = connection.execute(
                "SELECT memory_id,supports_answer,content_characters "
                "FROM l1_sufficiency_shadow_candidates WHERE user_message_id=? "
                "ORDER BY rank", (review["user_message_id"],),
            ).fetchall()
            expected = {
                row["memory_id"] for row in connection.execute(
                    "SELECT memory_id FROM l1_sufficiency_shadow_review_supports "
                    "WHERE review_event_id=?", (review["id"],),
                ).fetchall()
            }
            predicted = {
                row["memory_id"] for row in candidates if row["supports_answer"] == 1
            }
            totals["labeled_cases"] += 1
            totals[
                "answerable_labeled_cases" if expected
                else "unsupported_labeled_cases"
            ] += 1
            totals["false_block_cases"] += bool(expected) and not predicted
            totals["unsupported_pass_cases"] += not expected and bool(predicted)
            totals["incomplete_allow_cases"] += bool(expected and predicted and expected - predicted)
            totals["overinclusive_allow_cases"] += bool(predicted and predicted - expected)
            totals["original_candidate_count"] += len(candidates)
            totals["kept_candidate_count"] += len(predicted)
            totals["true_positive_count"] += len(expected & predicted)
            totals["false_positive_count"] += len(predicted - expected)
            totals["missed_support_count"] += len(expected - predicted)
            if all(row["content_characters"] is not None for row in candidates):
                totals["context_measured_cases"] += 1
                totals["original_context_characters"] += sum(
                    row["content_characters"] for row in candidates
                )
                totals["kept_context_characters"] += sum(
                    row["content_characters"] for row in candidates
                    if row["memory_id"] in predicted
                )
        original = totals["original_candidate_count"]
        original_chars = totals["original_context_characters"]
        predicted_positive = totals["true_positive_count"] + totals["false_positive_count"]
        expected_positive = totals["true_positive_count"] + totals["missed_support_count"]
        totals.update({
            "excluded_latest_reviews": totals["reviewed_cases"] - totals["labeled_cases"],
            "removed_candidate_count": original - totals["kept_candidate_count"],
            "candidate_reduction_rate": (
                None if not original else round(
                    (original - totals["kept_candidate_count"]) / original, 6,
                )
            ),
            "context_character_reduction_rate": (
                None if not original_chars else round(
                    (original_chars - totals["kept_context_characters"]) / original_chars, 6,
                )
            ),
            "candidate_precision": (
                None if not predicted_positive else round(
                    totals["true_positive_count"] / predicted_positive, 6,
                )
            ),
            "candidate_recall": (
                None if not expected_positive else round(
                    totals["true_positive_count"] / expected_positive, 6,
                )
            ),
        })
        totals["readiness"] = assess_l1_gate_readiness(totals)
        return totals

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
                "SELECT id,verdict,reason_code,review_revision,occurred_at,"
                "support_set_recorded "
                "FROM l1_sufficiency_shadow_review_events WHERE user_message_id=? "
                "ORDER BY review_revision DESC LIMIT 1", (user_message_id,),
            ).fetchone()
            if review is not None:
                review_payload = dict(review)
                review_payload["expected_supported_memory_ids"] = (
                    [row["memory_id"] for row in connection.execute(
                        "SELECT memory_id FROM l1_sufficiency_shadow_review_supports "
                        "WHERE review_event_id=? ORDER BY memory_id", (review["id"],),
                    ).fetchall()]
                    if review["support_set_recorded"] else None
                )
                review_payload.pop("id")
                review_payload.pop("support_set_recorded")
                payload["review"] = review_payload
            else:
                payload["review"] = {
                    "verdict": None, "reason_code": None,
                    "review_revision": 0, "occurred_at": None,
                    "expected_supported_memory_ids": None,
                }
            return payload
        finally:
            connection.close()

    def review(self, *, user_message_id: str, verdict: str, reason_code: str,
               expected_review_revision: int,
               expected_supported_memory_ids: list[str] | None = None) -> dict:
        allowed = {
            "correct": {"agreement"},
            "incorrect": {"missed_support", "false_support", "stale_content", "other"},
            "uncertain": {"ambiguous_query", "stale_content", "other"},
        }
        if verdict not in allowed or reason_code not in allowed[verdict]:
            raise ValueError("l1_sufficiency_shadow_review_invalid")
        if type(expected_review_revision) is not int or expected_review_revision < 0:
            raise ValueError("l1_sufficiency_shadow_review_invalid")
        if (expected_supported_memory_ids is not None
                and (not isinstance(expected_supported_memory_ids, list)
                     or len(expected_supported_memory_ids) > 100
                     or len(expected_supported_memory_ids) != len(
                         set(expected_supported_memory_ids)
                     )
                     or any(not isinstance(item, str) or not item.strip()
                            for item in expected_supported_memory_ids))):
            raise ValueError("l1_sufficiency_shadow_review_invalid")
        if (verdict == "uncertain") != (expected_supported_memory_ids is None):
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
            candidates = connection.execute(
                "SELECT memory_id,supports_answer FROM l1_sufficiency_shadow_candidates "
                "WHERE user_message_id=? ORDER BY rank", (user_message_id,),
            ).fetchall()
            available = {row["memory_id"] for row in candidates}
            expected_set = set(expected_supported_memory_ids or ())
            if not expected_set <= available:
                raise ValueError("l1_sufficiency_shadow_review_support_invalid")
            machine_set = {
                row["memory_id"] for row in candidates if row["supports_answer"] == 1
            }
            if ((verdict == "correct" and expected_set != machine_set)
                    or (verdict == "incorrect" and expected_set == machine_set)):
                raise ValueError("l1_sufficiency_shadow_review_verdict_mismatch")
            current = connection.execute(
                "SELECT max(review_revision) FROM l1_sufficiency_shadow_review_events "
                "WHERE user_message_id=?", (user_message_id,),
            ).fetchone()[0] or 0
            if current != expected_review_revision:
                raise ValueError("l1_sufficiency_shadow_review_conflict")
            revision = current + 1
            occurred_at = datetime.now(UTC).isoformat()
            event_id = str(uuid4())
            connection.execute(
                "INSERT INTO l1_sufficiency_shadow_review_events "
                "(id,user_message_id,review_revision,verdict,reason_code,"
                "support_set_recorded,occurred_at) VALUES (?,?,?,?,?,?,?)",
                (event_id, user_message_id, revision, verdict, reason_code,
                 int(expected_supported_memory_ids is not None), occurred_at),
            )
            for memory_id in expected_supported_memory_ids or ():
                connection.execute(
                    "INSERT INTO l1_sufficiency_shadow_review_supports "
                    "(review_event_id,user_message_id,memory_id) VALUES (?,?,?)",
                    (event_id, user_message_id, memory_id),
                )
            connection.commit()
            return {
                "verdict": verdict, "reason_code": reason_code,
                "review_revision": revision, "occurred_at": occurred_at,
                "expected_supported_memory_ids": expected_supported_memory_ids,
            }
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
