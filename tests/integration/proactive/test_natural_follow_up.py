from datetime import UTC, datetime

from longmemory.bootstrap import build_memory_runtime
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)


def prepare(path):
    connection = open_database(path)
    initialize_schema(connection)
    connection.close()


def test_explicit_conversation_request_creates_unarmed_traceable_candidate(tmp_path):
    path = tmp_path / "natural-follow-up.db"
    prepare(path)
    runtime = build_memory_runtime(path, clock=lambda: NOW)

    prepared = runtime.prepare_user(
        "我明天下午三点要提交毕业设计汇报，到时候问我汇报进展"
    )
    runtime.close()

    suggestion = prepared.follow_up_suggestion
    assert suggestion is not None
    assert suggestion.status == "candidate_created"
    assert suggestion.prompt_text == "汇报进展？"
    connection = open_database(path)
    row = connection.execute(
        "SELECT * FROM companion_follow_up_candidates"
    ).fetchone()
    assert row["creation_kind"] == "explicit_conversation_request"
    assert row["source_message_id"] == prepared.event.event_id
    assert row["source_memory_id"] == suggestion.source_memory_id
    assert connection.execute(
        "SELECT count(*) FROM proactive_outreach"
    ).fetchone()[0] == 0
    connection.close()


def test_vague_plan_keeps_memory_but_does_not_create_candidate(tmp_path):
    path = tmp_path / "vague-follow-up.db"
    prepare(path)
    runtime = build_memory_runtime(path, clock=lambda: NOW)

    prepared = runtime.prepare_user("我以后打算认真准备毕业设计")
    runtime.close()

    assert prepared.observation.writes
    assert prepared.follow_up_suggestion is None
    connection = open_database(path)
    assert connection.execute(
        "SELECT count(*) FROM companion_follow_up_candidates"
    ).fetchone()[0] == 0
    connection.close()
