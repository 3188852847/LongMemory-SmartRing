"""V48 -> V49：增加 1 分钟至 24 小时的自动交流间隔。"""


def migrate(connection) -> None:
    """重建主动设置表，同时把每日次数上限扩到一分钟频率所需的 1440。"""

    columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(proactive_policy_settings)"
        )
    }
    if "automatic_interval_seconds" in columns:
        return
    connection.executescript("""
        CREATE TABLE proactive_policy_settings_v49 (
            subject_id TEXT PRIMARY KEY CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
            enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
            utc_offset_minutes INTEGER NOT NULL CHECK (utc_offset_minutes BETWEEN -720 AND 840),
            allowed_weekdays_mask INTEGER NOT NULL CHECK (allowed_weekdays_mask BETWEEN 1 AND 127),
            allowed_start_minute INTEGER NOT NULL CHECK (allowed_start_minute BETWEEN 0 AND 1439),
            allowed_end_minute INTEGER NOT NULL CHECK (allowed_end_minute BETWEEN 0 AND 1439),
            daily_limit INTEGER NOT NULL CHECK (daily_limit BETWEEN 1 AND 1440),
            minimum_interval_seconds INTEGER NOT NULL CHECK (minimum_interval_seconds BETWEEN 0 AND 604800),
            maximum_lifetime_seconds INTEGER NOT NULL CHECK (maximum_lifetime_seconds BETWEEN 5 AND 1800),
            quiet_until TEXT,
            policy_version TEXT NOT NULL CHECK (length(trim(policy_version)) BETWEEN 1 AND 120),
            revision INTEGER NOT NULL CHECK (revision >= 1),
            updated_at TEXT NOT NULL,
            automatic_enabled INTEGER NOT NULL DEFAULT 0 CHECK (automatic_enabled IN (0,1)),
            scheduled_minute INTEGER NOT NULL DEFAULT 780 CHECK (scheduled_minute BETWEEN 0 AND 1439),
            greeting_text TEXT NOT NULL DEFAULT '下午好，今天过得怎么样？'
                CHECK (length(trim(greeting_text)) BETWEEN 1 AND 80),
            topic_enabled INTEGER NOT NULL DEFAULT 0 CHECK (topic_enabled IN (0,1)),
            automatic_interval_seconds INTEGER NOT NULL DEFAULT 86400
                CHECK (automatic_interval_seconds BETWEEN 60 AND 86400
                       AND automatic_interval_seconds % 60 = 0),
            CHECK (allowed_start_minute <> allowed_end_minute)
        );
        INSERT INTO proactive_policy_settings_v49 (
            subject_id,enabled,utc_offset_minutes,allowed_weekdays_mask,
            allowed_start_minute,allowed_end_minute,daily_limit,
            minimum_interval_seconds,maximum_lifetime_seconds,quiet_until,
            policy_version,revision,updated_at,automatic_enabled,scheduled_minute,
            greeting_text,topic_enabled,automatic_interval_seconds
        ) SELECT
            subject_id,enabled,utc_offset_minutes,allowed_weekdays_mask,
            allowed_start_minute,allowed_end_minute,daily_limit,
            minimum_interval_seconds,maximum_lifetime_seconds,quiet_until,
            policy_version,revision,updated_at,automatic_enabled,scheduled_minute,
            greeting_text,topic_enabled,86400
        FROM proactive_policy_settings;
        DROP TABLE proactive_policy_settings;
        ALTER TABLE proactive_policy_settings_v49 RENAME TO proactive_policy_settings;
    """)
