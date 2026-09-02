"""L1 原子记忆及其来源关系的 SQLite 存储适配器。"""

from datetime import datetime
from sqlite3 import Connection, Row

from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.memory.models import AtomicMemory


class SQLiteMemoryStore:
    """使用 SQLite 实现 MemoryStore 契约。"""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def save(self, memory: AtomicMemory) -> None:
        """持久化一条原子记忆。"""

        self._connection.execute(
            """
            INSERT INTO atomic_memories (
                id,
                content,
                source_message_id,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                str(memory.id),
                memory.content,
                str(memory.source_message_id),
                memory.created_at.isoformat(),
            ),
        )
        self._connection.commit()

    def get(self, memory_id: MemoryId) -> AtomicMemory | None:
        """根据 ID 读取一条原子记忆。"""

        row = self._connection.execute(
            """
            SELECT id, content, source_message_id, created_at
            FROM atomic_memories
            WHERE id = ?
            """,
            (str(memory_id),),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_memory(row)

    def list_all(self) -> tuple[AtomicMemory, ...]:
        """按照创建时间和 ID 返回全部记忆。"""

        rows = self._connection.execute(
            """
            SELECT id, content, source_message_id, created_at
            FROM atomic_memories
            ORDER BY created_at ASC, id ASC
            """
        ).fetchall()

        return tuple(self._row_to_memory(row) for row in rows)

    def delete(self, memory_id: MemoryId) -> bool:
        """删除指定记忆，并返回是否删除成功。"""

        cursor = self._connection.execute(
            """
            DELETE FROM atomic_memories
            WHERE id = ?
            """,
            (str(memory_id),),
        )
        self._connection.commit()

        return cursor.rowcount == 1

    @staticmethod
    def _row_to_memory(row: Row) -> AtomicMemory:
        """把 SQLite 查询结果恢复成领域模型。"""

        return AtomicMemory(
            id=MemoryId(row["id"]),
            content=row["content"],
            source_message_id=MessageId(row["source_message_id"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )