"""当前 SQLite V29 的完整结构定义；不包含历史迁移步骤。"""

SCHEMA_VERSION = 29

LATEST_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS atomic_memories (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    content TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    retired_at TEXT,
    superseded_by_id TEXT,
    FOREIGN KEY (superseded_by_id) REFERENCES atomic_memories (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_atomic_memories_active_content
    ON atomic_memories (subject_id, content) WHERE retired_at IS NULL;
CREATE TABLE IF NOT EXISTS memory_evidence (
    memory_id TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('user_stated', 'user_corrected')),
    linked_at TEXT NOT NULL,
    PRIMARY KEY (memory_id, source_message_id, source_type),
    FOREIGN KEY (memory_id) REFERENCES atomic_memories (id) ON DELETE CASCADE,
    FOREIGN KEY (source_message_id) REFERENCES conversation_messages (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_memory_evidence_source_message
    ON memory_evidence (source_message_id);

CREATE TABLE IF NOT EXISTS l1_deletion_events (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    deleted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_l1_deletion_events_subject_time
    ON l1_deletion_events (subject_id, deleted_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS memory_quality_events (
    id TEXT PRIMARY KEY,
    event_kind TEXT NOT NULL CHECK (event_kind = 'owner_confirmed_missed_extraction'),
    source_message_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    resolution TEXT NOT NULL CHECK (resolution IN ('created', 'evidence_added')),
    occurred_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_quality_event_source_kind
    ON memory_quality_events (source_message_id, event_kind);
CREATE INDEX IF NOT EXISTS idx_memory_quality_events_time
    ON memory_quality_events (occurred_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS scenario_memories (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 120),
    summary TEXT NOT NULL CHECK (length(trim(summary)) BETWEEN 1 AND 2000),
    generated_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    status TEXT NOT NULL CHECK (status IN ('candidate', 'active', 'rejected', 'stale')),
    generator_name TEXT NOT NULL CHECK (length(trim(generator_name)) > 0),
    generator_version TEXT NOT NULL CHECK (length(trim(generator_version)) > 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1)
);

CREATE TABLE IF NOT EXISTS scenario_memory_sources (
    scenario_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    memory_content_snapshot TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    PRIMARY KEY (scenario_id, memory_id),
    FOREIGN KEY (scenario_id) REFERENCES scenario_memories (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_scenario_sources_memory
    ON scenario_memory_sources (memory_id);

CREATE TABLE IF NOT EXISTS scenario_generation_audits (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL UNIQUE,
    generator_name TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    source_memory_count INTEGER NOT NULL CHECK (source_memory_count >= 2),
    source_message_count INTEGER NOT NULL CHECK (source_message_count >= 2),
    FOREIGN KEY (scenario_id) REFERENCES scenario_memories (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scenario_reviews (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    reviewer_type TEXT NOT NULL CHECK (reviewer_type IN ('user', 'policy')),
    reviewed_at TEXT NOT NULL,
    scenario_revision INTEGER NOT NULL CHECK (scenario_revision >= 1),
    policy_version TEXT,
    decision_reason TEXT,
    CHECK (
        (reviewer_type = 'user' AND policy_version IS NULL AND decision_reason IS NULL)
        OR
        (reviewer_type = 'policy' AND decision = 'accepted'
            AND length(trim(policy_version)) BETWEEN 1 AND 120
            AND length(trim(decision_reason)) BETWEEN 1 AND 120)
    ),
    FOREIGN KEY (scenario_id) REFERENCES scenario_memories (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scenario_lifecycle_events (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('manual_end', 'source_retired', 'source_deleted')),
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'system')),
    occurred_at TEXT NOT NULL,
    previous_status TEXT NOT NULL CHECK (previous_status IN ('candidate', 'active')),
    new_status TEXT NOT NULL CHECK (new_status = 'stale'),
    scenario_revision INTEGER NOT NULL CHECK (scenario_revision >= 2),
    FOREIGN KEY (scenario_id) REFERENCES scenario_memories (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_scenario_lifecycle_scenario
    ON scenario_lifecycle_events (scenario_id, occurred_at);

CREATE TABLE IF NOT EXISTS persona_memories (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN ('preference', 'habit', 'interaction_style', 'behavior_pattern')
    ),
    basis TEXT NOT NULL CHECK (basis IN ('user_declared', 'system_inferred')),
    label TEXT NOT NULL CHECK (length(trim(label)) BETWEEN 1 AND 120),
    statement TEXT NOT NULL CHECK (length(trim(statement)) BETWEEN 1 AND 1000),
    generated_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    status TEXT NOT NULL CHECK (status IN ('candidate', 'active', 'rejected', 'stale')),
    generator_name TEXT NOT NULL CHECK (length(trim(generator_name)) > 0),
    generator_version TEXT NOT NULL CHECK (length(trim(generator_version)) > 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1)
);

CREATE TABLE IF NOT EXISTS persona_sources (
    persona_id TEXT NOT NULL,
    source_layer TEXT NOT NULL CHECK (source_layer IN ('l1', 'l2')),
    source_id TEXT NOT NULL,
    source_content_snapshot TEXT NOT NULL CHECK (length(trim(source_content_snapshot)) > 0),
    linked_at TEXT NOT NULL,
    PRIMARY KEY (persona_id, source_layer, source_id),
    FOREIGN KEY (persona_id) REFERENCES persona_memories (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_persona_sources_source
    ON persona_sources (source_layer, source_id);

CREATE TABLE IF NOT EXISTS persona_generation_audits (
    id TEXT PRIMARY KEY,
    persona_id TEXT NOT NULL UNIQUE,
    basis TEXT NOT NULL CHECK (basis IN ('user_declared', 'system_inferred')),
    generator_name TEXT NOT NULL CHECK (length(trim(generator_name)) > 0),
    generator_version TEXT NOT NULL CHECK (length(trim(generator_version)) > 0),
    generated_at TEXT NOT NULL,
    source_count INTEGER NOT NULL CHECK (source_count >= 1),
    source_message_count INTEGER NOT NULL CHECK (source_message_count >= 1),
    observation_day_count INTEGER NOT NULL CHECK (observation_day_count >= 1),
    FOREIGN KEY (persona_id) REFERENCES persona_memories (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS persona_reviews (
    id TEXT PRIMARY KEY,
    persona_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    reviewer_type TEXT NOT NULL CHECK (reviewer_type IN ('user', 'policy')),
    reviewed_at TEXT NOT NULL,
    persona_revision INTEGER NOT NULL CHECK (persona_revision >= 1),
    policy_version TEXT,
    decision_reason TEXT,
    CHECK (
        (reviewer_type = 'user' AND policy_version IS NULL AND decision_reason IS NULL)
        OR
        (reviewer_type = 'policy' AND decision = 'accepted'
            AND length(trim(policy_version)) BETWEEN 1 AND 120
            AND length(trim(decision_reason)) BETWEEN 1 AND 120)
    ),
    FOREIGN KEY (persona_id) REFERENCES persona_memories (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS persona_replacements (
    candidate_persona_id TEXT NOT NULL,
    replaced_persona_id TEXT NOT NULL,
    target_revision INTEGER NOT NULL CHECK (target_revision >= 1),
    linked_at TEXT NOT NULL,
    applied_at TEXT,
    PRIMARY KEY (candidate_persona_id, replaced_persona_id),
    CHECK (candidate_persona_id <> replaced_persona_id),
    FOREIGN KEY (candidate_persona_id) REFERENCES persona_memories (id) ON DELETE RESTRICT,
    FOREIGN KEY (replaced_persona_id) REFERENCES persona_memories (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_persona_replacements_target
    ON persona_replacements (replaced_persona_id, applied_at);

CREATE TABLE IF NOT EXISTS persona_lifecycle_events (
    id TEXT PRIMARY KEY,
    persona_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('source_retired', 'source_deleted', 'source_stale')),
    source_layer TEXT NOT NULL CHECK (source_layer IN ('l1', 'l2')),
    source_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    previous_status TEXT NOT NULL CHECK (previous_status IN ('candidate', 'active')),
    new_status TEXT NOT NULL CHECK (new_status = 'stale'),
    persona_revision INTEGER NOT NULL CHECK (persona_revision >= 2),
    FOREIGN KEY (persona_id) REFERENCES persona_memories (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_persona_lifecycle_persona
    ON persona_lifecycle_events (persona_id, occurred_at);

CREATE TABLE IF NOT EXISTS memory_consolidation_runs (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) > 0),
    stage TEXT NOT NULL CHECK (stage IN ('l1_to_l2', 'l2_to_l3')),
    trigger_kind TEXT NOT NULL CHECK (trigger_kind IN ('new_evidence', 'manual', 'rebuild')),
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'skipped', 'failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome_code TEXT,
    source_count INTEGER NOT NULL DEFAULT 0 CHECK (source_count >= 0),
    model_call_count INTEGER NOT NULL DEFAULT 0 CHECK (model_call_count >= 0),
    cursor_recorded_at TEXT,
    cursor_source_id TEXT,
    risk_reviewer_version TEXT CHECK (
        risk_reviewer_version IS NULL
        OR length(trim(risk_reviewer_version)) BETWEEN 1 AND 120
    ),
    CHECK (
        (status = 'running' AND finished_at IS NULL AND outcome_code IS NULL)
        OR
        (status <> 'running' AND finished_at IS NOT NULL
            AND length(trim(outcome_code)) > 0)
    ),
    CHECK (
        (status = 'completed' AND source_count > 0
            AND cursor_recorded_at IS NOT NULL
            AND length(trim(cursor_source_id)) > 0)
        OR
        (status <> 'completed' AND cursor_recorded_at IS NULL
            AND cursor_source_id IS NULL)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_consolidation_one_running
    ON memory_consolidation_runs (subject_id, stage) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS idx_consolidation_recent
    ON memory_consolidation_runs (subject_id, stage, started_at DESC);

CREATE TABLE IF NOT EXISTS proactive_outreach (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
    trigger_kind TEXT NOT NULL CHECK (trigger_kind IN (
        'manual_test', 'explicit_schedule', 'inactivity_rule', 'habit_candidate'
    )),
    trigger_reason_code TEXT NOT NULL CHECK (
        length(trim(trigger_reason_code)) BETWEEN 1 AND 120
    ),
    content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 1 AND 500),
    created_at TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'candidate', 'blocked', 'queued', 'transport_sent',
        'device_acknowledged', 'played', 'expired', 'cancelled', 'failed'
    )),
    state_changed_at TEXT NOT NULL,
    idempotency_key TEXT NOT NULL CHECK (
        length(trim(idempotency_key)) BETWEEN 1 AND 160
    ),
    policy_version TEXT CHECK (
        policy_version IS NULL OR length(trim(policy_version)) BETWEEN 1 AND 120
    ),
    topic_seed_id TEXT,
    topic_seed_revision INTEGER CHECK (
        topic_seed_revision IS NULL OR topic_seed_revision >= 1
    ),
    strategy_version_id TEXT,
    strategy_selection_revision INTEGER CHECK (
        strategy_selection_revision IS NULL OR strategy_selection_revision >= 1
    ),
    strategy_evaluated_local_date TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    failure_reason TEXT CHECK (
        failure_reason IS NULL OR length(trim(failure_reason)) BETWEEN 1 AND 120
    ),
    CHECK (
        (state = 'failed' AND failure_reason IS NOT NULL)
        OR (state <> 'failed' AND failure_reason IS NULL)
    ),
    UNIQUE (subject_id, idempotency_key),
    CHECK ((topic_seed_id IS NULL) = (topic_seed_revision IS NULL)),
    CHECK (
        (strategy_version_id IS NULL AND strategy_selection_revision IS NULL
            AND strategy_evaluated_local_date IS NULL)
        OR
        (trigger_kind = 'habit_candidate' AND strategy_version_id IS NOT NULL
            AND strategy_selection_revision IS NOT NULL
            AND length(strategy_evaluated_local_date) = 10)
    ),
    FOREIGN KEY (topic_seed_id) REFERENCES proactive_topic_seeds (id) ON DELETE RESTRICT,
    FOREIGN KEY (strategy_version_id)
        REFERENCES companion_absence_strategy_versions (id)
);
CREATE INDEX IF NOT EXISTS idx_proactive_outreach_recent
    ON proactive_outreach (subject_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_proactive_outreach_due
    ON proactive_outreach (state, scheduled_for, expires_at);

CREATE TABLE IF NOT EXISTS proactive_outreach_events (
    id TEXT PRIMARY KEY,
    outreach_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    previous_state TEXT CHECK (previous_state IS NULL OR previous_state IN (
        'candidate', 'blocked', 'queued', 'transport_sent',
        'device_acknowledged', 'played', 'expired', 'cancelled', 'failed'
    )),
    new_state TEXT NOT NULL CHECK (new_state IN (
        'candidate', 'blocked', 'queued', 'transport_sent',
        'device_acknowledged', 'played', 'expired', 'cancelled', 'failed'
    )),
    reason_code TEXT NOT NULL CHECK (length(trim(reason_code)) BETWEEN 1 AND 120),
    evidence_kind TEXT NOT NULL CHECK (evidence_kind IN (
        'system_created', 'policy_decision', 'server_queue', 'transport_write',
        'device_ack', 'user_observed', 'system_recovery'
    )),
    occurred_at TEXT NOT NULL,
    UNIQUE (outreach_id, sequence),
    FOREIGN KEY (outreach_id) REFERENCES proactive_outreach (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_proactive_events_outreach
    ON proactive_outreach_events (outreach_id, sequence);

CREATE TABLE IF NOT EXISTS companion_interaction_events (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
    event_kind TEXT NOT NULL CHECK (
        event_kind = 'subsequent_user_message_observed'
    ),
    outreach_id TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    latency_seconds INTEGER NOT NULL CHECK (latency_seconds >= 0),
    evidence_kind TEXT NOT NULL CHECK (evidence_kind = 'temporal_order'),
    recorder_version TEXT NOT NULL CHECK (
        length(trim(recorder_version)) BETWEEN 1 AND 120
    ),
    UNIQUE (outreach_id, event_kind),
    FOREIGN KEY (outreach_id) REFERENCES proactive_outreach (id) ON DELETE RESTRICT,
    FOREIGN KEY (source_message_id) REFERENCES conversation_messages (id)
        ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_companion_interaction_subject_recent
    ON companion_interaction_events (subject_id, occurred_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_companion_interaction_source_message
    ON companion_interaction_events (source_message_id);

CREATE TABLE IF NOT EXISTS companion_feedback_events (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
    outreach_id TEXT NOT NULL,
    topic_seed_id TEXT NOT NULL,
    source_message_id TEXT NOT NULL UNIQUE,
    occurred_at TEXT NOT NULL,
    feedback_kind TEXT NOT NULL CHECK (feedback_kind = 'reject_topic'),
    action_kind TEXT NOT NULL CHECK (action_kind = 'topic_seed_disabled'),
    evidence_kind TEXT NOT NULL CHECK (evidence_kind = 'user_explicit'),
    interpreter_version TEXT NOT NULL CHECK (
        length(trim(interpreter_version)) BETWEEN 1 AND 120
    ),
    FOREIGN KEY (outreach_id) REFERENCES proactive_outreach (id) ON DELETE RESTRICT,
    FOREIGN KEY (topic_seed_id) REFERENCES proactive_topic_seeds (id) ON DELETE RESTRICT,
    FOREIGN KEY (source_message_id) REFERENCES conversation_messages (id)
        ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_companion_feedback_subject_recent
    ON companion_feedback_events (subject_id, occurred_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS companion_user_initiated_interactions (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
    source_message_id TEXT NOT NULL UNIQUE,
    occurred_at TEXT NOT NULL,
    previous_user_message_at TEXT,
    silence_gap_seconds INTEGER CHECK (
        silence_gap_seconds IS NULL OR silence_gap_seconds >= 14400
    ),
    evidence_kind TEXT NOT NULL CHECK (
        evidence_kind = 'silence_gap_without_recent_outreach'
    ),
    detector_version TEXT NOT NULL CHECK (
        length(trim(detector_version)) BETWEEN 1 AND 120
    ),
    CHECK (
        (previous_user_message_at IS NULL AND silence_gap_seconds IS NULL)
        OR (previous_user_message_at IS NOT NULL AND silence_gap_seconds IS NOT NULL)
    ),
    FOREIGN KEY (source_message_id) REFERENCES conversation_messages (id)
        ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_companion_user_initiated_subject_recent
    ON companion_user_initiated_interactions (subject_id, occurred_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS companion_routine_candidates (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
    status TEXT NOT NULL CHECK (status IN ('candidate', 'dismissed')),
    expected_minute INTEGER NOT NULL CHECK (expected_minute BETWEEN 0 AND 1439),
    utc_offset_minutes INTEGER NOT NULL CHECK (utc_offset_minutes BETWEEN -720 AND 840),
    observation_window_minutes INTEGER NOT NULL CHECK (observation_window_minutes = 30),
    evidence_count INTEGER NOT NULL CHECK (evidence_count >= 3),
    distinct_local_dates INTEGER NOT NULL CHECK (distinct_local_dates >= 3),
    evidence_fingerprint TEXT NOT NULL CHECK (length(evidence_fingerprint) = 64),
    rationale_code TEXT NOT NULL CHECK (
        rationale_code = 'repeated_user_initiated_activity_near_time'
    ),
    generator_version TEXT NOT NULL CHECK (length(trim(generator_version)) BETWEEN 1 AND 120),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    UNIQUE (subject_id, evidence_fingerprint)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_companion_routine_one_candidate
    ON companion_routine_candidates (subject_id) WHERE status='candidate';
CREATE INDEX IF NOT EXISTS idx_companion_routine_subject_recent
    ON companion_routine_candidates (subject_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS companion_routine_candidate_sources (
    candidate_id TEXT NOT NULL,
    user_initiated_event_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    silence_gap_seconds INTEGER,
    evidence_kind TEXT NOT NULL CHECK (
        evidence_kind = 'silence_gap_without_recent_outreach'
    ),
    PRIMARY KEY (candidate_id, user_initiated_event_id),
    FOREIGN KEY (candidate_id) REFERENCES companion_routine_candidates (id)
        ON DELETE CASCADE,
    FOREIGN KEY (user_initiated_event_id)
        REFERENCES companion_user_initiated_interactions (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_companion_routine_source_event
    ON companion_routine_candidate_sources (user_initiated_event_id);

CREATE TABLE IF NOT EXISTS companion_absence_strategy_versions (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
    source_candidate_id TEXT NOT NULL,
    source_candidate_revision INTEGER NOT NULL CHECK (source_candidate_revision >= 1),
    expected_minute INTEGER NOT NULL CHECK (expected_minute BETWEEN 0 AND 1439),
    grace_minutes INTEGER NOT NULL CHECK (grace_minutes BETWEEN 15 AND 360),
    utc_offset_minutes INTEGER NOT NULL CHECK (utc_offset_minutes BETWEEN -720 AND 840),
    allowed_weekdays_mask INTEGER NOT NULL CHECK (allowed_weekdays_mask BETWEEN 1 AND 127),
    trigger_policy_version TEXT NOT NULL CHECK (length(trim(trigger_policy_version)) BETWEEN 1 AND 120),
    replay_protocol TEXT NOT NULL CHECK (length(trim(replay_protocol)) BETWEEN 1 AND 120),
    replay_dataset_name TEXT NOT NULL CHECK (length(trim(replay_dataset_name)) BETWEEN 1 AND 120),
    replay_dataset_version TEXT NOT NULL CHECK (length(trim(replay_dataset_version)) BETWEEN 1 AND 120),
    replay_dataset_sha256 TEXT NOT NULL CHECK (length(replay_dataset_sha256) = 64),
    parameter_fingerprint TEXT NOT NULL CHECK (length(parameter_fingerprint) = 64),
    replay_case_count INTEGER NOT NULL CHECK (replay_case_count > 0),
    replay_matched_count INTEGER NOT NULL CHECK (replay_matched_count BETWEEN 0 AND replay_case_count),
    replay_unsafe_allow_count INTEGER NOT NULL CHECK (replay_unsafe_allow_count >= 0),
    replay_gate_passed INTEGER NOT NULL CHECK (replay_gate_passed IN (0,1)),
    replayed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (expected_minute + grace_minutes < 1440),
    CHECK (replay_gate_passed = (replay_matched_count = replay_case_count AND replay_unsafe_allow_count = 0)),
    UNIQUE (subject_id, parameter_fingerprint),
    FOREIGN KEY (source_candidate_id) REFERENCES companion_routine_candidates (id)
        ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_companion_absence_versions_subject
    ON companion_absence_strategy_versions (subject_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS companion_absence_strategy_selections (
    subject_id TEXT PRIMARY KEY,
    current_version_id TEXT,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    updated_at TEXT NOT NULL,
    FOREIGN KEY (current_version_id) REFERENCES companion_absence_strategy_versions (id)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS companion_absence_strategy_switch_events (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    previous_version_id TEXT,
    selected_version_id TEXT,
    action TEXT NOT NULL CHECK (action IN ('activate','deactivate','rollback')),
    pointer_revision INTEGER NOT NULL CHECK (pointer_revision >= 1),
    created_at TEXT NOT NULL,
    CHECK ((action = 'deactivate' AND selected_version_id IS NULL)
        OR (action IN ('activate','rollback') AND selected_version_id IS NOT NULL)),
    UNIQUE (subject_id, pointer_revision),
    FOREIGN KEY (previous_version_id) REFERENCES companion_absence_strategy_versions (id)
        ON DELETE RESTRICT,
    FOREIGN KEY (selected_version_id) REFERENCES companion_absence_strategy_versions (id)
        ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_companion_absence_switch_subject
    ON companion_absence_strategy_switch_events (subject_id, pointer_revision DESC);

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

CREATE TABLE IF NOT EXISTS proactive_policy_settings (
    subject_id TEXT PRIMARY KEY CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
    enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
    utc_offset_minutes INTEGER NOT NULL CHECK (utc_offset_minutes BETWEEN -720 AND 840),
    allowed_weekdays_mask INTEGER NOT NULL CHECK (allowed_weekdays_mask BETWEEN 1 AND 127),
    allowed_start_minute INTEGER NOT NULL CHECK (allowed_start_minute BETWEEN 0 AND 1439),
    allowed_end_minute INTEGER NOT NULL CHECK (allowed_end_minute BETWEEN 0 AND 1439),
    daily_limit INTEGER NOT NULL CHECK (daily_limit BETWEEN 1 AND 20),
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
    CHECK (allowed_start_minute <> allowed_end_minute)
);

CREATE TABLE IF NOT EXISTS proactive_topic_seeds (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
    scenario_id TEXT NOT NULL,
    prompt_text TEXT NOT NULL CHECK (length(trim(prompt_text)) BETWEEN 1 AND 120),
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    FOREIGN KEY (scenario_id) REFERENCES scenario_memories (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_proactive_topic_seeds_subject
    ON proactive_topic_seeds (subject_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS proactive_schedule_overrides (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
    local_date TEXT NOT NULL CHECK (length(local_date) = 10),
    scheduled_minute INTEGER NOT NULL CHECK (scheduled_minute BETWEEN 0 AND 1439),
    policy_revision INTEGER NOT NULL CHECK (policy_revision >= 1),
    status TEXT NOT NULL CHECK (status IN ('armed', 'consumed', 'cancelled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    consumption_reason TEXT CHECK (
        consumption_reason IS NULL OR length(trim(consumption_reason)) BETWEEN 1 AND 120
    ),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    CHECK (
        (status = 'armed' AND consumption_reason IS NULL)
        OR (status <> 'armed' AND consumption_reason IS NOT NULL)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_proactive_schedule_override_one_armed
    ON proactive_schedule_overrides (subject_id) WHERE status='armed';
CREATE INDEX IF NOT EXISTS idx_proactive_schedule_override_recent
    ON proactive_schedule_overrides (subject_id, created_at DESC, id DESC);

CREATE TRIGGER IF NOT EXISTS trg_audit_l1_delete
BEFORE DELETE ON atomic_memories
BEGIN
    INSERT INTO l1_deletion_events (id, memory_id, subject_id, deleted_at)
    VALUES (
        lower(hex(randomblob(16))), OLD.id, OLD.subject_id,
        strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_scenario_stale_on_l1_retire
AFTER UPDATE OF retired_at ON atomic_memories
WHEN OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL
BEGIN
    INSERT INTO scenario_lifecycle_events
        (id, scenario_id, action, actor_type, occurred_at,
         previous_status, new_status, scenario_revision)
    SELECT lower(hex(randomblob(16))), id, 'source_retired', 'system',
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), status, 'stale', revision + 1
    FROM scenario_memories
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT scenario_id FROM scenario_memory_sources WHERE memory_id = NEW.id);
    UPDATE scenario_memories
    SET status = 'stale', revision = revision + 1
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT scenario_id FROM scenario_memory_sources WHERE memory_id = NEW.id);
END;

CREATE TRIGGER IF NOT EXISTS trg_scenario_stale_on_l1_delete
BEFORE DELETE ON atomic_memories
BEGIN
    INSERT INTO scenario_lifecycle_events
        (id, scenario_id, action, actor_type, occurred_at,
         previous_status, new_status, scenario_revision)
    SELECT lower(hex(randomblob(16))), id, 'source_deleted', 'system',
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), status, 'stale', revision + 1
    FROM scenario_memories
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT scenario_id FROM scenario_memory_sources WHERE memory_id = OLD.id);
    UPDATE scenario_memories
    SET status = 'stale', revision = revision + 1
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT scenario_id FROM scenario_memory_sources WHERE memory_id = OLD.id);
END;

CREATE TRIGGER IF NOT EXISTS trg_persona_stale_on_l1_retire
AFTER UPDATE OF retired_at ON atomic_memories
WHEN OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL
BEGIN
    INSERT INTO persona_lifecycle_events
        (id, persona_id, action, source_layer, source_id, occurred_at,
         previous_status, new_status, persona_revision)
    SELECT lower(hex(randomblob(16))), id, 'source_retired', 'l1', NEW.id,
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), status, 'stale', revision + 1
    FROM persona_memories
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT persona_id FROM persona_sources
                 WHERE source_layer='l1' AND source_id=NEW.id);
    UPDATE persona_memories SET status='stale', revision=revision+1
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT persona_id FROM persona_sources
                 WHERE source_layer='l1' AND source_id=NEW.id);
END;

CREATE TRIGGER IF NOT EXISTS trg_persona_stale_on_l1_delete
BEFORE DELETE ON atomic_memories
BEGIN
    INSERT INTO persona_lifecycle_events
        (id, persona_id, action, source_layer, source_id, occurred_at,
         previous_status, new_status, persona_revision)
    SELECT lower(hex(randomblob(16))), id, 'source_deleted', 'l1', OLD.id,
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), status, 'stale', revision + 1
    FROM persona_memories
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT persona_id FROM persona_sources
                 WHERE source_layer='l1' AND source_id=OLD.id);
    UPDATE persona_memories SET status='stale', revision=revision+1
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT persona_id FROM persona_sources
                 WHERE source_layer='l1' AND source_id=OLD.id);
END;

CREATE TRIGGER IF NOT EXISTS trg_persona_stale_on_l2_stale
AFTER UPDATE OF status ON scenario_memories
WHEN OLD.status IN ('candidate', 'active') AND NEW.status='stale'
BEGIN
    INSERT INTO persona_lifecycle_events
        (id, persona_id, action, source_layer, source_id, occurred_at,
         previous_status, new_status, persona_revision)
    SELECT lower(hex(randomblob(16))), id, 'source_stale', 'l2', NEW.id,
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), status, 'stale', revision + 1
    FROM persona_memories
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT persona_id FROM persona_sources
                 WHERE source_layer='l2' AND source_id=NEW.id);
    UPDATE persona_memories SET status='stale', revision=revision+1
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT persona_id FROM persona_sources
                 WHERE source_layer='l2' AND source_id=NEW.id);
END;
"""
