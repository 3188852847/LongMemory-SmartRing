"""临时SQLite验证批量来源与旧逐ID投影等价；不启动SDK。"""

from contextlib import contextmanager
import sqlite3
from types import SimpleNamespace

import pytest

from longmemory.methods.hy_memory.administration import HyAdministration


@pytest.fixture
def admin(tmp_path):
    state = SimpleNamespace(root=tmp_path, _lease=object())
    method = SimpleNamespace(_client=SimpleNamespace(state=state), wait_until_ready=lambda: None)
    result = HyAdministration(method)
    with result._ledger():
        pass
    return result


def insert(admin, request, item, source, state='completed', action='correct', occurred='2026-01-01T00:00:00Z'):
    with sqlite3.connect(admin._ledger_path) as db:
        db.execute('INSERT INTO operations (request_id,payload_hash,action,item_id,source_event_id,revision,state,occurred_at) '
                   'VALUES (?,?,?,?,?,?,?,?)', (request, 'synthetic-hash', action, item, source,
                                               'synthetic-revision', state, occurred))


def legacy_overlay(path, item):
    with sqlite3.connect(path) as db:
        rows = db.execute('SELECT source_event_id,state,action FROM operations WHERE item_id=? '
                          'ORDER BY occurred_at,request_id', (item,)).fetchall()
    return (tuple(dict.fromkeys(row[0] for row in rows if row[1] == 'completed' and row[2] == 'correct')),
            any(row[1] in {'running', 'uncertain'} for row in rows))


def test_order_deduplication_delete_and_uncertainty_match_original_projection(admin):
    # 写入顺序刻意不同于时间及request_id，不能依赖SQL自然行序。
    insert(admin, 'r9', 'item-a', 'source-last', occurred='2026-01-03')
    insert(admin, 'r2', 'item-a', 'source-b', occurred='2026-01-01')
    insert(admin, 'r1', 'item-a', 'source-a', occurred='2026-01-01')
    insert(admin, 'r3', 'item-a', 'source-a', occurred='2026-01-02')
    insert(admin, 'r4', 'item-a', 'delete-source', action='delete')
    insert(admin, 'r5', 'item-a', 'failed-source', state='failed')
    insert(admin, 'r6', 'item-a', 'uncertain-delete', state='uncertain', action='delete')
    insert(admin, 'r7', 'item-b', 'running-correction', state='running')
    insert(admin, 'r8', 'item-c', 'completed-delete', action='delete')
    items = ['item-b', 'item-a', 'item-c', 'missing', 'item-a']
    expected = {item: legacy_overlay(admin._ledger_path, item) for item in items}
    actual = admin.source_overlays(iter(items))
    assert actual == expected
    assert list(actual) == ['item-b', 'item-a', 'item-c', 'missing']
    assert actual['item-a'] == (('source-a', 'source-b', 'source-last'), True)
    assert actual['item-b'] == ((), True)
    assert actual['item-c'] == ((), False)
    assert all(admin.source_overlay(item) == expected[item] for item in expected)


def test_more_than_350_ids_open_ledger_once_and_query_bounded_chunks(admin, monkeypatch):
    items = [f'synthetic-item-{number:04}' for number in range(703)]
    with sqlite3.connect(admin._ledger_path) as db:
        db.executemany('INSERT INTO operations (request_id,payload_hash,action,item_id,source_event_id,revision,state,occurred_at) '
            'VALUES (?,?,?,?,?,?,?,?)', [(f'r-{number}', 'h', 'correct', item, f's-{number}', 'v', 'completed', '2026-01-01')
                                        for number, item in enumerate(items)])
    expected = {item: legacy_overlay(admin._ledger_path, item) for item in items}
    original = admin._ledger
    opens, queries = [], []
    class RecordingConnection:
        def __init__(self, db): self.db = db
        def execute(self, query, parameters):
            queries.append((query, tuple(parameters)))
            return self.db.execute(query, parameters)
    @contextmanager
    def counted():
        opens.append(True)
        with original() as db:
            yield RecordingConnection(db)
    monkeypatch.setattr(admin, '_ledger', counted)
    assert admin.source_overlays(items + items[:10]) == expected
    assert len(opens) == 1
    assert [len(parameters) for _, parameters in queries] == [350, 350, 3]
    assert sum(len(parameters) for _, parameters in queries) == 703


def test_empty_request_never_opens_existing_ledger(admin, monkeypatch):
    monkeypatch.setattr(admin, '_ledger', lambda: pytest.fail('empty batch must not open SQLite'))
    assert admin.source_overlays([]) == {}


def test_missing_ledger_does_not_create_one_or_initialize_engine(tmp_path):
    method = SimpleNamespace(_client=SimpleNamespace(state=SimpleNamespace(root=tmp_path)),
                             wait_until_ready=lambda: pytest.fail('read must not initialize engine'))
    admin = HyAdministration(method)
    assert admin.source_overlays(['a', 'a', 'b']) == {'a': ((), False), 'b': ((), False)}
    assert admin.source_overlay('a') == ((), False)
    assert not list(tmp_path.iterdir())


def test_next_call_sees_changed_states_new_sources_and_removed_rows(admin):
    insert(admin, 'r1', 'item', 'initial')
    first = admin.source_overlays(['item'])
    insert(admin, 'r2', 'item', 'new', state='running')
    assert first == {'item': (('initial',), False)}
    assert admin.source_overlays(['item']) == {'item': (('initial',), True)}
    with sqlite3.connect(admin._ledger_path) as db:
        db.execute("UPDATE operations SET state='completed' WHERE request_id='r2'")
    assert admin.source_overlays(['item']) == {'item': (('initial', 'new'), False)}
    with sqlite3.connect(admin._ledger_path) as db:
        db.execute("DELETE FROM operations WHERE request_id='r1'")
    assert admin.source_overlays(['item']) == {'item': (('new',), False)}
    assert first == {'item': (('initial',), False)}


def test_reopened_admin_preserves_interrupted_running_isolation(admin):
    insert(admin, 'r1', 'item', 'pending', state='running')
    reopened = HyAdministration(admin.method)
    assert reopened.source_overlays(['item']) == {'item': ((), True)}
    with sqlite3.connect(admin._ledger_path) as db:
        assert db.execute("SELECT state,error_code FROM operations WHERE request_id='r1'").fetchone() == (
            'uncertain', 'hy_management_interrupted')


def test_ledger_failure_propagates_instead_of_returning_safe_looking_empty_sources(admin, monkeypatch):
    @contextmanager
    def unavailable():
        raise sqlite3.OperationalError('synthetic ledger unavailable')
        yield
    monkeypatch.setattr(admin, '_ledger', unavailable)
    with pytest.raises(sqlite3.OperationalError, match='synthetic ledger unavailable'):
        admin.source_overlays(['item'])


def test_batch_reports_one_numeric_observation_without_item_or_source_values(admin):
    from longmemory.methods.hy_memory.observation import Observation, header
    insert(admin, 'r1', 'synthetic-item', 'synthetic-source')
    observation = Observation('a' * 32)
    with observation.activate():
        assert admin.source_overlays(['synthetic-item']) == {'synthetic-item': (('synthetic-source',), False)}
    stage = observation.snapshot()['stages']['management_overlay_ms']
    assert stage['calls'] == 1 and stage['total_ms'] >= 0
    assert 'synthetic-item' not in header(observation) and 'synthetic-source' not in header(observation)
