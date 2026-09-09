"""从仍有效的 L1/L0 证据解析当前临时互动方式。"""

from datetime import datetime
from pathlib import Path

from longmemory.application.temporary_interaction import (
    TemporaryInteractionDirective,
    classify_temporary_interaction,
    directive_context,
)
from longmemory.infrastructure.database.connection import open_database


class SQLiteTemporaryInteractionProvider:
    """读取最新明确设置；不持有连接，也不把用户原话当作系统提示。"""

    def __init__(self, database: Path) -> None:
        self._database = database.resolve()

    def current(self, *, at: datetime) -> TemporaryInteractionDirective | None:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("temporary_interaction_time_timezone_required")
        moment = at.isoformat()
        connection = open_database(self._database)
        try:
            rows = connection.execute(
                "SELECT a.id AS memory_id,a.content AS memory_content,a.valid_to,"
                "m.id AS message_id,m.content AS message_content "
                "FROM atomic_memories a "
                "JOIN memory_evidence e ON e.memory_id=a.id "
                "JOIN conversation_messages m ON m.id=e.source_message_id "
                "WHERE a.subject_id='user:self' AND a.retired_at IS NULL "
                "AND a.valid_to IS NOT NULL AND m.role='user' "
                "AND (a.valid_from IS NULL OR julianday(a.valid_from)<=julianday(?)) "
                "ORDER BY a.recorded_at DESC,e.linked_at DESC,a.id DESC",
                (moment,),
            ).fetchall()
        finally:
            connection.close()
        for row in rows:
            mode = classify_temporary_interaction(row["message_content"])
            if mode is not None:
                # 最新一次明确选择一旦到期就恢复长期默认；不能让更早的
                # 临时选择在新选择结束后意外“复活”。
                if datetime.fromisoformat(row["valid_to"]) <= at:
                    return None
                if mode == "default":
                    return None
                return TemporaryInteractionDirective(
                    mode=mode,
                    source_memory_id=row["memory_id"],
                    source_content=row["memory_content"],
                    source_message_id=row["message_id"],
                    valid_to=row["valid_to"],
                    context=directive_context(mode),
                )
        return None
