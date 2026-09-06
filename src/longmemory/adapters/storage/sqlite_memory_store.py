"""L1 原子记忆及其来源关系的 SQLite 存储适配器。"""

from datetime import datetime
from sqlite3 import Connection, Row

from longmemory.core.common.identifiers import (
    MemoryId,
    MemorySubjectId,
    MessageId,
)
from longmemory.core.memory.l1_atomic.models import (
    AtomicMemory,
    MemoryEvidence,
    MemorySourceType,
)


class SQLiteMemoryStore:
    """使用 SQLite 实现 MemoryStore 契约。"""

    def __init__(self, connection: Connection, *, commit_changes: bool = True) -> None:
        self._connection = connection
        # 用例拥有整轮事务时，存储操作不能提前释放 SQLite 写锁。
        self._commit_changes = commit_changes

    def save(
        self,
        memory: AtomicMemory,
        evidence: MemoryEvidence,
    ) -> None:
        """在同一事务中保存原子记忆及其首条来源证据。"""

        if evidence.memory_id != memory.id:
            raise ValueError("来源证据必须指向正在保存的记忆。")
        try:
            self._connection.execute(
                """
                INSERT INTO atomic_memories (
                    id,
                    subject_id,
                    content,
                    recorded_at,
                    valid_from,
                    valid_to,
                    retired_at,
                    superseded_by_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(memory.id),
                    str(memory.subject_id),
                    memory.content,
                    memory.recorded_at.isoformat(),
                    self._optional_datetime_to_text(memory.valid_from),
                    self._optional_datetime_to_text(memory.valid_to),
                    self._optional_datetime_to_text(memory.retired_at),
                    (
                        str(memory.superseded_by_id)
                        if memory.superseded_by_id is not None
                        else None
                    ),
                ),
            )
            self._insert_evidence(evidence)
            if self._commit_changes:
                self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def add_evidence(self, evidence: MemoryEvidence) -> bool:
        """给已有记忆增加来源证据，重复关联不会重复写入。"""

        try:
            cursor = self._insert_evidence(evidence)
            if self._commit_changes:
                self._connection.commit()
            return cursor.rowcount == 1
        except BaseException:
            self._connection.rollback()
            raise

    def list_evidence(
        self,
        memory_id: MemoryId,
    ) -> tuple[MemoryEvidence, ...]:
        """按关联时间和消息 ID 返回全部来源证据。"""

        rows = self._connection.execute(
            """
            SELECT
                memory_id,
                source_message_id,
                source_type,
                linked_at
            FROM memory_evidence
            WHERE memory_id = ?
            ORDER BY linked_at ASC, source_message_id ASC
            """,
            (str(memory_id),),
        ).fetchall()

        return tuple(
            MemoryEvidence(
                memory_id=MemoryId(row["memory_id"]),
                source_message_id=MessageId(row["source_message_id"]),
                source_type=MemorySourceType(row["source_type"]),
                linked_at=datetime.fromisoformat(row["linked_at"]),
            )
            for row in rows
        )

    def get(self, memory_id: MemoryId) -> AtomicMemory | None:
        """根据 ID 读取一条原子记忆。"""

        row = self._connection.execute(
            """
            SELECT
                id,
                subject_id,
                content,
                recorded_at,
                valid_from,
                valid_to,
                retired_at,
                superseded_by_id
            FROM atomic_memories
            WHERE id = ?
            """,
            (str(memory_id),),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_memory(row)

    def find_by_content(
        self,
        content: str,
        *,
        subject_id: MemorySubjectId,
    ) -> AtomicMemory | None:
        """查找同一主体内容完全相同的当前有效记忆。"""

        row = self._connection.execute(
            """
            SELECT
                id,
                subject_id,
                content,
                recorded_at,
                valid_from,
                valid_to,
                retired_at,
                superseded_by_id
            FROM atomic_memories
            WHERE subject_id = ?
              AND content = ?
              AND retired_at IS NULL
            ORDER BY recorded_at ASC, id ASC
            LIMIT 1
            """,
            (str(subject_id), content),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_memory(row)

    def list_all(self) -> tuple[AtomicMemory, ...]:
        """按照记录时间和 ID 返回全部记忆，包括已退役历史。"""

        rows = self._connection.execute(
            """
            SELECT
                id,
                subject_id,
                content,
                recorded_at,
                valid_from,
                valid_to,
                retired_at,
                superseded_by_id
            FROM atomic_memories
            ORDER BY recorded_at ASC, id ASC
            """
        ).fetchall()

        return tuple(self._row_to_memory(row) for row in rows)

    def list_active(self) -> tuple[AtomicMemory, ...]:
        """按照记录时间和 ID 返回当前有效记忆。"""

        rows = self._connection.execute(
            """
            SELECT
                id,
                subject_id,
                content,
                recorded_at,
                valid_from,
                valid_to,
                retired_at,
                superseded_by_id
            FROM atomic_memories
            WHERE retired_at IS NULL
            ORDER BY recorded_at ASC, id ASC
            """
        ).fetchall()

        return tuple(self._row_to_memory(row) for row in rows)

    def list_page(self, *, query: str = "", state: str = "active", limit: int = 25,
                  offset: int = 0) -> tuple[int, tuple[AtomicMemory, ...]]:
        """管理页的字面子串筛选；不是聊天召回，也不改变检索算法。

        限定每页大小，在 SQL 中分页，不将整个数据库或所有 L0 来源发给浏览器。
        调用方若需要总数与列表的同一快照，应在读取事务中调用。
        """
        if (state not in {"active", "retired", "all"} or len(query) > 200
                or type(limit) is not int or not 1 <= limit <= 100
                or type(offset) is not int or not 0 <= offset <= 100000):
            raise ValueError("无效的记忆分页参数")
        conditions = ["instr(lower(content), lower(?)) > 0"] if query else ["1 = 1"]
        parameters = [query] if query else []
        if state == "active":
            conditions.append("retired_at IS NULL")
        elif state == "retired":
            conditions.append("retired_at IS NOT NULL")
        # 这里只组合固定的 SQL 片段；用户搜索内容始终通过参数绑定。
        predicate = " AND ".join(conditions)
        total = self._connection.execute(
            "SELECT COUNT(*) FROM atomic_memories WHERE " + predicate, parameters
        ).fetchone()[0]
        rows = self._connection.execute(
            "SELECT * FROM atomic_memories WHERE " + predicate
            + " ORDER BY recorded_at DESC, id DESC LIMIT ? OFFSET ?",
            [*parameters, limit, offset],
        ).fetchall()
        return total, tuple(self._row_to_memory(row) for row in rows)

    def delete(self, memory_id: MemoryId) -> bool:
        """删除指定记忆，并返回是否删除成功。"""

        cursor = self._connection.execute(
            """
            DELETE FROM atomic_memories
            WHERE id = ?
            """,
            (str(memory_id),),
        )
        if self._commit_changes:
            self._connection.commit()

        return cursor.rowcount == 1

    def retire_as_superseded(
        self,
        memory_id: MemoryId,
        *,
        superseded_by_id: MemoryId,
        retired_at: datetime,
        valid_to: datetime | None = None,
    ) -> bool:
        """只取代当前有效记忆，并按需记录现实世界中的失效时间。"""

        if valid_to is None:
            # 纠错不推断现实失效时间，也不覆盖异常/历史导入已有的时间字段。
            cursor = self._connection.execute(
                """
                UPDATE atomic_memories
                SET retired_at = ?, superseded_by_id = ?
                WHERE id = ? AND retired_at IS NULL
                """,
                (retired_at.isoformat(), str(superseded_by_id), str(memory_id)),
            )
        else:
            cursor = self._connection.execute(
                """
                UPDATE atomic_memories
                SET retired_at = ?, superseded_by_id = ?, valid_to = ?
                WHERE id = ? AND retired_at IS NULL
                """,
                (
                    retired_at.isoformat(),
                    str(superseded_by_id),
                    valid_to.isoformat(),
                    str(memory_id),
                ),
            )
        if self._commit_changes:
            self._connection.commit()
        return cursor.rowcount == 1

    def _insert_evidence(self, evidence: MemoryEvidence):
        """插入来源关联；复合主键保证同一证据不会重复。"""

        return self._connection.execute(
            """
            INSERT OR IGNORE INTO memory_evidence (
                memory_id,
                source_message_id,
                source_type,
                linked_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                str(evidence.memory_id),
                str(evidence.source_message_id),
                evidence.source_type.value,
                evidence.linked_at.isoformat(),
            ),
        )

    @staticmethod
    def _row_to_memory(row: Row) -> AtomicMemory:
        """把 SQLite 查询结果恢复成领域模型。"""

        return AtomicMemory(
            id=MemoryId(row["id"]),
            subject_id=MemorySubjectId(row["subject_id"]),
            content=row["content"],
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
            valid_from=SQLiteMemoryStore._optional_text_to_datetime(
                row["valid_from"]
            ),
            valid_to=SQLiteMemoryStore._optional_text_to_datetime(
                row["valid_to"]
            ),
            retired_at=SQLiteMemoryStore._optional_text_to_datetime(
                row["retired_at"]
            ),
            superseded_by_id=(
                MemoryId(row["superseded_by_id"])
                if row["superseded_by_id"] is not None
                else None
            ),
        )

    @staticmethod
    def _optional_datetime_to_text(value: datetime | None) -> str | None:
        """把可空时间转换成 SQLite 使用的 ISO 文本。"""

        return value.isoformat() if value is not None else None

    @staticmethod
    def _optional_text_to_datetime(value: str | None) -> datetime | None:
        """把 SQLite 中的可空 ISO 文本恢复为时间对象。"""

        return datetime.fromisoformat(value) if value is not None else None
