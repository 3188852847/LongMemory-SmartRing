import asyncio
import json
from test_console import console, login
from longmemory.entrypoints.api import server
from longmemory.entrypoints.api.chat_backend import ChatBackend
from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.methods.longmemory_v1.method import LongMemoryV1


def test_voxcpm_health_requires_expected_local_service(monkeypatch):
    class Response:
        status = 200
        def read(self, _limit):
            return json.dumps({'ready': True, 'provider': 'voxcpm2'}).encode()
    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ('127.0.0.1', 18768, 0.5)
        def request(self, method, path):
            assert (method, path) == ('GET', '/health')
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr('longmemory.entrypoints.api.voice_settings.http.client.HTTPConnection', Connection)
    assert server.VoiceSettings.voxcpm_ready() is True


def test_voice_api_auth_strict_body_and_audio(tmp_path, monkeypatch):
    database = tmp_path / 'synthetic.db'; LongMemoryV1(database).close()
    backend = ChatBackend(database, FakeAnswerGenerator())
    calls = []
    class Fake:
        def __init__(self, *args): pass
        async def call(self, body):
            calls.append(body)
            return b'audio' if body['action'] == 'preview' else {'voice':'synthetic'}
    monkeypatch.setattr(server, 'VoiceSettings', Fake)
    async def run():
        async with console(chat_backend=backend) as (client, base, _):
            await login(client, base)
            assert (await client.get(base + '/api/voice-settings')).status == 403
        async with console(chat_backend=backend, xiaozhi_server=tmp_path) as (client, base, _):
            url = base + '/api/voice-settings'
            headers = await login(client, base)
            assert (await client.get(url)).status == 200
            assert (await client.post(url + '/preview', json={'voice':'synthetic'})).status == 403
            assert (await client.post(url + '/preview', headers=headers, json={'voice':'synthetic', 'text':'private'})).status == 409
            response = await client.post(url + '/preview', headers=headers, json={'voice':'synthetic'})
            assert response.status == 200 and response.content_type == 'audio/mpeg'
            assert await response.read() == b'audio'
            assert response.headers['Cache-Control'] == 'no-store'
            assert (await client.post(url, headers=headers, json={'voice':'synthetic', 'expected_digest':'a'*64})).status == 200
    asyncio.run(run())
    assert len(calls) == 3
