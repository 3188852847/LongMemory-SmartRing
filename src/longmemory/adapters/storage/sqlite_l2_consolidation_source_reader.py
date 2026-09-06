"""选择当前有效 L2，并解析其用户 L0 观察日供 L3 门控。"""

from datetime import UTC, datetime
from sqlite3 import Connection, Row

from longmemory.core.common.identifiers import MemorySubjectId, ScenarioId
from longmemory.core.memory.consolidation.models import ConsolidationCursor
from longmemory.core.memory.consolidation.sources import (
    L2ConsolidationBatch,
    L2ConsolidationEvidence,
    L2ConsolidationSource,
)


_ELIGIBLE = (
    "subject_id=? AND status='active' "
    "AND (valid_from IS NULL OR valid_from<=?) "
    "AND (valid_to IS NULL OR valid_to>=?)"
)


class SQLiteL2ConsolidationSourceReader:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def read_batch(
        self,
        subject_id: str,
        *,
        after: ConsolidationCursor | None,
        limit: int,
        now: datetime,
    ) -> L2ConsolidationBatch:
        if (
            not subject_id.strip()
            or not 2 <= limit <= 100
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            raise ValueError("consolidation_l2_source_query_invalid")
        current = now.isoformat()
        cursor_clause, cursor_values = self._after_clause(after)
        base_values = (subject_id, current, current)
        pending = self._connection.execute(
            "SELECT count(*) FROM scenario_memories WHERE " + _ELIGIBLE + cursor_clause,
            (*base_values, *cursor_values),
        ).fetchone()[0]
        if pending == 0:
            return L2ConsolidationBatch((), 0, 0, None)

        new_rows = self._connection.execute(
            "SELECT id,subject_id,title,summary,generated_at FROM scenario_memories "
            "WHERE " + _ELIGIBLE + cursor_clause
            + " ORDER BY generated_at,id LIMIT ?",
            (*base_values, *cursor_values, limit),
        ).fetchall()
        remaining = limit - len(new_rows)
        context_rows = []
        if remaining and after is not None:
            selected_ids = tuple(row["id"] for row in new_rows)
            placeholders = ",".join("?" for _ in selected_ids)
            exclusion = f" AND id NOT IN ({placeholders})" if selected_ids else ""
            context_rows = self._connection.execute(
                "SELECT id,subject_id,title,summary,generated_at FROM scenario_memories "
                "WHERE " + _ELIGIBLE
                + " AND (generated_at<? OR (generated_at=? AND id<=?))"
                + exclusion + " ORDER BY generated_at DESC,id DESC LIMIT ?",
                (
                    *base_values,
                    after.recorded_at.isoformat(), after.recorded_at.isoformat(),
                    after.source_id, *selected_ids, remaining,
                ),
            ).fetchall()
        sources = tuple(self._source(row) for row in (*new_rows, *context_rows))
        last_new = new_rows[-1]
        return L2ConsolidationBatch(
            sources, pending, len(new_rows),
            ConsolidationCursor(
                datetime.fromisoformat(last_new["generated_at"]), last_new["id"],
            ),
        )

    @staticmethod
    def _after_clause(after):
        if after is None:
            return "", ()
        value = after.recorded_at.isoformat()
        return " AND (generated_at>? OR (generated_at=? AND id>?))", (
            value, value, after.source_id,
        )

    def _source(self, row: Row) -> L2ConsolidationSource:
        messages = self._connection.execute(
            "SELECT DISTINCT m.id,m.content,m.created_at FROM scenario_memory_sources s "
            "JOIN memory_evidence e ON e.memory_id=s.memory_id "
            "JOIN conversation_messages m ON m.id=e.source_message_id "
            "WHERE s.scenario_id=? AND m.role='user' ORDER BY m.created_at,m.id",
            (row["id"],),
        ).fetchall()
        return L2ConsolidationSource(
            ScenarioId(row["id"]), MemorySubjectId(row["subject_id"]),
            f'{row["title"]}：{row["summary"]}',
            datetime.fromisoformat(row["generated_at"]),
            tuple(L2ConsolidationEvidence(
                item["id"], item["content"],
                datetime.fromisoformat(item["created_at"]).astimezone(UTC).date().isoformat(),
            ) for item in messages),
        )
