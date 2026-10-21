"""固定 Silero 控制流、合成 PCM 与替身推理；不连接服务或读取私人数据。"""

from collections import deque
import importlib
import json
import math
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
import time

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts/development/xiaozhi"
PCM = np.full(960, 4000, np.int16).tobytes()


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    observer = importlib.import_module("voice_vad_signal_observation")
    input_observer = importlib.import_module("voice_input_observation")
    assert Path(observer.__file__).resolve() == SCRIPTS / "voice_vad_signal_observation.py"
    # 安装会包装该内部类；每例还原，避免测试间累积。
    previous = input_observer._ObservedVAD.is_vad
    yield observer, input_observer
    input_observer._ObservedVAD.is_vad = previous


class Session:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def run(self, names, feed):
        self.calls += 1
        if self.fail:
            raise ValueError("never-export-inference-error")
        probability = .9 if self.calls % 11 < 7 else .05
        return [np.array([[probability]], np.float32), feed["state"] + .01]


def provider(session=None):
    logger = SimpleNamespace(bind=lambda **kwargs: SimpleNamespace(error=lambda *args: None))
    cls = runpy.run_path(str(ROOT / "tests/fixtures/xiaozhi_silero_snapshot_eb4b28c.py"),
                        init_globals={"np": np, "time": time, "VADProviderBase": object,
                                      "logger": logger, "TAG": "fixture"})["VADProvider"]
    value = cls.__new__(cls)
    value.session = session or Session()
    value.vad_threshold, value.vad_threshold_low = .5, .2
    value.silence_threshold_ms, value.frame_window_threshold = 1000, 3
    return value


def connection(vad):
    class Connection:
        _longmemory_input_observation_installed = True

        def _decode_opus_packet(self, data):
            return data

        def _apply_aec(self, timestamp, pcm_frame):
            return pcm_frame

    conn = Connection()
    conn.vad = vad
    conn.client_listen_mode = "realtime"
    conn.client_is_speaking = True
    conn.client_audio_buffer = bytearray()
    conn.client_voice_window = deque(maxlen=5)
    conn.last_is_voice = conn.client_have_voice = conn.client_voice_stop = False
    conn.vad_last_voice_time = 0
    return conn


def install(modules, conn):
    observer, input_observer = modules
    conn.vad = input_observer._ObservedVAD(conn.vad, input_observer._State())
    return observer.install_voice_vad_signal_observation(type(conn), input_observation_module=input_observer)


def counts(value, phase="speaking", *, recent=False):
    group = value["recent_groups" if recent else "groups"][phase]
    return {key: count for key, count in zip(value["count_keys"], group["counts"]) if count is not None}


def test_missing_getter_does_not_create_state_or_invent_zero(modules):
    observer, _ = modules
    conn = SimpleNamespace()
    assert observer.voice_vad_signal_snapshot(None)["state"] == "no_connection"
    value = observer.voice_vad_signal_snapshot(conn)
    assert value["state"] == "not_observed" and value["groups"] is None
    assert conn.__dict__ == {}


def test_exact_silero_returns_rnn_context_and_call_count_are_preserved(modules):
    observer, input_observer = modules
    baseline, observed = connection(provider()), connection(provider())
    raw_session = observed.vad.session
    install(modules, observed)
    for number in range(24):
        frame = PCM if number % 3 else bytes(1920)
        expected = baseline.vad.is_vad(baseline, frame)
        actual = observed.vad.is_vad(observed, frame)
        assert actual is expected
        np.testing.assert_array_equal(observed._vad_state, baseline._vad_state)
        np.testing.assert_array_equal(observed._vad_context, baseline._vad_context)
        assert observed.client_audio_buffer == baseline.client_audio_buffer
        assert observed.client_voice_window == baseline.client_voice_window
        assert observed.last_is_voice == baseline.last_is_voice
        assert observed.client_have_voice == baseline.client_have_voice
    value = observer.voice_vad_signal_snapshot(observed)
    group = value["groups"]["speaking"]
    assert raw_session.calls == baseline.vad.session.calls == 45
    assert counts(value)["inference_return"] == 45
    assert counts(value).get("inference_contract_other", 0) == 0
    assert counts(value)["vad_input"] == 24
    assert observed.vad.state.counts["vad_check"] == 24
    assert sum(group["probability"]["bins"]) == 45
    assert value["contract"]["threshold"] == .5
    assert value["contract"]["runtime_model_hash"] is None
    assert input_observer._attach(observed) is not None
    assert isinstance(observed.vad.original.session, observer._Session)


