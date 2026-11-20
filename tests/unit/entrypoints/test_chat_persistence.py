"""合成旁库恢复，不读日常数据库，不请求校园模型。"""
import asyncio
from contextlib import ExitStack, closing
from dataclasses import asdict
import sqlite3
from unittest.mock import Mock
from uuid import uuid4

import pytest
from test_console import console, login
from test_chat_console import backend
from longmemory.entrypoints.api.chat_store import ChatStore
from longmemory.entrypoints.api.contracts import ChatMessageRequest
from longmemory.entrypoints.api.routes.chat import Chat, OWNER_COOKIE


def test_restart_list_rename_history_and_replay(backend):
    histories = []
    class Generator:
        def generate_turn(self, **kwargs):
            histories.append(kwargs['history'])
            return 'synthetic answer'
    backend.provider = 'openai_compatible'
    backend.generator = Generator()
    async def run():
        async with console(chat_backend=backend) as (client, base, _):
            headers = await login(client, base)
            key = (await (await client.post(base+'/api/chats', headers=headers)).json())['chat_id']
            body = {'text':'合成测试', 'request_id':str(uuid4())}
            result = await (await client.post(base+f'/api/chats/{key}/messages', json=body, headers=headers)).json()
            assert result['status'] == 'completed'
            feedback_path = base+f'/api/chats/{key}/turns/{body["request_id"]}/memory-feedback'
            feedback_body = {'kind':'recall_miss', 'expected_revision':0}
            assert (await client.post(feedback_path, json=feedback_body)).status == 403
            feedback_response = await client.post(feedback_path, json=feedback_body, headers=headers)
            assert feedback_response.status == 200
            feedback = (await feedback_response.json())['feedback']
            assert feedback['kind'] == 'recall_miss' and feedback['revision'] == 1
            conflict = await client.post(feedback_path, json={
                'kind':'memory_ok', 'expected_revision':0,
            }, headers=headers)
            assert conflict.status == 409
            summary = await (await client.get(
                base + '/api/chat-memory-feedback/daily?local_date=' +
                feedback['occurred_at'][:10] + '&utc_offset_minutes=0'
            )).json()
            assert summary['action_counts']['recall_miss'] == 1
            assert summary['current_counts']['recall_miss'] == 1
            assert summary['current_total'] == 1
            assert summary['items'][0]['request_id'] == body['request_id']
            assert 'input' not in summary['items'][0] and 'answer' not in summary['items'][0]
            issue_index = await (await client.get(
                base + '/api/chat-memory-feedback?kind=issues&offset=0&limit=25'
            )).json()
            assert issue_index['total'] == 1
            assert issue_index['review_counts'] == {'open': 1, 'resolved': 0, 'dismissed': 0}
            assert issue_index['items'][0]['review']['state'] == 'open'
            assert issue_index['items'][0]['diagnostic_focus'] == 'retrieval'
            assert issue_index['items'][0]['retrieved_counts'] == {'l1': 0, 'l2': 0, 'l3': 0}
            assert 'input' not in issue_index['items'][0] and 'answer' not in issue_index['items'][0]
            review = await client.post(
                base + '/api/chat-memory-feedback/reviews', headers=headers,
                json={'source':'web_chat','target_id':body['request_id'],
                      'feedback_revision':1,'action':'dismiss',
                      'reason_code':'not_memory_issue','expected_review_revision':0},
            )
            assert review.status == 200
            assert (await review.json())['state'] == 'dismissed'
            assert (await (await client.get(
                base + '/api/chat-memory-feedback?kind=issues&offset=0&limit=25'
            )).json())['total'] == 0
            dismissed = await (await client.get(
                base + '/api/chat-memory-feedback?kind=dismissed&offset=0&limit=25'
            )).json()
            assert dismissed['items'][0]['review']['reason_code'] == 'not_memory_issue'
            assert (await client.post(base+f'/api/chats/{key}/title', json={'title':'昨天的聊天'}, headers=headers)).status == 200
            cookie = next(c.value for c in client.cookie_jar if c.key == OWNER_COOKIE)
        async with console(chat_backend=backend) as (client, base, _):
            await login(client, base)
            client.cookie_jar.update_cookies({OWNER_COOKIE:cookie})
            headers = await login(client, base)
            chats = await (await client.get(base+'/api/chats')).json()
            assert chats['chats'][0]['title'] == '昨天的聊天'
            saved = await (await client.get(base+f'/api/chats/{key}')).json()
            assert saved['turns'][0]['answer'] == 'synthetic answer'
            assert saved['turns'][0]['memory_feedback']['kind'] == 'recall_miss'
            changed = await client.post(
                base+f'/api/chats/{key}/turns/{body["request_id"]}/memory-feedback',
                json={'kind':'memory_ok', 'expected_revision':1}, headers=headers,
            )
            assert changed.status == 200
            refreshed = await (await client.get(base+f'/api/chats/{key}')).json()
            assert refreshed['turns'][0]['memory_feedback']['kind'] == 'memory_ok'
            assert len(refreshed['turns'][0]['memory_feedback_events']) == 2
            changed_summary = await (await client.get(
                base + '/api/chat-memory-feedback/daily?local_date=' +
                feedback['occurred_at'][:10] + '&utc_offset_minutes=0'
            )).json()
            assert changed_summary['action_counts']['recall_miss'] == 1
            assert changed_summary['action_counts']['memory_ok'] == 1
            assert changed_summary['current_counts']['memory_ok'] == 1
            assert changed_summary['current_counts']['recall_miss'] == 0
            assert (await (await client.get(
                base + '/api/chat-memory-feedback?kind=issues&offset=0&limit=25'
            )).json())['total'] == 0
            all_index = await (await client.get(
                base + '/api/chat-memory-feedback?kind=all&offset=0&limit=25'
            )).json()
            assert all_index['total'] == 1
            assert all_index['counts']['memory_ok'] == 1
            replay = await (await client.post(base+f'/api/chats/{key}/messages', json=body, headers=headers)).json()
            assert replay['memory_feedback']['kind'] == 'memory_ok' and len(histories) == 1
            await client.post(base+f'/api/chats/{key}/messages', json={'text':'继续', 'request_id':str(uuid4())}, headers=headers)
            assert histories[-1][0]['content'] == '合成测试'
            client.cookie_jar.clear()
            await login(client, base)
            assert (await (await client.get(base+'/api/chats')).json())['chats'] == []
    asyncio.run(run())


