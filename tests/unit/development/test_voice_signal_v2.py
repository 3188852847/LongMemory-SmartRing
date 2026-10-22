"""同端点显式协商独立AEC补充；保持完整v1及原设备响应预算。"""

import asyncio
from copy import deepcopy
import importlib
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace as NS

import pytest
from aiohttp.test_utils import TestClient, TestServer

from test_voice_signal_endpoint import maximum_signal

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts/development/xiaozhi'))
    return tuple(importlib.import_module(name) for name in
                 ('voice_signal_diagnostics', 'device_control', 'control_http'))


def maximum_v1(signal):
    value = maximum_signal(signal)
    # 旧白名单允许整个有限浮点域；正数最短JSON表示可长达23字符。
    longest = 1.2345678901234567e-100
    assert len(json.dumps(longest)) == 23
    for key in ('groups', 'recent_groups'):
        for group in value[key].values():
            for energy in group['energy'].values():
                energy['max_rms_pcm16'] = longest
                if key == 'groups':
                    energy['last_rms_pcm16'] = longest
            group['probability']['min'] = group['probability']['max'] = longest
    for key in ('threshold', 'threshold_low', 'silence_threshold_ms', 'frame_window_threshold'):
        value['contract'][key] = longest
    value['contract']['session_observed'] = False
    value['aec_reference']['timestamp_nonzero'] = False
    return value


def raw_v2(signal, *, maximum=False):
    value = maximum_v1(signal)
    total = dict(valid=3, invalid=0, zero_input=1, below_floor=1,
                 original_error=0, observer_error=0, ratio_bins=[0, 0, 0, 0, 1, 0])
    if maximum:
        total = {key: [signal.LIMIT] * 6 if key == 'ratio_bins' else signal.LIMIT for key in total}
    value.update(version=2, observation_id='f' * 16, clock_ms=signal.CLOCK_MAX,
                 aec_pairs=dict(rms_floor_pcm16=500, ratio_edges=list(signal.PAIR_RATIO_EDGES),
                                total=total, recent=deepcopy(total)))
    return value


def test_v1_float_domain_and_separate_v2_maximum_are_preserved(modules):
    signal, _, _ = modules
    old = maximum_v1(signal)
    assert signal.project(old) == old
    assert len(json.dumps(old).encode()) <= 6000
    raw = raw_v2(signal, maximum=True)
    assert len(json.dumps(raw).encode()) > 6000
    public = signal.project(raw, version=2)
    assert set(public) == {'version', 'kind', 'state', 'clock_ms', 'observation_generation', 'aec_pairs'}
    assert public['kind'] == 'aec_pairs_supplement' and public['state'] == 'observed'
    assert public['clock_ms'] == 2**63 - 1 > signal.LIMIT
    assert public['observation_generation'] == 'f' * 16
    assert set(public['aec_pairs']) == {'rms_floor_pcm16', 'ratio_edges', 'total'}
    assert len(json.dumps(public).encode()) <= signal.MAX_BYTES == 6000
    public['aec_pairs']['total']['ratio_bins'][0] = 0
    assert raw['aec_pairs']['total']['ratio_bins'][0] == signal.LIMIT
    print(json.dumps(dict(v1_bytes=len(json.dumps(old).encode()),
                         rejected_full_v2_bytes=len(json.dumps(raw).encode()),
                         supplement_max_bytes=len(json.dumps(signal.project(raw, version=2)).encode()))))


@pytest.mark.parametrize('bad', ['extra', 'version_bool', 'version_old', 'clock_bool', 'clock_negative',
    'clock_float', 'clock_overflow', 'clock_nan', 'generation_private', 'generation_upper',
    'generation_missing', 'floor_bool', 'floor_float', 'wrong_edges', 'total_extra', 'count_bool',
    'count_negative', 'count_overflow', 'bin_bool', 'bin_length', 'bad_denominator', 'unknown_state'])
