"""把圆屏明确反馈关联到最近一次已完成问答，不复制对话正文。"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from uuid import uuid4

from longmemory.application.round_screen_memory_feedback import (
    INTERPRETER_VERSION,
    classify_explicit_round_screen_feedback,
)
from longmemory.methods.contracts import MemoryEvent


@dataclass(frozen=True, slots=True)
class RoundScreenMemoryFeedbackResult:
    kind: str
    recorded: bool
    target_user_message_id: str | None
    reason: str | None


class SQLiteRoundScreenMemoryFeedbackStore:
    """保存十分钟内对最近一轮圆屏回答的明确质量反馈。"""

    _MAXIMUM_AGE = timedelta(minutes=10)

    def __init__(self, database: Path) -> None:
        self._database = database.resolve()

    def record_if_explicit(
        self, event: MemoryEvent,
    ) -> RoundScreenMemoryFeedbackResult | None:
        kind = classify_explicit_round_screen_feedback(event.content)
        if kind is None:
            return None
        connection = sqlite3.connect(
            self._database.as_uri() + "?mode=rw", uri=True, timeout=2,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT target_user_message_id,event_kind FROM "
                "round_screen_memory_feedback_events WHERE feedback_message_id=?",
                (event.event_id,),
            ).fetchone()
            if existing is not None:
                if existing["event_kind"] != kind:
                    raise ValueError("round_screen_feedback_conflict")
                connection.rollback()
                return RoundScreenMemoryFeedbackResult(
                    kind, True, existing["target_user_message_id"], None,
                )
            source = connection.execute(
                "SELECT role FROM conversation_messages WHERE id=?",
                (event.event_id,),
            ).fetchone()
            if source is None or source["role"] != "user":
                raise ValueError("round_screen_feedback_source_not_found")
            target = connection.execute(
                "SELECT user_message_id,completed_at FROM round_screen_turns "
                "WHERE completed_at<=? ORDER BY completed_at DESC,user_message_id DESC LIMIT 1",
                (event.occurred_at.isoformat(),),
            ).fetchone()
            if target is None:
                connection.rollback()
                return RoundScreenMemoryFeedbackResult(kind, False, None, "no_previous_turn")
            completed_at = datetime.fromisoformat(target["completed_at"])
            age = event.occurred_at - completed_at
            if age < timedelta(0) or age > self._MAXIMUM_AGE:
                connection.rollback()
                return RoundScreenMemoryFeedbackResult(kind, False, None, "previous_turn_too_old")
            connection.execute(
                "INSERT INTO round_screen_memory_feedback_events "
                "(id,target_user_message_id,feedback_message_id,event_kind,evidence_kind,"
                "interpreter_version,occurred_at) VALUES (?,?,?,?,?,?,?)",
                (
                    str(uuid4()), target["user_message_id"], event.event_id, kind,
                    "explicit_round_screen_statement", INTERPRETER_VERSION,
                    event.occurred_at.isoformat(),
                ),
            )
            connection.commit()
            return RoundScreenMemoryFeedbackResult(
                kind, True, target["user_message_id"], None,
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_events(self) -> tuple[dict, ...]:
        """返回控制台诊断所需的无正文元数据。"""

        connection = sqlite3.connect(
            self._database.as_uri() + "?mode=ro", uri=True, timeout=2,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        try:
            rows = connection.execute(
                "SELECT f.target_user_message_id,f.feedback_message_id,f.event_kind,"
                "f.occurred_at,t.assistant_message_id,t.retrieved_l1_count,"
                "t.retrieved_l2_count,t.retrieved_l3_count "
                "FROM round_screen_memory_feedback_events f "
                "JOIN round_screen_turns t ON t.user_message_id=f.target_user_message_id "
                "ORDER BY f.occurred_at DESC,f.id DESC"
            ).fetchall()
            return tuple(dict(row) for row in rows)
        finally:
            connection.close()