def test_sidecar_does_not_migrate_memory_and_exclusive_lock(backend):
    before = backend.database.read_bytes()
    store = ChatStore(backend.database)
    assert store.load() == {}
    assert not store.path.exists()
    second = ChatStore(backend.database)
    with pytest.raises(ValueError):
        second.load()
    store.save('test', asdict(Chat('synthetic-owner', 0)))
    store.close()
    assert second.load()['test']['title'] == '新聊天'
    second.close()
    assert backend.database.read_bytes() == before


def test_sidecar_connections_close_after_each_operation_and_file_can_be_renamed(tmp_path, monkeypatch):
    database = tmp_path / 'synthetic.db'
    connect = sqlite3.connect
    connections = []
    with ExitStack() as cleanup:
        def track_connection(*args, **kwargs):
            db = connect(*args, **kwargs)
            connections.append(db)  # 持有真实连接，排除垃圾回收代为关闭的情况。
            cleanup.callback(db.close)
            return db

        monkeypatch.setattr(sqlite3, 'connect', track_connection)
        with closing(ChatStore(database)) as store:
            assert store.load() == {}
            store.save('one', {'title': '合成会话'})
            with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
                connections[-1].execute('SELECT 1')
        with closing(ChatStore(database)) as reopened:
            assert reopened.load() == {'one': {'title': '合成会话'}}
            with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
                connections[-1].execute('SELECT 1')
            reopened.remove('one')
            with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
                connections[-1].execute('SELECT 1')

        assert len(connections) == 3
        renamed = store.path.rename(tmp_path / 'renamed.chats.sqlite3')
        with closing(connect(renamed)) as db:
            assert db.execute('SELECT id FROM web_chats').fetchall() == []


def test_sidecar_failed_delete_rolls_back_before_closing(tmp_path, monkeypatch):
    with closing(ChatStore(tmp_path / 'synthetic.db')) as store:
        store.load()
        store.save('one', {'title': '保留原会话'})
        connect = sqlite3.connect
        with closing(connect(store.path)) as db, db:
            db.execute("""CREATE TRIGGER reject_delete AFTER DELETE ON web_chats
                          BEGIN SELECT RAISE(FAIL, 'synthetic delete fault'); END""")
        statements = []
        with closing(connect(store.path)) as writer:
            writer.set_trace_callback(statements.append)
            monkeypatch.setattr(sqlite3, 'connect', lambda path: writer)
            with pytest.raises(sqlite3.IntegrityError, match='synthetic delete fault'):
                store.remove('one')
            assert 'ROLLBACK' in statements
            with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
                writer.execute('SELECT 1')
        with closing(connect(store.path)) as db:
            assert db.execute('SELECT id FROM web_chats').fetchall() == [('one',)]


