"""主动联系设置的 SQLite 存储；缺省行表示安全默认关闭。"""

from datetime import datetime, timedelta
from sqlite3 import Connection

from longmemory.core.proactive import OutreachPolicyConfig, ProactivePolicySettings


class SQLiteProactivePolicyStore:
    def __init__(self, connection: Connection, *, commit_changes: bool = True) -> None:
        self._connection = connection
        self._commit_changes = commit_changes

    def get(self, subject_id: str) -> ProactivePolicySettings:
        row = self._connection.execute(
            "SELECT * FROM proactive_policy_settings WHERE subject_id=?", (subject_id,),
        ).fetchone()
        if row is None:
            return ProactivePolicySettings(subject_id, OutreachPolicyConfig())
        weekdays = tuple(day for day in range(7) if row["allowed_weekdays_mask"] & (1 << day))
        return ProactivePolicySettings(
            subject_id,
            OutreachPolicyConfig(
                enabled=bool(row["enabled"]),
                utc_offset_minutes=row["utc_offset_minutes"],
                allowed_weekdays=weekdays,
                allowed_start_minute=row["allowed_start_minute"],
                allowed_end_minute=row["allowed_end_minute"],
                daily_limit=row["daily_limit"],
                minimum_interval=timedelta(seconds=row["minimum_interval_seconds"]),
                maximum_lifetime=timedelta(seconds=row["maximum_lifetime_seconds"]),
                policy_version=row["policy_version"],
            ),
            datetime.fromisoformat(row["quiet_until"]) if row["quiet_until"] else None,
            row["revision"],
            datetime.fromisoformat(row["updated_at"]),
            bool(row["automatic_enabled"]),
            row["scheduled_minute"],
            row["greeting_text"],
            bool(row["topic_enabled"]),
            row["automatic_interval_seconds"],
        )

    def save(
        self, settings: ProactivePolicySettings, *, expected_revision: int,
    ) -> ProactivePolicySettings:
        if settings.revision != expected_revision + 1 or settings.updated_at is None:
            raise ValueError("proactive_settings_save_contract_invalid")
        config = settings.config
        values = (
            int(config.enabled), config.utc_offset_minutes,
            sum(1 << day for day in config.allowed_weekdays),
            config.allowed_start_minute, config.allowed_end_minute, config.daily_limit,
            int(config.minimum_interval.total_seconds()),
            int(config.maximum_lifetime.total_seconds()),
            settings.quiet_until.isoformat() if settings.quiet_until else None,
            config.policy_version, settings.revision, settings.updated_at.isoformat(),
            int(settings.automatic_enabled), settings.scheduled_minute,
            settings.greeting_text, int(settings.topic_enabled),
            settings.automatic_interval_seconds,
        )
        try:
            if expected_revision == 0:
                changed = self._connection.execute(
                    "INSERT OR IGNORE INTO proactive_policy_settings "
                    "(subject_id,enabled,utc_offset_minutes,allowed_weekdays_mask,"
                    "allowed_start_minute,allowed_end_minute,daily_limit,"
                    "minimum_interval_seconds,maximum_lifetime_seconds,quiet_until,"
                    "policy_version,revision,updated_at,automatic_enabled,scheduled_minute,"
                    "greeting_text,topic_enabled,automatic_interval_seconds) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (settings.subject_id, *values),
                ).rowcount
            else:
                changed = self._connection.execute(
                    "UPDATE proactive_policy_settings SET enabled=?,utc_offset_minutes=?,"
                    "allowed_weekdays_mask=?,allowed_start_minute=?,allowed_end_minute=?,"
                    "daily_limit=?,minimum_interval_seconds=?,maximum_lifetime_seconds=?,"
                    "quiet_until=?,policy_version=?,revision=?,updated_at=?,"
                    "automatic_enabled=?,scheduled_minute=?,greeting_text=?,topic_enabled=?,"
                    "automatic_interval_seconds=? "
                    "WHERE subject_id=? AND revision=?",
                    (*values, settings.subject_id, expected_revision),
                ).rowcount
            if changed != 1:
                raise ValueError("proactive_settings_conflict")
            if self._commit_changes:
                self._connection.commit()
            return settings
        except BaseException:
            if self._commit_changes:
                self._connection.rollback()
            raise