def test_supplement_rejects_bad_fixed_fields_without_error_text(modules, bad):
    signal, _, _ = modules
    value = raw_v2(signal)
    if bad == 'extra': value['PRIVATE'] = 'PRIVATE'
    elif bad == 'version_bool': value['version'] = True
    elif bad == 'version_old': value['version'] = 1
    elif bad == 'clock_bool': value['clock_ms'] = True
    elif bad == 'clock_negative': value['clock_ms'] = -1
    elif bad == 'clock_float': value['clock_ms'] = 1.5
    elif bad == 'clock_overflow': value['clock_ms'] = 2**63
    elif bad == 'clock_nan': value['clock_ms'] = float('nan')
    elif bad == 'generation_private': value['observation_id'] = 'PRIVATE'
    elif bad == 'generation_upper': value['observation_id'] = 'F' * 16
    elif bad == 'generation_missing': value['observation_id'] = None
    elif bad == 'floor_bool': value['aec_pairs']['rms_floor_pcm16'] = True
    elif bad == 'floor_float': value['aec_pairs']['rms_floor_pcm16'] = 500.
    elif bad == 'wrong_edges': value['aec_pairs']['ratio_edges'][0] = .11
    elif bad == 'total_extra': value['aec_pairs']['total']['PRIVATE'] = 1
    elif bad == 'count_bool': value['aec_pairs']['total']['valid'] = True
    elif bad == 'count_negative': value['aec_pairs']['total']['invalid'] = -1
    elif bad == 'count_overflow': value['aec_pairs']['total']['original_error'] = 2**31
    elif bad == 'bin_bool': value['aec_pairs']['total']['ratio_bins'][0] = True
    elif bad == 'bin_length': value['aec_pairs']['total']['ratio_bins'].append(0)
    elif bad == 'bad_denominator': value['aec_pairs']['total']['valid'] += 1
    else: value['state'] = 'PRIVATE'
    result = signal.project(value, version=2)
    assert result == signal.missing('unavailable', version=2)
    assert 'PRIVATE' not in json.dumps(result)


def test_missing_pair_or_clock_never_becomes_zero_or_fake_time(modules):
    signal, _, _ = modules
    value = raw_v2(signal)
    value.update(aec_pairs=None, clock_ms=None)
    public = signal.project(value, version=2)
    assert public['state'] == 'observed'
    assert public['aec_pairs'] is None and public['clock_ms'] is None
    assert public['observation_generation'] == 'f' * 16
    for state in ('no_connection', 'not_observed', 'unavailable'):
        value.update(state=state, observation_id=None)
        assert signal.project(value, version=2) == signal.missing(state, version=2)
    value['aec_pairs'] = raw_v2(signal)['aec_pairs']
    assert signal.project(value, version=2) == signal.missing('unavailable', version=2)


def test_supplement_does_not_serialize_discarded_legacy_or_recent_values(modules):
    signal, _, _ = modules
    value = raw_v2(signal)
    value['groups'] = {'discarded': 'PRIVATE'}
    value['aec_pairs']['recent'] = {'discarded': 'PRIVATE'}
    result = signal.project(value, version=2)
    assert result['aec_pairs']['total']['valid'] == 3
    assert 'PRIVATE' not in json.dumps(result)


def test_snapshot_explicit_opt_in_old_producer_and_current_connection(modules, monkeypatch):
    signal, device, _ = modules
    calls = []
    def get(conn, **kwargs):
        calls.append((conn, kwargs))
        if not kwargs: return maximum_v1(signal)
        if conn is None:
            value = raw_v2(signal)
            value.update(state='no_connection', observation_id=None, aec_pairs=None)
            return value
        return raw_v2(signal)
    monkeypatch.setitem(sys.modules, 'voice_vad_signal_observation', NS(voice_vad_signal_snapshot=get))
    control = device.DeviceControl('synthetic')
    conn = NS(websocket=NS(state=NS(name='OPEN')))
    control.attach(conn, 'synthetic')
    assert control.voice_input_signal() == maximum_v1(signal)
    assert calls[-1] == (conn, {})
    assert control.voice_input_signal(version=2)['clock_ms'] == signal.CLOCK_MAX
    assert calls[-1] == (conn, {'include_aec_pairs': True})
    conn.websocket.state.name = 'CLOSED'
    assert control.voice_input_signal(version=2) == signal.missing('no_connection', version=2)
    assert calls[-1] == (None, {'include_aec_pairs': True})
    control.attach(NS(), 'synthetic')
    previous = len(calls)
    assert control.voice_input_signal(version=2) == signal.missing('unavailable', version=2)
    assert len(calls) == previous
    monkeypatch.setitem(sys.modules, 'voice_vad_signal_observation',
                        NS(voice_vad_signal_snapshot=lambda conn: maximum_v1(signal)))
    assert signal.snapshot(conn, version=2) == signal.missing('unavailable', version=2)
    assert signal.snapshot(conn) == maximum_v1(signal)