def test_interrupted_turn_recovered_without_reexecution(backend):
    import hashlib
    token = 'a'*64
    body = {'request_id':str(uuid4()), 'input':'合成中断输入'}
    key = str(uuid4())
    store = ChatStore(backend.database)
    store.save(key, asdict(Chat(hashlib.sha256(token.encode()).hexdigest(), 0, pending=True, active_request=body)))
    async def run():
        async with console(chat_backend=backend) as (client, base, _):
            headers = await login(client, base)
            client.cookie_jar.update_cookies({OWNER_COOKIE:token})
            data = await (await client.get(base+f'/api/chats/{key}')).json()
            assert not data['pending'] and data['turns'][0]['status'] == 'interrupted'
            replay = await (await client.post(base+f'/api/chats/{key}/messages',
                json={'text':body['input'], 'request_id':body['request_id']}, headers=headers)).json()
            assert replay['status'] == 'interrupted'
    asyncio.run(run())


@pytest.mark.parametrize("recover_via", ["query", "replay", "restart"])
def test_final_save_failure_never_reexecutes_or_exposes_uncommitted_turn(
    backend, monkeypatch, recover_via,
):
    generate = Mock(return_value="合成回答")
    monkeypatch.setattr(backend.generator, "generate", generate)
    save = ChatStore.save
    storage_down = True

    def save_with_fault(store, key, payload):
        if storage_down and payload["turns"] and not payload["pending"]:
            raise sqlite3.OperationalError("synthetic final write failure")
        save(store, key, payload)

    monkeypatch.setattr(ChatStore, "save", save_with_fault)
    body = {"request_id": str(uuid4()), "text": "合成输入"}

    async def run():
        nonlocal storage_down
        async with console(chat_backend=backend) as (client, base, _):
            headers = await login(client, base)
            key = (await (await client.post(base + "/api/chats", headers=headers)).json())["chat_id"]
            detail = f"/api/chats/{key}"
            send = base + detail + "/messages"
            for _ in range(2):
                response = await client.post(send, json=body, headers=headers)
                assert response.status == 503
                assert await response.json() == {"error": "chat_archive_unavailable"}
                snapshot = await (await client.get(base + detail)).json()
                assert snapshot["pending"] and snapshot["turns"] == []
            listing = await (await client.get(base + "/api/chats")).json()
            assert listing["chats"][0]["turn_count"] == 0
            for change, error in [({"text": "改过的内容"}, "chat_request_conflict"),
                                  ({"request_id": str(uuid4())}, "chat_busy")]:
                response = await client.post(send, json={**body, **change}, headers=headers)
                assert response.status == 409 and (await response.json())["error"] == error

            if recover_via != "restart":
                storage_down = False
                if recover_via == "replay":
                    response = await client.post(send, json=body, headers=headers)
                    assert response.status == 200 and (await response.json())["answer"] == "合成回答"
                snapshot = await (await client.get(base + detail)).json()
                assert not snapshot["pending"] and len(snapshot["turns"]) == 1
                assert snapshot["turns"][0]["status"] == "completed"
                assert snapshot["turns"][0]["request_id"] == body["request_id"]
            cookie = next(c.value for c in client.cookie_jar if c.key == OWNER_COOKIE)

        storage_down = False
        async with console(chat_backend=backend) as (client, base, _):
            client.cookie_jar.update_cookies({OWNER_COOKIE: cookie})
            headers = await login(client, base)
            saved = await (await client.get(base + detail)).json()
            assert not saved["pending"] and len(saved["turns"]) == 1
            turn = saved["turns"][0]
            if recover_via == "restart":
                assert turn["status"] == "interrupted" and turn["error"] == "interrupted_write_state_unknown"
            else:
                assert turn == snapshot["turns"][0]
            response = await client.post(base + detail + "/messages", json=body, headers=headers)
            assert response.status == 200 and await response.json() == turn
            generate.assert_called_once()

    asyncio.run(run())


