"""合成旁库恢复，不读日常数据库，不请求校园模型。"""
import asyncio
from dataclasses import asdict
from uuid import uuid4

import pytest
from test_console import console, login
from test_chat_console import backend
from longmemory.entrypoints.api.chat_store import ChatStore
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
            assert summary['items'][0]['request_id'] == body['request_id']
            assert 'input' not in summary['items'][0] and 'answer' not in summary['items'][0]
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
