"""V21→V22：新增默认不生效的跨日陪伴策略候选及来源。"""

from sqlite3 import Connection


def migrate(connection: Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS companion_strategy_candidates (
            id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
            status TEXT NOT NULL CHECK (status IN ('candidate', 'dismissed')),
            suggested_minute INTEGER NOT NULL CHECK (suggested_minute BETWEEN 0 AND 1439),
            utc_offset_minutes INTEGER NOT NULL CHECK (utc_offset_minutes BETWEEN -720 AND 840),
            evidence_count INTEGER NOT NULL CHECK (evidence_count >= 3),
            distinct_local_dates INTEGER NOT NULL CHECK (distinct_local_dates >= 3),
            evidence_fingerprint TEXT NOT NULL CHECK (length(evidence_fingerprint) = 64),
            rationale_code TEXT NOT NULL CHECK (length(trim(rationale_code)) BETWEEN 1 AND 120),
            generator_version TEXT NOT NULL CHECK (length(trim(generator_version)) BETWEEN 1 AND 120),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            UNIQUE (subject_id, evidence_fingerprint)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_companion_strategy_one_candidate
            ON companion_strategy_candidates (subject_id) WHERE status='candidate';
        CREATE INDEX IF NOT EXISTS idx_companion_strategy_subject_recent
            ON companion_strategy_candidates (subject_id, created_at DESC, id DESC);

        CREATE TABLE IF NOT EXISTS companion_strategy_candidate_sources (
            candidate_id TEXT NOT NULL,
            interaction_event_id TEXT NOT NULL,
            outreach_id TEXT NOT NULL,
            queued_at TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            latency_seconds INTEGER NOT NULL CHECK (latency_seconds BETWEEN 0 AND 1800),
            delivery_evidence_level TEXT NOT NULL CHECK (delivery_evidence_level IN (
                'server_queued', 'transport_sent', 'device_acknowledged', 'played'
            )),
            PRIMARY KEY (candidate_id, interaction_event_id),
            FOREIGN KEY (candidate_id) REFERENCES companion_strategy_candidates (id)
                ON DELETE CASCADE,
            FOREIGN KEY (interaction_event_id) REFERENCES companion_interaction_events (id)
                ON DELETE RESTRICT,
            FOREIGN KEY (outreach_id) REFERENCES proactive_outreach (id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_companion_strategy_source_interaction
            ON companion_strategy_candidate_sources (interaction_event_id);
    """)
