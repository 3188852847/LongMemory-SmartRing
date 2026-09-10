"""全部使用合成配置与临时库，不读取个人角色、不访问学校模型。"""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from longmemory.entrypoints.api.role_settings import RoleSettings, RoleConflict
from longmemory.entrypoints.api.chat_backend import ChatBackend
from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.adapters.llm.openai_compatible import OpenAICompatibleAnswerGenerator, SYSTEM_PROMPT
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.longmemory_v1.method import LongMemoryV1
from test_console import console, login


def test_read_no_creation_save_restart_conflict(tmp_path):
    database = tmp_path / 'synthetic.db'
    store = RoleSettings(database, 'plain_v1')
    assert store.current()['revision'] == 0 and not store.path.exists()
    value = store.save(expected_revision=0, name='合成角色', prompt='说话简短')
    assert value['revision'] == 1
    assert RoleSettings(database, 'elysia_v1').current() == value
    with pytest.raises(RoleConflict):
        store.save(expected_revision=0, name='旧编辑', prompt='不要覆盖')
    assert store.current() == value and not database.exists()


def test_history_is_newest_first_and_does_not_change_current(tmp_path):
    store = RoleSettings(tmp_path / 'synthetic.db', 'plain_v1')
    assert store.history() == [] and not store.path.exists()
    first = store.save(expected_revision=0, name='第一版', prompt='第一版表达')
    second = store.save(expected_revision=1, name='第二版', prompt='第二版表达')
    assert store.history() == [second, first]
    assert store.current() == second


@pytest.mark.parametrize('change', [{'name':''}, {'prompt':' '}, {'prompt':'x'*12001}, {'expected_revision':True}, {'prompt':'x\x00'}])
def test_invalid_setting_does_not_create_files(tmp_path, change):
    store = RoleSettings(tmp_path / 'synthetic.db', 'plain_v1')
    with pytest.raises(ValueError):
        store.save(**({'expected_revision':0, 'name':'合成', 'prompt':'合成'} | change))
    assert not store.path.exists()


def test_concurrent_saves_do_not_overwrite(tmp_path):
    store = RoleSettings(tmp_path / 'synthetic.db', 'plain_v1')
    store.save(expected_revision=0, name='初始', prompt='初始')
    def save(n):
        try:
            return store.save(expected_revision=1, name=str(n), prompt=str(n))['revision']
        except RoleConflict:
            return 'conflict'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(map(str, pool.map(save, [1, 2]))) == ['2', 'conflict']


def test_role_snapshot_applies_next_turn_preserves_guardrails(tmp_path):
    database = tmp_path / 'synthetic.db'; LongMemoryV1(database).close()
    payloads = []
    def transport(_settings, body):
        payloads.append(json.loads(body))
        if len(payloads) == 1:
            backend.roles.save(expected_revision=1, name='第二版', prompt='第二版表达')
        return 200, b'{"choices":[{"message":{"content":"ok"}}]}'
    generator = OpenAICompatibleAnswerGenerator(ModelSettings(provider='openai_compatible', base_url='https://synthetic.invalid/v1', api_key='synthetic', model='test'), transport=transport)
    backend = ChatBackend(database, generator, provider='openai_compatible')
    backend.roles.save(expected_revision=0, name='第一版', prompt='第一版表达')
    first = backend.run('你好', ())
    second = backend.run('再聊一句', ())
    assert first['status'] == second['status'] == 'completed'
    assert first['role_revision'] == 1 and second['role_revision'] == 2
    assert payloads[0]['messages'][1]['content'] == '第一版表达'
    assert payloads[1]['messages'][1]['content'] == '第二版表达'
    assert payloads[0]['messages'][0]['content'] == SYSTEM_PROMPT


def test_role_api_security_validation_and_persistence(tmp_path):
    database = tmp_path / 'synthetic.db'; LongMemoryV1(database).close()
    backend = ChatBackend(database, FakeAnswerGenerator())
    async def run():
        async with console(chat_backend=backend) as (client, base, _):
            url = base + '/api/assistant-role'
            assert (await client.get(url)).status == 401
            headers = await login(client, base)
            initial = await (await client.get(url)).json()
            assert initial['device'] == 'not_synced' and initial['web'] == 'fake_no_persona'
            assert initial['history'] == []
            assert not backend.roles.path.exists()
            body = {'expected_revision':0, 'name':'合成角色', 'prompt':'合成内容'*1000}
            assert (await client.post(url, json=body)).status == 403
            assert (await client.post(url, json=body | {'api_key':'forbidden'}, headers=headers)).status == 400
            assert (await client.post(url, json=body, headers=headers)).status == 200
            assert (await client.post(url, json=body, headers=headers)).status == 409
            current = await (await client.get(url)).json()
            assert current['current']['prompt'] == body['prompt']
            assert current['history'][0]['revision'] == 1
            assert (await client.post(url, json=body | {'prompt':'x'*90000}, headers=headers)).status == 413
    asyncio.run(run())