def test_swallowed_inference_error_is_none_and_not_relabelled_as_false(modules):
    observer, _ = modules
    raw = Session(fail=True)
    conn = connection(provider(raw))
    install(modules, conn)
    assert conn.vad.is_vad(conn, PCM) is None
    value = observer.voice_vad_signal_snapshot(conn)
    observed_counts = counts(value)
    assert raw.calls == observed_counts["inference_error"] == observed_counts["vad_none"] == 1
    assert observed_counts.get("vad_false", 0) == conn.vad.state.counts["vad_error"] == 0
    assert "never-export" not in json.dumps(value)


def test_installed_v2_decoder_aec_boundaries_and_wraparound(modules):
    observer, _ = modules
    conn = connection(provider())
    timestamp = 15
    reference_timestamp = 2**32 - 5
    conn.aec_audio_cache = {reference_timestamp: b"never-export-reference"}
    output = np.full(960, 400, np.int16).tobytes()
    # 模拟已安装的直连 v2 解码包装：观测器最后安装。
    def decode(self, data):
        return self._apply_aec(timestamp, data)
    def aec(self, timestamp, pcm_frame):
        assert pcm_frame is PCM
        return output
    type(conn)._decode_opus_packet = decode
    type(conn)._apply_aec = aec
    install(modules, conn)
    assert conn._decode_opus_packet(PCM) is output
    assert conn.vad.is_vad(conn, output) is False
    value = observer.voice_vad_signal_snapshot(conn)
    energy = value["groups"]["speaking"]["energy"]
    assert energy["aec_input"]["last_rms_pcm16"] == 4000
    for stage in ("aec_output", "decode_return", "vad_input"):
        assert energy[stage]["last_rms_pcm16"] == 400
    assert value["aec_reference"]["nearest_reference_abs_delta_ms"] == 20
    assert value["aec_reference"]["timestamp_nonzero"] is True
    assert "never-export" not in json.dumps(value)


def test_v1_no_aec_calls_are_unknown_not_zero_energy(modules):
    observer, _ = modules
    conn = connection(provider())
    install(modules, conn)
    assert conn._decode_opus_packet(PCM) is PCM
    group = observer.voice_vad_signal_snapshot(conn)["groups"]["speaking"]
    assert "aec_input" not in counts(observer.voice_vad_signal_snapshot(conn)) and "aec_input" not in group["energy"]
    assert observer.voice_vad_signal_snapshot(conn)["aec_reference"] is None


@pytest.mark.parametrize("mode,frame", [("manual", PCM), ("realtime", bytes(20))])
def test_no_inference_path_not_invented(modules, mode, frame):
    observer, _ = modules
    conn = connection(provider())
    conn.client_listen_mode = mode
    install(modules, conn)
    conn.vad.is_vad(conn, frame)
    group = observer.voice_vad_signal_snapshot(conn)["groups"]["speaking"]
    assert group["probability"] is None
    assert counts(observer.voice_vad_signal_snapshot(conn)).get("inference_return", 0) == 0


def test_idempotent_no_double_inference_or_input_observer(modules):
    observer, input_observer = modules
    conn = connection(provider())
    install(modules, conn)
    original = type(conn)._decode_opus_packet
    assert observer.install_voice_vad_signal_observation(type(conn))["already_installed"]
    assert type(conn)._decode_opus_packet is original
    for _ in range(3):
        input_observer._attach(conn)
    conn.vad.is_vad(conn, PCM)
    assert conn.vad.state.counts["vad_check"] == 1
    assert conn.vad.original.session.original.calls == 1


def test_shared_session_context_isolation_across_connections_and_phases(modules):
    observer, input_observer = modules
    shared = provider()
    first = connection(shared)
    second = type(first)()
    second.__dict__.update(connection(shared).__dict__)
    install(modules, first)
    second.vad = input_observer._ObservedVAD(shared, input_observer._State())
    second.client_is_speaking = False
    first.vad.is_vad(first, PCM)
    second.vad.is_vad(second, bytes(1920))
    first_snapshot = observer.voice_vad_signal_snapshot(first)
    second_snapshot = observer.voice_vad_signal_snapshot(second)
    assert counts(first_snapshot, "not_speaking") == {}
    assert counts(second_snapshot, "speaking") == {}
    assert first_snapshot["groups"]["speaking"]["energy"]["vad_input"]["last_rms_pcm16"] == 4000
    assert second_snapshot["groups"]["not_speaking"]["energy"]["vad_input"]["last_rms_pcm16"] == 0


