"""一次性开发定时验证授权的 SQLite 存储。"""

from datetime import datetime
from sqlite3 import Connection, IntegrityError


class SQLiteProactiveScheduleOverrideStore:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get_armed(self, subject_id: str) -> dict | None:
        row = self._connection.execute(
            "SELECT * FROM proactive_schedule_overrides "
            "WHERE subject_id=? AND status='armed' ORDER BY created_at DESC,id DESC LIMIT 1",
            (subject_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_latest(self, subject_id: str) -> dict | None:
        row = self._connection.execute(
            "SELECT * FROM proactive_schedule_overrides WHERE subject_id=? "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (subject_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def arm(
        self, *, override_id: str, subject_id: str, local_date: str,
        scheduled_minute: int, policy_revision: int, now: datetime,
    ) -> dict:
        try:
            self._connection.execute(
                "INSERT INTO proactive_schedule_overrides "
                "(id,subject_id,local_date,scheduled_minute,policy_revision,status,"
                "created_at,updated_at,consumption_reason,revision) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (override_id, subject_id, local_date, scheduled_minute,
                 policy_revision, "armed",
                 now.isoformat(), now.isoformat(), None, 1),
            )
            self._connection.commit()
        except IntegrityError:
            self._connection.rollback()
            raise ValueError("proactive_schedule_override_already_armed") from None
        return self.get_armed(subject_id)

    def finish(
        self, override_id: str, *, subject_id: str, expected_revision: int,
        status: str, reason: str, now: datetime,
    ) -> dict:
        if status not in {"consumed", "cancelled"}:
            raise ValueError("proactive_schedule_override_status_invalid")
        changed = self._connection.execute(
            "UPDATE proactive_schedule_overrides SET status=?,consumption_reason=?,"
            "updated_at=?,revision=revision+1 WHERE id=? AND subject_id=? "
            "AND status='armed' AND revision=?",
            (status, reason, now.isoformat(), override_id, subject_id, expected_revision),
        ).rowcount
        if changed != 1:
            self._connection.rollback()
            raise ValueError("proactive_schedule_override_conflict")
        self._connection.commit()
        row = self._connection.execute(
            "SELECT * FROM proactive_schedule_overrides WHERE id=?", (override_id,),
        ).fetchone()
        return dict(row)
