"""L0 原始对话的 SQLite 存储适配器。"""

from datetime import datetime
from sqlite3 import Connection

from longmemory.core.common.identifiers import MessageId
from longmemory.core.conversation.models import (
    ConversationMessage,
    MessageRole,
)


class SQLiteConversationStore:
    """使用 SQLite 实现 ConversationStore 契约。"""

    def __init__(self, connection: Connection, *, commit_changes: bool = True) -> None:
        self._connection = connection
        self._commit_changes = commit_changes

    def save(self, message: ConversationMessage) -> None:
        """持久化一条原始消息。"""

        self._connection.execute(
            """
            INSERT INTO conversation_messages (
                id,
                role,
                content,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                str(message.id),
                message.role.value,
                message.content,
                message.created_at.isoformat(),
            ),
        )
        if self._commit_changes:
            self._connection.commit()

    def get(self, message_id: MessageId) -> ConversationMessage | None:
        """根据 ID 读取一条原始消息。"""

        row = self._connection.execute(
            """
            SELECT id, role, content, created_at
            FROM conversation_messages
            WHERE id = ?
            """,
            (str(message_id),),
        ).fetchone()

        if row is None:
            return None

        return ConversationMessage(
            id=MessageId(row["id"]),
            role=MessageRole(row["role"]),
            content=row["content"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
