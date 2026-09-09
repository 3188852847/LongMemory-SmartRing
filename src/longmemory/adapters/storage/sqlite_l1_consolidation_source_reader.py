"""从 SQLite 稳定选择 L1→L2 的新证据和旧未归组上下文。"""

from datetime import datetime
from sqlite3 import Connection, Row

from longmemory.core.common.identifiers import MemoryId, MemorySubjectId
from longmemory.core.memory.consolidation.models import ConsolidationCursor
from longmemory.core.memory.consolidation.sources import (
    L1ConsolidationBatch,
    L1ConsolidationSource,
)


_ELIGIBLE = (
    "a.subject_id=? AND a.retired_at IS NULL "
    # 第一版不把有明确结束时间的临时 L1 提炼成长期场景；否则 L1 到期后，
    # 派生 L2 仍可能继续影响回答。未来若要总结短期状态，应设计传播期限。
    "AND a.valid_to IS NULL "
    "AND EXISTS (SELECT 1 FROM memory_evidence e "
    "JOIN conversation_messages m ON m.id=e.source_message_id "
    "WHERE e.memory_id=a.id AND m.role='user') "
    "AND NOT EXISTS (SELECT 1 FROM scenario_memory_sources s "
    "JOIN scenario_memories l2 ON l2.id=s.scenario_id "
    "WHERE s.memory_id=a.id AND l2.status IN ('candidate','active'))"
)


class SQLiteL1ConsolidationSourceReader:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def read_batch(
        self,
        subject_id: str,
        *,
        after: ConsolidationCursor | None,
        limit: int,
    ) -> L1ConsolidationBatch:
        """先取游标后的最老新来源，再用最近的旧未归组来源补足容量。"""

        if not subject_id.strip() or not 2 <= limit <= 100:
            raise ValueError("consolidation_source_query_invalid")
        cursor_clause, cursor_values = self._after_clause(after)
        pending = self._connection.execute(
            "SELECT count(*) FROM atomic_memories a WHERE " + _ELIGIBLE + cursor_clause,
            (subject_id, *cursor_values),
        ).fetchone()[0]
        if pending == 0:
            return L1ConsolidationBatch((), 0, 0, None)

        new_rows = self._connection.execute(
            "SELECT a.id,a.subject_id,a.content,a.recorded_at FROM atomic_memories a "
            "WHERE " + _ELIGIBLE + cursor_clause
            + " ORDER BY a.recorded_at,a.id LIMIT ?",
            (subject_id, *cursor_values, limit),
        ).fetchall()
        selected_ids = tuple(row["id"] for row in new_rows)
        remaining = limit - len(new_rows)
        context_rows = []
        if remaining and after is not None:
            placeholders = ",".join("?" for _ in selected_ids)
            exclusion = f" AND a.id NOT IN ({placeholders})" if selected_ids else ""
            context_rows = self._connection.execute(
                "SELECT a.id,a.subject_id,a.content,a.recorded_at FROM atomic_memories a "
                "WHERE " + _ELIGIBLE
                + " AND (a.recorded_at<? OR (a.recorded_at=? AND a.id<=?))"
                + exclusion
                + " ORDER BY a.recorded_at DESC,a.id DESC LIMIT ?",
                (
                    subject_id,
                    after.recorded_at.isoformat(), after.recorded_at.isoformat(),
                    after.source_id,
                    *selected_ids,
                    remaining,
                ),
            ).fetchall()

        sources = tuple(self._source(row) for row in (*new_rows, *context_rows))
        last_new = new_rows[-1]
        return L1ConsolidationBatch(
            sources=sources,
            pending_new_source_count=pending,
            selected_new_source_count=len(new_rows),
            next_cursor=ConsolidationCursor(
                datetime.fromisoformat(last_new["recorded_at"]), last_new["id"],
            ),
        )

    @staticmethod
    def _after_clause(after: ConsolidationCursor | None) -> tuple[str, tuple[str, ...]]:
        if after is None:
            return "", ()
        value = after.recorded_at.isoformat()
        return (
            " AND (a.recorded_at>? OR (a.recorded_at=? AND a.id>?))",
            (value, value, after.source_id),
        )

    def _source(self, row: Row) -> L1ConsolidationSource:
        messages = self._connection.execute(
            "SELECT DISTINCT m.id FROM memory_evidence e "
            "JOIN conversation_messages m ON m.id=e.source_message_id "
            "WHERE e.memory_id=? AND m.role='user' ORDER BY m.created_at,m.id",
            (row["id"],),
        ).fetchall()
        return L1ConsolidationSource(
            MemoryId(row["id"]), MemorySubjectId(row["subject_id"]), row["content"],
            datetime.fromisoformat(row["recorded_at"]),
            tuple(message["id"] for message in messages),
        )
