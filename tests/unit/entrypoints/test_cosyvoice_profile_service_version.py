import json
import pytest
from longmemory.entrypoints.api.voice_settings import VoiceSettings


@pytest.mark.parametrize(('body', 'expected'), [
    ({'ready': True, 'provider': 'cosyvoice3'}, 'needs_restart'),
    ({'ready': True, 'provider': 'cosyvoice3', 'voice_profile_contract_version': 1}, 'ready'),
    ({'ready': False, 'provider': 'cosyvoice3'}, 'unavailable'),
    ({'ready': True, 'provider': 'other', 'voice_profile_contract_version': 1}, 'unavailable'),
    ([], 'unavailable'),
])
def test_profile_feature_version_requires_actual_running_service(monkeypatch, body, expected):
    class Response:
        status = 200
        def read(self, maximum): return json.dumps(body).encode()
    class Connection:
        def __init__(self, host, port, timeout): assert (host, port) == ('127.0.0.1', 18770)
        def request(self, method, path): assert (method, path) == ('GET', '/health')
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr('longmemory.entrypoints.api.voice_settings.http.client.HTTPConnection', Connection)
    assert VoiceSettings.cosy_profile_service_state() == expected


def test_old_service_ignoring_draft_never_counts_as_successful_clone_preview(monkeypatch):
    class Response:
        status = 200
        def read(self, maximum): return b'RIFF-default-voice'
        def getheader(self, name): return None
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr('longmemory.entrypoints.api.voice_settings.http.client.HTTPConnection', Connection)
    with pytest.raises(ValueError, match='synthesis_failed'):
        VoiceSettings.local_speech('cosyvoice3', '固定测试', voice_profile={'version': 1, 'reference_id': None, 'transcript': '', 'style': '平静'})
