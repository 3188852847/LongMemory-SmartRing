import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from types import SimpleNamespace

from longmemory.adapters.storage.sqlite_follow_up_store import (
    SQLiteFollowUpCandidateStore,
)
from longmemory.core.proactive import FollowUpCandidate, FollowUpCandidateStatus
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema
from longmemory.entrypoints.api.memory_backend import MemoryBackend, MemoryAccessError


NOW = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)
CONTENT = "用户计划在周五晚上完善毕业设计汇报。"


def insert_memory(connection, *, retired_at=None, valid_from=None, valid_to=None):
    connection.execute(
        "INSERT INTO atomic_memories "
        "(id,subject_id,content,recorded_at,valid_from,valid_to,retired_at,superseded_by_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("memory-1", "user:self", CONTENT, NOW.isoformat(),
         valid_from.isoformat() if valid_from else None,
         valid_to.isoformat() if valid_to else None,
         retired_at.isoformat() if retired_at else None, None),
    )
    connection.commit()


def candidate(**changes):
    values = {
        "id": "a" * 32,
        "subject_id": "user:self",
        "source_memory_id": "memory-1",
        "source_content_sha256": hashlib.sha256(CONTENT.encode()).hexdigest(),
        "prompt_text": "毕业设计汇报准备得怎么样了？",
        "follow_up_at": NOW + timedelta(days=1),
        "status": FollowUpCandidateStatus.CANDIDATE,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    return FollowUpCandidate(**values)


def test_follow_up_candidate_keeps_l1_provenance_and_can_be_cancelled(tmp_path):
    connection = open_database(tmp_path / "follow-up.db")
    initialize_schema(connection)
    insert_memory(connection)
    store = SQLiteFollowUpCandidateStore(connection)
    store.create(candidate())
    row = store.list("user:self")[0]
    assert row["source_content"] == CONTENT
    assert row["status"] == "candidate"
    assert store.cancel(row["id"], expected_revision=1, now=NOW) is True
    assert store.list("user:self")[0]["status"] == "cancelled"
    connection.close()


def test_follow_up_rejects_retired_or_changed_l1_and_cascades_owner_deletion(tmp_path):
    connection = open_database(tmp_path / "follow-up-source.db")
    initialize_schema(connection)
    insert_memory(connection, retired_at=NOW)
    store = SQLiteFollowUpCandidateStore(connection)
    with pytest.raises(ValueError, match="follow_up_source_not_current"):
        store.create(candidate())
    connection.execute("UPDATE atomic_memories SET retired_at=NULL")
    with pytest.raises(ValueError, match="follow_up_source_conflict"):
        store.create(candidate(source_content_sha256="c" * 64))
    store.create(candidate())
    connection.execute("DELETE FROM atomic_memories WHERE id='memory-1'")
    assert connection.execute(
        "SELECT count(*) FROM companion_follow_up_candidates"
    ).fetchone()[0] == 0
    connection.close()


@pytest.mark.parametrize(
    ("valid_from", "valid_to"),
    [
        (NOW + timedelta(days=1, minutes=1), None),
        (None, NOW + timedelta(days=1)),
    ],
)
def test_follow_up_rejects_l1_outside_its_valid_time(
    tmp_path, valid_from, valid_to,
):
    connection = open_database(tmp_path / "follow-up-validity.db")
    initialize_schema(connection)
    insert_memory(connection, valid_from=valid_from, valid_to=valid_to)

    with pytest.raises(ValueError, match="follow_up_source_not_current"):
        SQLiteFollowUpCandidateStore(connection).create(candidate())

    connection.close()


def test_v33_upgrade_adds_empty_follow_up_table(tmp_path):
    connection = open_database(tmp_path / "v33.db")
    initialize_schema(connection)
    connection.execute("DROP TABLE companion_follow_up_candidates")
    connection.execute("PRAGMA user_version=33")
    initialize_schema(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute(
        "SELECT count(*) FROM companion_follow_up_candidates"
    ).fetchone()[0] == 0
    connection.close()


def test_memory_backend_requires_current_detail_revision_and_never_activates(tmp_path):
    path = tmp_path / "follow-up-api.db"
    connection = open_database(path)
    initialize_schema(connection)
    insert_memory(connection)
    connection.close()
    backend = MemoryBackend(path, clock=lambda: NOW)
    detail = backend.get("memory-1")
    request = SimpleNamespace(
        source_memory_id="memory-1",
        expected_memory_revision=detail["revision"],
        prompt_text="毕业设计汇报准备得怎么样了？",
        follow_up_at=NOW + timedelta(days=1),
        request_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    result = backend.create_follow_up_candidate(request)
    assert result["status"] == "candidate"
    assert result["ready_for_activation"] is True
    assert "outreach_id" not in result
    assert backend.cancel_follow_up_candidate(
        result["id"], expected_revision=1,
    )["status"] == "cancelled"

    stale_request = SimpleNamespace(**{
        **request.__dict__,
        "request_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "expected_memory_revision": "0" * 64,
    })
    with pytest.raises(MemoryAccessError, match="follow_up_source_conflict"):
        backend.create_follow_up_candidate(stale_request)