def test_unexpected_backend_interruption_reserves_request_id(backend, monkeypatch):
    interrupted = Mock(side_effect=RuntimeError("synthetic interruption"))
    monkeypatch.setattr(backend, "run", interrupted)

    async def run():
        async with console(chat_backend=backend) as (client, base, _):
            headers = await login(client, base)
            key = (await (await client.post(base + "/api/chats", headers=headers)).json())["chat_id"]
            body = {"request_id": str(uuid4()), "text": "合成输入"}
            for _ in range(2):
                response = await client.post(base + f"/api/chats/{key}/messages", json=body, headers=headers)
                turn = await response.json()
                assert turn["status"] == "interrupted" and turn["error"] == "interrupted_write_state_unknown"
            interrupted.assert_called_once()

    asyncio.run(run())


def test_query_and_same_request_share_slow_final_save(backend, monkeypatch):
    generate = Mock(return_value="合成回答")
    monkeypatch.setattr(backend.generator, "generate", generate)
    save = ChatStore.save
    attempts = []

    async def run():
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()

        def slow_final_save(store, key, payload):
            if payload["turns"] and not payload["pending"]:
                attempts.append(key)
                if len(attempts) == 1:
                    raise sqlite3.OperationalError("synthetic first failure")
                loop.call_soon_threadsafe(entered.set)
            save(store, key, payload)

        monkeypatch.setattr(ChatStore, "save", slow_final_save)
        async with console(chat_backend=backend) as (client, base, _):
            headers = await login(client, base)
            key = (await (await client.post(base + "/api/chats", headers=headers)).json())["chat_id"]
            detail = base + f"/api/chats/{key}"
            send = detail + "/messages"
            body = {"request_id": str(uuid4()), "text": "合成输入"}
            assert (await client.post(send, json=body, headers=headers)).status == 503
            replay_parsed = asyncio.Event()
            validate = ChatMessageRequest.model_validate

            def validate_replay(data):
                message = validate(data)
                replay_parsed.set()
                return message

            monkeypatch.setattr(ChatMessageRequest, "model_validate", staticmethod(validate_replay))
            with closing(sqlite3.connect(ChatStore(backend.database).path)) as locker:
                locker.execute("BEGIN IMMEDIATE")
                query = asyncio.create_task(client.get(detail))
                await asyncio.wait_for(entered.wait(), timeout=5)
                replay = asyncio.create_task(client.post(send, json=body, headers=headers))
                await asyncio.wait_for(replay_parsed.wait(), timeout=5)
                rename = await client.post(detail + "/title", json={"title": "暂缓改名"}, headers=headers)
                assert rename.status == 409
                assert (await client.get(base + "/api/chats")).status == 200
                assert not query.done() and not replay.done()
            snapshot = await (await query).json()
            turn = await (await replay).json()
            assert turn["status"] == "completed" and snapshot["turns"] == [turn]
            assert not snapshot["pending"]
            assert attempts == [key, key]
            generate.assert_called_once()

    asyncio.run(run())


def test_shutdown_retries_final_save_independently_for_each_chat(backend, monkeypatch):
    save = ChatStore.save
    healthy = set()
    attempts = []
    generate = Mock(return_value="合成回答")
    monkeypatch.setattr(backend.generator, "generate", generate)

    def partial_outage(store, key, payload):
        if payload["turns"] and not payload["pending"]:
            attempts.append(key)
            if key not in healthy:
                raise sqlite3.OperationalError("synthetic final write failure")
        save(store, key, payload)

    monkeypatch.setattr(ChatStore, "save", partial_outage)

    async def run():
        keys = []
        async with console(chat_backend=backend) as (client, base, _):
            headers = await login(client, base)
            for _ in range(2):
                key = (await (await client.post(base + "/api/chats", headers=headers)).json())["chat_id"]
                keys.append(key)
                body = {"request_id": str(uuid4()), "text": "合成输入"}
                response = await client.post(base + f"/api/chats/{key}/messages", json=body, headers=headers)
                assert response.status == 503
            cookie = next(c.value for c in client.cookie_jar if c.key == OWNER_COOKIE)
            healthy.add(keys[1])  # 两个会话均未手动查询；第二个在退出前恢复可写。

        assert all(attempts.count(key) == 2 for key in keys)
        async with console(chat_backend=backend) as (client, base, _):
            client.cookie_jar.update_cookies({OWNER_COOKIE: cookie})
            await login(client, base)
            for key, status in zip(keys, ["interrupted", "completed"], strict=True):
                snapshot = await (await client.get(base + f"/api/chats/{key}")).json()
                assert not snapshot["pending"] and len(snapshot["turns"]) == 1
                assert snapshot["turns"][0]["status"] == status
        assert generate.call_count == 2

    asyncio.run(run())