def test_recent_buckets_expire_bound_and_getter_is_detached(modules, monkeypatch):
    observer, _ = modules
    conn = connection(provider())
    install(modules, conn)
    now = [10.]
    monkeypatch.setattr(observer.time, "monotonic", lambda: now[0])
    for second in range(10, 20):
        now[0] = second
        conn._decode_opus_packet(PCM)
    value = observer.voice_vad_signal_snapshot(conn)
    assert counts(value, recent=True)["decode_return"] == 3
    value["groups"]["speaking"]["counts"][0] = -1
    assert counts(observer.voice_vad_signal_snapshot(conn))["decode_return"] == 10
    now[0] = 25
    assert counts(observer.voice_vad_signal_snapshot(conn), recent=True) == {}
    assert len(getattr(conn, observer.STATE).recent) <= 3


def test_energy_pcm_edges_and_invalid_data(modules):
    observer, _ = modules
    assert observer._energy(b"x") is None
    assert observer._energy(b"") is None
    value = observer._energy(np.array([-32768, 32767, 0, 0], np.int16).tobytes())
    assert value["peak_pcm16"] == 32768
    assert value["zero_fraction"] == value["clipped_fraction"] == .5
    assert math.isfinite(value["dbfs"])


def test_original_decode_exception_identity_preserved(modules):
    observer, _ = modules
    conn = connection(provider())
    error = RuntimeError("never-export-decode-error")
    def fail(self, data):
        raise error
    type(conn)._decode_opus_packet = fail
    install(modules, conn)
    with pytest.raises(RuntimeError) as result:
        conn._decode_opus_packet(PCM)
    assert result.value is error
    value = observer.voice_vad_signal_snapshot(conn)
    assert counts(value)["decode_return_error"] == 1
    assert "never-export" not in json.dumps(value)


def test_observer_energy_failure_does_not_change_output(modules, monkeypatch):
    observer, _ = modules
    conn = connection(provider())
    install(modules, conn)
    def fail(pcm):
        raise ValueError("observer-only")
    monkeypatch.setattr(observer, "_energy", fail)
    assert conn._decode_opus_packet(PCM) is PCM
    assert conn.vad.is_vad(conn, PCM) is False


def test_saturation_and_json_safe_no_paths_or_payloads(modules):
    observer, _ = modules
    conn = connection(provider())
    install(modules, conn)
    conn._decode_opus_packet(PCM)
    state = getattr(conn, observer.STATE)
    state.groups["speaking"]["counts"]["decode_return"] = observer.LIMIT
    conn._decode_opus_packet(PCM)
    value = observer.voice_vad_signal_snapshot(conn)
    assert counts(value)["decode_return"] == observer.LIMIT
    encoded = json.dumps(value, allow_nan=False)
    assert str(ROOT) not in encoded and "audio" not in encoded


def test_worst_case_all_phases_and_saturated_values_fit_budget(modules):
    observer, _ = modules
    conn = connection(provider())
    state = observer._state(conn)
    for phase in observer.PHASES:
        for stage in observer.STAGES:
            state.record(phase, stage, energy=observer._energy(PCM))
        for event in observer.EXPORTED_COUNTS:
            state.record(phase, event, probability=.1234567890123456)
        for group in (state.groups[phase], state.recent[-1][1][phase]):
            group["counts"] = {key: observer.LIMIT for key in observer.EXPORTED_COUNTS}
            group["probability"]["bins"] = [observer.LIMIT] * 7
            group["probability"]["max"] = .9876543210987654
            for value in group["energy"].values():
                value["max_rms_pcm16"] = 32767.999
                value["max_peak_pcm16"] = 32768
                value["last"]["rms_pcm16"] = 32767.999
    state.contract = dict(session_observed=True, threshold=.1234567890123456,
                          threshold_low=.1234567890123456, silence_threshold_ms=60000.,
                          frame_window_threshold=100., runtime_model_hash=None)
    state.aec_reference = dict(timestamp_nonzero=True, reference_present=True,
                               nearest_reference_abs_delta_ms=2**31, reference_count=observer.LIMIT)
    value = observer.voice_vad_signal_snapshot(conn)
    encoded = json.dumps(value, allow_nan=False).encode()
    assert len(encoded) <= 6000, len(encoded)
