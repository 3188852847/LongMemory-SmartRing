"""低频整理运行账本的 SQLite 实现。"""

from datetime import datetime
from sqlite3 import Connection, IntegrityError, Row

from longmemory.core.memory.consolidation.models import (
    ConsolidationCursor,
    ConsolidationRun,
    ConsolidationRunStatus,
    ConsolidationStage,
    ConsolidationTrigger,
)


class SQLiteConsolidationRunStore:
    def __init__(self, connection: Connection, *, commit_changes: bool = True) -> None:
        self._connection = connection
        self._commit_changes = commit_changes

    def start(self, run: ConsolidationRun) -> None:
        if run.status != ConsolidationRunStatus.RUNNING:
            raise ValueError("consolidation_start_requires_running")
        try:
            self._connection.execute(
                "INSERT INTO memory_consolidation_runs "
                "(id,subject_id,stage,trigger_kind,status,started_at,source_count,"
                "model_call_count) VALUES (?,?,?,?,?,?,?,?)",
                (
                    run.id, run.subject_id, run.stage.value, run.trigger.value,
                    run.status.value, run.started_at.isoformat(), run.source_count,
                    run.model_call_count,
                ),
            )
            if self._commit_changes:
                self._connection.commit()
        except IntegrityError as error:
            self._connection.rollback()
            if "memory_consolidation_runs.subject_id" in str(error):
                raise ValueError("consolidation_already_running") from None
            raise

    def finish(self, run: ConsolidationRun) -> None:
        if run.status == ConsolidationRunStatus.RUNNING:
            raise ValueError("consolidation_finish_requires_terminal")
        cursor = run.cursor
        statement = (
            "UPDATE memory_consolidation_runs SET status=?,finished_at=?,outcome_code=?,"
            "source_count=?,model_call_count=?,cursor_recorded_at=?,cursor_source_id=? "
            "WHERE id=? AND subject_id=? AND stage=? AND trigger_kind=? AND status='running'"
        )
        values = (
            run.status.value,
            run.finished_at.isoformat(),
            run.outcome_code,
            run.source_count,
            run.model_call_count,
            cursor.recorded_at.isoformat() if cursor else None,
            cursor.source_id if cursor else None,
            run.id,
            run.subject_id,
            run.stage.value,
            run.trigger.value,
        )
        try:
            changed = self._connection.execute(statement, values).rowcount
            if changed != 1:
                raise ValueError("consolidation_run_finish_conflict")
            if self._commit_changes:
                self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def latest_cursor(
        self, subject_id: str, stage: ConsolidationStage,
    ) -> ConsolidationCursor | None:
        row = self._connection.execute(
            "SELECT cursor_recorded_at,cursor_source_id FROM memory_consolidation_runs "
            "WHERE subject_id=? AND stage=? AND status='completed' "
            "AND cursor_recorded_at IS NOT NULL "
            "ORDER BY finished_at DESC,id DESC LIMIT 1",
            (subject_id, stage.value),
        ).fetchone()
        if row is None:
            return None
        return ConsolidationCursor(
            datetime.fromisoformat(row["cursor_recorded_at"]), row["cursor_source_id"],
        )

    def has_running(self, subject_id: str, stage: ConsolidationStage) -> bool:
        return self._connection.execute(
            "SELECT EXISTS(SELECT 1 FROM memory_consolidation_runs "
            "WHERE subject_id=? AND stage=? AND status='running')",
            (subject_id, stage.value),
        ).fetchone()[0] == 1

    def model_calls_since(
        self, subject_id: str, stage: ConsolidationStage, since: datetime,
    ) -> int:
        if since.tzinfo is None or since.utcoffset() is None:
            raise ValueError("since_timezone_required")
        return self._connection.execute(
            "SELECT coalesce(sum(model_call_count),0) FROM memory_consolidation_runs "
            "WHERE subject_id=? AND stage=? AND started_at>=?",
            (subject_id, stage.value, since.isoformat()),
        ).fetchone()[0]

    def list_recent(
        self, subject_id: str, stage: ConsolidationStage, *, limit: int = 20,
    ) -> tuple[ConsolidationRun, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("consolidation_run_limit_invalid")
        rows = self._connection.execute(
            "SELECT * FROM memory_consolidation_runs WHERE subject_id=? AND stage=? "
            "ORDER BY started_at DESC,id DESC LIMIT ?",
            (subject_id, stage.value, limit),
        ).fetchall()
        return tuple(self._row_to_run(row) for row in rows)

    @staticmethod
    def _row_to_run(row: Row) -> ConsolidationRun:
        cursor = None
        if row["cursor_recorded_at"] is not None:
            cursor = ConsolidationCursor(
                datetime.fromisoformat(row["cursor_recorded_at"]),
                row["cursor_source_id"],
            )
        return ConsolidationRun(
            id=row["id"],
            subject_id=row["subject_id"],
            stage=ConsolidationStage(row["stage"]),
            trigger=ConsolidationTrigger(row["trigger_kind"]),
            status=ConsolidationRunStatus(row["status"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            source_count=row["source_count"],
            model_call_count=row["model_call_count"],
            finished_at=(
                datetime.fromisoformat(row["finished_at"])
                if row["finished_at"] else None
            ),
            outcome_code=row["outcome_code"],
            cursor=cursor,
        )
