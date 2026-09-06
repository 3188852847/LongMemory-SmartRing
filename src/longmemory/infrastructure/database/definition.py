"""当前 SQLite V11 的完整结构定义；不包含历史迁移步骤。"""

SCHEMA_VERSION = 11

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
    reviewer_type TEXT NOT NULL CHECK (reviewer_type IN ('user')),
    reviewed_at TEXT NOT NULL,
    scenario_revision INTEGER NOT NULL CHECK (scenario_revision >= 1),
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