def test_real_ac_pair_snapshot_and_observed_without_pairs_are_read_only(modules):
    signal, _, _ = modules
    observer = importlib.import_module('voice_vad_signal_observation')
    phase = importlib.import_module('voice_input_observation')
    fixture = runpy.run_path(str(ROOT / 'tests/unit/development/test_voice_vad_signal_observation.py'))
    conn = fixture['connection'](fixture['provider']())
    previous = phase._ObservedVAD.is_vad
    try:
        conn.vad = phase._ObservedVAD(conn.vad, phase._State())
        observer.install_voice_vad_signal_observation(type(conn), input_observation_module=phase)
        conn._decode_opus_packet(fixture['PCM'])
        assert signal.snapshot(conn, version=2)['aec_pairs'] is None
        assert conn._apply_aec(1, fixture['PCM']) is fixture['PCM']
        calls = conn.vad.original.session.calls
        value = signal.snapshot(conn, version=2)
        assert value['aec_pairs']['total']['valid'] == 1
        assert value['aec_pairs']['total']['ratio_bins'] == [0, 0, 0, 0, 1, 0]
        for _ in range(3):
            assert signal.snapshot(conn, version=2)['aec_pairs'] == value['aec_pairs']
            assert signal.snapshot(conn)['version'] == 1
        assert conn.vad.original.session.calls == calls == 0
        empty = NS()
        assert signal.snapshot(empty, version=2)['state'] == 'not_observed'
        assert not vars(empty)
    finally:
        phase._ObservedVAD.is_vad = previous


def test_real_http_negotiation_auth_budget_and_complete_existing_client(modules, monkeypatch, tmp_path):
    signal, device, http = modules
    from longmemory.adapters.device_control.xiaozhi import XiaozhiControlClient
    old = runpy.run_path(str(ROOT / 'tests/fixtures/ai_signal_device_status_boundary.py'))['maximum_existing_status']()
    control = device.DeviceControl('synthetic')
    control.status = lambda: deepcopy(old)
    calls = []
    def get(conn, **kwargs):
        calls.append(kwargs)
        return raw_v2(signal, maximum=True) if kwargs else maximum_v1(signal)
    monkeypatch.setitem(sys.modules, 'voice_vad_signal_observation', NS(voice_vad_signal_snapshot=get))
    control.attach(NS(websocket=NS(state=NS(name='OPEN'))), 'synthetic')
    async def run():
        headers = {'Host': '127.0.0.1:12345', 'Authorization': 'Bearer ' + 'a' * 64}
        async with TestClient(TestServer(http.create_app(control, 'a' * 64, port=12345))) as client:
            for extra, status in (({'Authorization': 'wrong'}, 401), ({'Host': 'wrong'}, 403),
                                  ({'Origin': 'http://invalid'}, 403), ({'Sec-Fetch-Site': 'same-origin'}, 403)):
                async with client.get('/api/voice-input-signal?version=2', headers={**headers, **extra}) as response:
                    assert response.status == status
            assert not calls
            for method, path in (('POST', '/api/voice-input-signal?version=2'),
                                 ('HEAD', '/api/voice-input-signal?version=2'),
                                 ('GET', '/api/voice-input-signal/?version=2')):
                async with client.request(method, path, headers=headers) as response:
                    assert response.status in (404, 405)
            assert not calls
            for query in ('version=', 'version=3', 'version=02', 'version=PRIVATE',
                          'version=2&version=2', 'version=1&version=2', 'private=1', 'version=2&private=1'):
                async with client.get('/api/voice-input-signal?' + query, headers=headers) as response:
                    assert response.status == 400
                    assert 'PRIVATE' not in await response.text()
            assert not calls
            for query, expected in (('', maximum_v1(signal)), ('?version=1', maximum_v1(signal)),
                                    ('?version=2', signal.project(raw_v2(signal, maximum=True), version=2))):
                async with client.get('/api/voice-input-signal' + query, headers=headers) as response:
                    raw = await response.read()
                    assert response.status == 200 and len(raw) <= 6000
                    assert response.headers['Cache-Control'] == 'no-store'
                    assert json.loads(raw) == expected
            assert calls == [{}, {}, {'include_aec_pairs': True}]
            async with client.get('/api/device', headers=headers) as response:
                raw = await response.read()
                assert raw == json.dumps(old).encode() and len(raw) == 15519 < 16384
            class LocalSession:
                def request(self, method, url, **kwargs):
                    assert url.startswith('http://127.0.0.1:8766/')
                    kwargs['headers']['Host'] = headers['Host']
                    return client.session.request(method, client.make_url(url.removeprefix('http://127.0.0.1:8766')), **kwargs)
            token = tmp_path / 'synthetic-token'
            token.write_text('a' * 64)
            bridge = XiaozhiControlClient(token)
            bridge._session = LocalSession()
            assert await bridge._request('GET', '/api/voice-input-signal') == maximum_v1(signal)
            assert await bridge._request('GET', '/api/voice-input-signal?version=2') == signal.project(raw_v2(signal, maximum=True), version=2)
    asyncio.run(run())
