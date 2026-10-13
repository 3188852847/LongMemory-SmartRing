"""真实受限 HTTP 与合成 WAV，不读取小智/个人配置，不调用 GPU。"""
import asyncio
import base64
from io import BytesIO
import json
import wave

from test_console import console, login
from longmemory.entrypoints.api import server
from longmemory.entrypoints.api.voice_settings import VoiceSettings
from longmemory.entrypoints.api.chat_backend import ChatBackend
from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.methods.longmemory_v1.method import LongMemoryV1


def synthetic_wav():
    output = BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes(b'\x01\x00' * 48000)
    return output.getvalue()


def test_authenticated_upload_profile_conflict_preview_and_no_global_limit_change(tmp_path, monkeypatch):
    backend = VoiceSettings(tmp_path / 'server', tmp_path / 'synthetic.db', tmp_path)
    LongMemoryV1(backend.database).close()
    chat = ChatBackend(backend.database, FakeAnswerGenerator())
    monkeypatch.setattr(server, 'VoiceSettings', lambda *args: backend)
    monkeypatch.setattr(backend, 'cosy_profile_service_state', lambda: 'ready')
    calls = []
    def synth(backend_name, text, **kwargs):
        calls.append((backend_name, text, kwargs))
        return synthetic_wav()
    monkeypatch.setattr(backend, 'local_speech', synth)
    async def run():
        async with console(chat_backend=chat, xiaozhi_server=tmp_path) as (client, base, _):
            assert (await client.get(base + '/api/voice-profile')).status == 401
            headers = await login(client, base)
            before = await (await client.get(base + '/api/voice-profile')).json()
            payload = {'audio_base64': base64.b64encode(synthetic_wav()).decode(), 'label': '合成声线', 'transcript': '这是合成文本。'}
            assert (await client.post(base + '/api/voice-references', json=payload)).status == 403
            response = await client.post(base + '/api/voice-references', json=payload, headers=headers)
            assert response.status == 201
            item = (await response.json())['item']
            assert len(item['id']) == 32
            # 超过普通 1KiB 的音频上传可用；其他 API 大 body 仍被原限制拒绝。
            assert (await client.post(base + '/api/voice-settings', json={'voice': 'x' * 1200}, headers=headers)).status != 200
            profile = {**before['profile'], 'reference_id': item['id'], 'transcript': item['transcript'], 'style': '温柔自然'}
            preview = await client.post(base + '/api/voice-profile/preview', headers=headers, json={'profile': profile})
            assert preview.status == 200 and preview.content_type == 'audio/wav'
            assert await preview.read() == synthetic_wav()
            assert backend.cosy_profiles.profile()[0] == before['profile']
            assert calls[0][0] == 'cosyvoice3' and calls[0][2]['voice_profile'] == profile
            assert calls[0][2]['bypass_local_cache'] is True
            saved = await client.post(base + '/api/voice-profile', headers=headers, json={'profile': profile, 'expected_profile_digest': before['profile_digest']})
            assert saved.status == 200
            assert (await saved.json())['activation'] == 'next_synthesis'
            stale = await client.post(base + '/api/voice-profile', headers=headers, json={'profile': before['profile'], 'expected_profile_digest': before['profile_digest']})
            assert stale.status == 409 and await stale.json() == {'error': 'voice_profile_changed'}
            bad = await client.post(base + '/api/voice-references', headers=headers, json={**payload, 'audio_base64': 'invalid!@'})
            assert bad.status == 400
            arbitrary = {**profile, 'reference_id': '../secret.wav'}
            assert (await client.post(base + '/api/voice-profile/preview', headers=headers, json={'profile': arbitrary})).status == 409
            assert len(calls) == 1
            assert (await client.get(base + '/api/voice-profile', headers={'Origin': 'https://evil.invalid'})).status == 403
    asyncio.run(run())


def test_reference_upload_bounded_and_no_write_on_invalid_wave(tmp_path, monkeypatch):
    backend = VoiceSettings(tmp_path / 'server', tmp_path / 'synthetic.db', tmp_path)
    LongMemoryV1(backend.database).close()
    chat = ChatBackend(backend.database, FakeAnswerGenerator())
    monkeypatch.setattr(server, 'VoiceSettings', lambda *args: backend)
    monkeypatch.setattr(backend, 'cosy_profile_service_state', lambda: 'ready')
    async def run():
        async with console(chat_backend=chat, xiaozhi_server=tmp_path) as (client, base, _):
            headers = await login(client, base)
            response = await client.post(base + '/api/voice-references', headers=headers, json={'audio_base64': base64.b64encode(b'RIFF-fake').decode(), 'label': '合成', 'transcript': '合成'})
            assert response.status == 400 and not (tmp_path / 'data').exists()
            oversized = json.dumps({'audio_base64': 'A' * (6 * 1024 * 1024), 'label': '合成', 'transcript': '合成'})
            response = await client.post(base + '/api/voice-references', headers=headers | {'Content-Type': 'application/json'}, data=oversized)
            assert response.status == 400 and not (tmp_path / 'data').exists()
    asyncio.run(run())
