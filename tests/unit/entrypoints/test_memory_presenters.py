from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from longmemory.entrypoints.api.memory_presenters import (
    details_json,
    memory_json,
    persona_replacement_json,
    revision,
)


NOW = datetime.now(UTC)


def memory(**changes):
    values = {
        "id": "memory-1", "subject_id": "user:self", "content": "用户喜欢喝茶。",
        "recorded_at": NOW, "valid_from": None, "valid_to": None,
        "retired_at": None, "superseded_by_id": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_memory_projection_keeps_effective_state_separate_from_storage_state():
    future = memory(valid_from=NOW + timedelta(days=1))
    retired = memory(retired_at=NOW, superseded_by_id="memory-2")
    assert memory_json(future)["effective_state"] == "not_started"
    projected = memory_json(retired)
    assert projected["state"] == "retired" and projected["superseded_by_id"] == "memory-2"


def test_details_projection_and_revision_are_stable():
    evidence = SimpleNamespace(
        source_message_id="message-1", source_type=SimpleNamespace(value="user_stated"),
        linked_at=NOW,
    )
    message = SimpleNamespace(
        role=SimpleNamespace(value="user"), content="我喜欢喝茶。", created_at=NOW,
    )
    data = details_json(SimpleNamespace(
        memory=memory(), sources=[SimpleNamespace(evidence=evidence, source_message=message)],
    ))
    assert data["sources"][0]["message"]["content"] == "我喜欢喝茶。"
    assert revision(data) == revision(dict(reversed(list(data.items()))))


def test_persona_replacement_embeds_related_projection_without_backend_dependency():
    replacement = SimpleNamespace(
        candidate_persona_id="persona-2", replaced_persona_id="persona-1",
        target_revision=3, linked_at=NOW, applied_at=None,
    )
    related = SimpleNamespace(
        id="persona-1", subject_id="user:self", kind=SimpleNamespace(value="preference"),
        basis=SimpleNamespace(value="inferred"), label="饮品偏好", statement="用户偏好茶。",
        generated_at=NOW, valid_from=None, valid_to=None,
        status=SimpleNamespace(value="accepted"), generator_name="test",
        generator_version="v1", revision=3,
    )
    result = persona_replacement_json(replacement, related)
    assert result["related"]["id"] == "persona-1"
    assert result["related"]["revision"] == 3
