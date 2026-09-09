"""记忆质量样本的只追加复核状态；不保存问题、回答或记忆正文。"""

from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from uuid import uuid4


_ACTION_STATE = {"resolve": "resolved", "dismiss": "dismissed", "reopen": "open"}
_ACTION_REASONS = {
    "resolve": {"memory_corrected", "retrieval_fixed", "answer_behavior_fixed", "other"},
    "dismiss": {"false_positive", "not_memory_issue", "other"},
    "reopen": {"needs_follow_up"},
}


class SQLiteMemoryFeedbackReviewStore:
    """以乐观 revision 更新内部工作队列，同时保留完整操作历史。"""

    def __init__(self, database: Path, *, clock=None) -> None:
        self._database = database.resolve()
        self._clock = clock or (lambda: datetime.now(UTC))

    def current(self, targets: tuple[tuple[str, str, int], ...]) -> dict[tuple[str, str, int], dict]:
        if not targets:
            return {}
        wanted = set(targets)
        connection = sqlite3.connect(
            self._database.as_uri() + "?mode=ro", uri=True, timeout=2,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        try:
            result = {target: self._state(None) for target in wanted}
            # 事件表不含正文，按 revision 倒序一次读取即可，避免样本列表形成
            # N+1 次查询；只把调用方明确请求的目标投影进结果。
            rows = connection.execute(
                "SELECT feedback_source,feedback_target_id,feedback_revision,"
                "action,reason_code,review_revision,occurred_at FROM "
                "memory_feedback_review_events ORDER BY review_revision DESC"
            ).fetchall()
            seen = set()
            for row in rows:
                key = (row["feedback_source"], row["feedback_target_id"],
                       row["feedback_revision"])
                if key in wanted and key not in seen:
                    result[key] = self._state(row)
                    seen.add(key)
            return result
        finally:
            connection.close()

    def record(
        self, *, source: str, target_id: str, feedback_revision: int,
        action: str, reason_code: str, expected_review_revision: int,
    ) -> dict:
        if source not in {"web_chat", "round_screen"}:
            raise ValueError("memory_feedback_review_invalid")
        if action not in _ACTION_REASONS or reason_code not in _ACTION_REASONS[action]:
            raise ValueError("memory_feedback_review_invalid")
        connection = sqlite3.connect(
            self._database.as_uri() + "?mode=rw", uri=True, timeout=2,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        try:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                "SELECT action,reason_code,review_revision,occurred_at FROM "
                "memory_feedback_review_events WHERE feedback_source=? "
                "AND feedback_target_id=? AND feedback_revision=? "
                "ORDER BY review_revision DESC LIMIT 1",
                (source, target_id, feedback_revision),
            ).fetchone()
            current = self._state(latest)
            if current["review_revision"] != expected_review_revision:
                raise ValueError("memory_feedback_review_conflict")
            if (current["state"] == "open") != (action != "reopen"):
                raise ValueError("memory_feedback_review_transition_invalid")
            occurred_at = self._clock().isoformat()
            next_revision = expected_review_revision + 1
            connection.execute(
                "INSERT INTO memory_feedback_review_events "
                "(id,feedback_source,feedback_target_id,feedback_revision,action,"
                "reason_code,review_revision,occurred_at) VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid4()), source, target_id, feedback_revision, action,
                 reason_code, next_revision, occurred_at),
            )
            connection.commit()
            return {"state": _ACTION_STATE[action], "reason_code": reason_code,
                    "review_revision": next_revision, "occurred_at": occurred_at}
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _state(row) -> dict:
        if row is None:
            return {"state": "open", "reason_code": None,
                    "review_revision": 0, "occurred_at": None}
        return {"state": _ACTION_STATE[row["action"]],
                "reason_code": row["reason_code"],
                "review_revision": row["review_revision"],
                "occurred_at": row["occurred_at"]}
