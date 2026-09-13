"""V44 日常 L1 提取账本只保存过程元数据，不复制用户正文。"""

from datetime import UTC, datetime
import sqlite3

import pytest

from longmemory.adapters.storage.sqlite_l1_extraction_audit import (
    L1ExtractionAuditMetadata,
    SQLiteL1ExtractionAuditStore,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


def _source(connection, message_id="source-1"):
    connection.execute(
        "INSERT INTO conversation_messages(id,role,content,created_at) VALUES (?,?,?,?)",
        (message_id, "user", "这段正文不应复制进审计表", "2026-09-13T01:00:00+00:00"),
    )
    connection.commit()


def _metadata():
    return L1ExtractionAuditMetadata(
        method_version="1", prompt_version="candidate-v1",
        preprocessor_version="safety-v3", prompt_sha256="a" * 64,
        provider="official", model="model-a",
    )


def test_v43_upgrade_adds_empty_extraction_ledger_without_changing_l0(tmp_path):
    database = tmp_path / "v43.db"
    connection = open_database(database)
    initialize_schema(connection)
    _source(connection)
    connection.execute("DROP TABLE l1_extraction_events")
    connection.execute("PRAGMA user_version=43")
    connection.commit()

    initialize_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM l1_extraction_events").fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_store_appends_started_and_terminal_metadata_without_content(tmp_path):
    connection = open_database(tmp_path / "audit.db")
    initialize_schema(connection)
    _source(connection)
    store = SQLiteL1ExtractionAuditStore(connection)
    now = datetime(2026, 9, 13, 1, 2, tzinfo=UTC)

    store.start(
        attempt_id="attempt-1", source_message_id="source-1",
        metadata=_metadata(), occurred_at=now,
    )
    store.finish(
        attempt_id="attempt-1", source_message_id="source-1",
        phase="completed", outcome_code="added", candidate_count=1,
        added_count=1, metadata=_metadata(), occurred_at=now,
        duration_ms=12.5,
    )

    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(l1_extraction_events)")
    }
    assert "content" not in columns and "source_text" not in columns
    rows = connection.execute(
        "SELECT phase,outcome_code,candidate_count,added_count,prompt_sha256 "
        "FROM l1_extraction_events ORDER BY phase DESC"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("started", None, None, None, "a" * 64),
        ("completed", "added", 1, 1, "a" * 64),
    ]
    page = store.list_recent(limit=10)
    assert page["counts"]["added"] == 1
    assert page["counts"]["incomplete"] == 0
    assert page["items"][0]["source_message_id"] == "source-1"
    assert "content" not in page["items"][0]
    connection.close()


def test_store_rejects_invalid_hash_and_missing_source(tmp_path):
    with pytest.raises(ValueError, match="metadata_invalid"):
        L1ExtractionAuditMetadata(
            method_version="1", prompt_version="v1",
            preprocessor_version="v1", prompt_sha256="not-a-hash",
            provider="official", model="model-a",
        )

    connection = open_database(tmp_path / "audit.db")
    initialize_schema(connection)
    store = SQLiteL1ExtractionAuditStore(connection)
    with pytest.raises(sqlite3.IntegrityError):
        store.start(
            attempt_id="attempt-missing", source_message_id="missing",
            metadata=_metadata(), occurred_at=datetime.now(UTC),
        )
    # 失败 INSERT 已回滚，同一连接仍可继续正常写入。
    _source(connection, "source-after-failure")
    connection.close()
