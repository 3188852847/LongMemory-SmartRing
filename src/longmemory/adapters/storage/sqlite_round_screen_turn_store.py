"""圆屏最终回答与既有用户 L0 的 SQLite 原子关联。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from uuid import uuid4


@dataclass(frozen=True)
class RoundScreenTurnResult:
    assistant_message_id: str
    created: bool


class SQLiteRoundScreenTurnStore:
    """保存实际助手文本，但不把服务端排队冒充圆屏已播放。"""

    def __init__(self, database: Path, clock=lambda: datetime.now(UTC)) -> None:
        self._database = database.resolve()
        self._clock = clock

    def record(self, *, user_message_id: str, answer: str,
               retrieved_l1_count: int, retrieved_l2_count: int,
               retrieved_l3_count: int) -> RoundScreenTurnResult:
        connection = sqlite3.connect(
            self._database.as_uri() + "?mode=rw", uri=True, timeout=2,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT assistant_message_id,retrieved_l1_count,retrieved_l2_count,"
                "retrieved_l3_count FROM round_screen_turns WHERE user_message_id=?",
                (user_message_id,),
            ).fetchone()
            if existing is not None:
                saved = connection.execute(
                    "SELECT content FROM conversation_messages WHERE id=? AND role='assistant'",
                    (existing["assistant_message_id"],),
                ).fetchone()
                same = (
                    saved is not None and saved["content"] == answer
                    and existing["retrieved_l1_count"] == retrieved_l1_count
                    and existing["retrieved_l2_count"] == retrieved_l2_count
                    and existing["retrieved_l3_count"] == retrieved_l3_count
                )
                if not same:
                    raise ValueError("round_screen_turn_conflict")
                connection.rollback()
                return RoundScreenTurnResult(existing["assistant_message_id"], False)
            source = connection.execute(
                "SELECT role FROM conversation_messages WHERE id=?",
                (user_message_id,),
            ).fetchone()
            if source is None or source["role"] != "user":
                raise ValueError("round_screen_user_turn_not_found")
            assistant_id = str(uuid4())
            completed_at = self._clock().isoformat()
            connection.execute(
                "INSERT INTO conversation_messages (id,role,content,created_at) "
                "VALUES (?,'assistant',?,?)",
                (assistant_id, answer, completed_at),
            )
            connection.execute(
                "INSERT INTO round_screen_turns "
                "(user_message_id,assistant_message_id,retrieved_l1_count,"
                "retrieved_l2_count,retrieved_l3_count,completed_at) "
                "VALUES (?,?,?,?,?,?)",
                (user_message_id, assistant_id, retrieved_l1_count,
                 retrieved_l2_count, retrieved_l3_count, completed_at),
            )
            connection.commit()
            return RoundScreenTurnResult(assistant_id, True)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
