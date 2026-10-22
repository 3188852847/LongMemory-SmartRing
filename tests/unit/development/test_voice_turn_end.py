"""合成 PCM、可控同步模型与上游形状的接收边界；不导入日用服务。"""

import asyncio
import importlib.util
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts/development/xiaozhi"
SPEC = importlib.util.spec_from_file_location("voice_turn_end_ac_test", SCRIPTS / "voice_turn_end.py")
turn = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = turn
SPEC.loader.exec_module(turn)
PCM = b"\x17\x00" * 960


class Detector:
    def __init__(self, probability=0.9, blocked=False):
        self.probability = probability
        self.blocked = blocked
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def predict(self, pcm):
        self.calls.append(pcm)
        self.entered.set()
        if self.blocked:
            assert self.release.wait(3)
        if isinstance(self.probability, Exception):
            raise self.probability
        return self.probability


def state_harness(detector=None, **kwargs):
    now = [0.0]
    events = []
    config = turn.TurnEndConfig(mode=kwargs.pop("mode", "enabled"), **kwargs)
    state = turn.TurnEndState(config, turn.InferenceSlot(detector), events.append, lambda: now[0])
    return SimpleNamespace(state=state, detector=detector, now=now, events=events)


def observe(h, silence=300, *, voice=False, stamp=1, stop=False, pcm=PCM * 20):
    return h.state.observe(pcm=pcm, audio_have_voice=voice, voice_stamp=stamp,
                           silence_ms=silence, upstream_stop=stop)


async def finish(h):
    if h.state.pending:
        await asyncio.shield(h.state.pending[0])


def test_source_is_assigned_worktree():
    assert Path(turn.__file__).resolve() == SCRIPTS / "voice_turn_end.py"
    import longmemory
    assert Path(longmemory.__file__).resolve().is_relative_to(ROOT / "src")


def test_default_off_has_no_patch_or_model():
    class Connection:
        pass
    class Provider:
        pass
    assert turn.install_voice_turn_end(Connection, Provider) == {"mode": "off", "installed": False}
    assert not hasattr(Provider, "receive_audio")


def test_complete_only_confirms_after_guard_and_does_not_duplicate():
    h = state_harness(Detector())
    async def run():
        assert not observe(h)
        await finish(h)
        assert not observe(h, 360)
        assert observe(h, 420)
        assert not observe(h, 480)
    asyncio.run(run())
    assert [e["type"] for e in h.events] == ["provisional", "confirmed"]
    assert h.events[0]["authoritative"] is False
    assert h.events[1]["authoritative"] is True
    assert h.events[1]["transcript_revision"] is None


def test_thinking_pause_holds_legacy_then_continued_speech_invalidates():
    h = state_harness(Detector(0.1))
    async def run():
        observe(h)
        await finish(h)
        assert not observe(h, 600, stop=True)
        assert not observe(h, 0, voice=True, stamp=2, stop=True)
        h.detector.probability = 0.95
        assert not observe(h, 300, stamp=2)
        await finish(h)
        assert observe(h, 420, stamp=2)
    asyncio.run(run())
    assert [e["type"] for e in h.events] == ["cancel", "continued", "provisional", "confirmed"]
    assert [e["audio_revision"] for e in h.events] == [0, 1, 1, 1]
    assert all(e["cancel_epoch"] == 1 for e in h.events)


def test_stale_complete_after_resumed_speech_never_confirms():
    h = state_harness(Detector(blocked=True))
    async def run():
        observe(h)
        assert await asyncio.to_thread(h.detector.entered.wait, 1)
        old = h.state.pending[0]
        observe(h, 0, voice=True, stamp=2)
        h.detector.release.set()
        await old
        assert not observe(h, 100, stamp=2)
        assert h.state.probability is None
    asyncio.run(run())
    assert [e["type"] for e in h.events] == ["cancel", "continued"]


def test_shadow_never_changes_legacy_and_revokes_hypothetical_confirmation():
    h = state_harness(Detector(), mode="shadow")
    async def run():
        observe(h)
        await finish(h)
        assert not observe(h, 420)
        assert h.state.confirmed
        observe(h, 0, voice=True, stamp=2)
        assert not h.state.confirmed
        assert observe(h, 600, stamp=2, stop=True)
    asyncio.run(run())
    assert all(not e["authoritative"] for e in h.events)
    assert [e["type"] for e in h.events][:4] == ["provisional", "confirmed", "cancel", "continued"]


@pytest.mark.parametrize("value", [RuntimeError("synthetic"), float("nan"), -1, 2, "0.9"])
def test_invalid_or_failed_model_preserves_legacy_endpoint(value):
    h = state_harness(Detector(value))
    async def run():
        observe(h)
        try:
            await finish(h)
        except Exception:
            pass
        assert not observe(h, 420)
        assert observe(h, 600, stop=True)
    asyncio.run(run())
    assert h.events[-1]["reason"] == "legacy_fallback"


def test_timeout_keeps_actual_slot_busy_and_no_late_result_reuse():
    detector = Detector(blocked=True)
    h = state_harness(detector)
    other = turn.TurnEndState(h.state.config, h.state.slot)
    async def run():
        observe(h)
        future = h.state.pending[0]
        assert await asyncio.to_thread(detector.entered.wait, 1)
        h.now[0] = 0.151
        assert observe(h, 600, stop=True)
        assert h.state.latest_status == "timeout"
        other.observe(pcm=PCM * 20, audio_have_voice=False, voice_stamp=2,
                      silence_ms=300, upstream_stop=False)
        assert other.latest_status == "busy"
        assert len(detector.calls) == 1
        detector.release.set()
        await future
        assert h.state.probability is None
    asyncio.run(run())


def test_low_probability_has_bounded_attempts_and_silence_fallback():
    h = state_harness(Detector(0.1), max_attempts=2)
    async def run():
        for silence in range(300, 1800, 60):
            assert not observe(h, silence, stop=silence >= 600)
            await finish(h)
        assert observe(h, 1800, stop=True)
    asyncio.run(run())
    assert len(h.detector.calls) == 2
    assert h.events[-1]["reason"] == "silence_budget"


def test_reset_close_and_missing_model_are_bounded():
    h = state_harness()
    async def run():
        assert not observe(h)
        assert observe(h, 600, stop=True)
        h.state.cancel()
        assert h.state.turn_id == 1
        observe(h)
        h.state.cancel(close=True, reason="closed")
        assert h.state.closed
        assert not observe(h, 1800)
    asyncio.run(run())
    assert h.events[-1]["type"] == "cancel"
    assert h.events[-1]["reason"] == "closed"


def test_missing_model_cannot_shorten_a_longer_legacy_silence_threshold():
    h = state_harness()
    async def run():
        for silence in range(300, 3000, 60):
            assert not observe(h, silence)
        assert observe(h, 3000, stop=True)
    asyncio.run(run())
    assert h.events[-1]["reason"] == "legacy_fallback"


def test_no_model_result_cannot_hold_an_already_due_legacy_endpoint():
    h = state_harness(Detector(blocked=True))
    async def run():
        assert observe(h, 300, stop=True)
        assert h.events[-1]["reason"] == "legacy_fallback"
        h.detector.release.set()
        await finish(h)
    asyncio.run(run())


def test_eight_second_model_context_but_no_audio_in_snapshot_or_event():
    h = state_harness(Detector())
    async def run():
        observe(h, pcm=PCM * 1000)
        await finish(h)
        observe(h, 420)
    asyncio.run(run())
    assert len(h.detector.calls[0]) == 256000
    assert "pcm" not in str(h.state.snapshot())
    assert all(isinstance(value, (str, int, bool, type(None))) for event in h.events for value in event.values())


def test_callback_failure_does_not_break_original_endpoint():
    h = state_harness()
    h.state.emit = lambda event: (_ for _ in ()).throw(RuntimeError("synthetic"))
    async def run():
        observe(h)
        assert observe(h, 600, stop=True)
    asyncio.run(run())
    assert h.state.counts["callback_failed"] == 1


def boundary_harness(monkeypatch, *, mode="enabled", detector=None, prefetch=False):
    # 复用既有 ASR 预取测试的合成 Connection/Provider，不导入外部服务。
    spec = importlib.util.spec_from_file_location("asr_prefetch_ac_boundary", Path(__file__).with_name("test_voice_asr_prefetch.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    h = module.harness(monkeypatch, enabled=prefetch)
    events = []
    turn.install_voice_turn_end(h.Connection, h.Provider, detector=detector,
                               config=turn.TurnEndConfig(mode=mode),
                               on_event=lambda conn, event: events.append(event), calibration_approved=True)
    return h, events


@pytest.mark.parametrize("prefetch", [False, True])
def test_receive_boundary_holds_then_confirms_full_continued_audio(monkeypatch, prefetch):
    detector = Detector(0.1)
    h, events = boundary_harness(monkeypatch, detector=detector, prefetch=prefetch)
    async def run():
        h.connection.asr_audio = [PCM] * 20
        await h.provider.receive_audio(h.connection, PCM, False)
        state = getattr(h.connection, turn.STATE)
        await asyncio.shield(state.pending[0])
        monkeypatch.setattr(turn.time, "time", lambda: 100.3)
        h.connection.client_voice_stop = True
        await h.provider.receive_audio(h.connection, PCM, False)
        assert not h.connection.submitted
        assert len(h.connection.asr_audio) == 22
        h.connection.vad_last_voice_time = 100300
        await h.provider.receive_audio(h.connection, PCM, True)
        assert not h.connection.client_voice_stop
        detector.probability = 0.95
        monkeypatch.setattr(turn.time, "time", lambda: 100.6)
        await h.provider.receive_audio(h.connection, PCM, False)
        await asyncio.shield(state.pending[0])
        monkeypatch.setattr(turn.time, "time", lambda: 100.72)
        await h.provider.receive_audio(h.connection, PCM, False)
        assert len(h.connection.submitted) == 1
        assert len(h.model.calls[-1]) == 25 * 1920
        assert not h.connection.asr_audio
        assert state.turn_id == 1
    asyncio.run(run())
    assert any(e["type"] == "continued" for e in events)
    assert events[-1]["type"] == "confirmed"


@pytest.mark.parametrize("condition", ["manual", "stream", "voiceprint", "speaking", "closed", "bad_pcm", "bad_stamp"])
def test_unsupported_receive_leaves_legacy_untouched(monkeypatch, condition):
    detector = Detector()
    h, events = boundary_harness(monkeypatch, detector=detector)
    if condition == "manual":
        h.connection.client_listen_mode = "manual"
    elif condition == "stream":
        h.provider.interface_type = SimpleNamespace(value="STREAM")
    elif condition == "voiceprint":
        h.connection.voiceprint_provider = object()
    elif condition == "speaking":
        h.connection.client_is_speaking = True
    elif condition == "closed":
        h.connection.stop_event.set()
    elif condition == "bad_stamp":
        h.connection.vad_last_voice_time = float("nan")
    async def run():
        h.connection.asr_audio = [PCM] * 20
        h.connection.client_voice_stop = True
        await h.provider.receive_audio(h.connection, b"x" if condition == "bad_pcm" else PCM, False)
    asyncio.run(run())
    assert detector.calls == []
    assert len(h.connection.submitted) == 1
    assert not any(e["type"] == "confirmed" for e in events)


def test_shadow_receive_is_byte_for_byte_original_submit(monkeypatch):
    h, events = boundary_harness(monkeypatch, mode="shadow", detector=Detector(0.1))
    async def run():
        h.connection.asr_audio = [PCM] * 20
        h.connection.client_voice_stop = True
        await h.provider.receive_audio(h.connection, PCM, False)
        assert h.model.calls == [PCM * 21]
        assert len(h.connection.submitted) == 1
        await h.connection.close()
        assert getattr(h.connection, turn.STATE).closed
    asyncio.run(run())
    assert all(not e["authoritative"] for e in events)


@pytest.mark.parametrize("settings", [{"mode": "other"}, {"threshold": 0.1}, {"max_attempts": 100},
                                       {"max_silence_ms": 4000}, {"inference_timeout_ms": 0}])
def test_unbounded_or_invalid_config_rejected(settings):
    with pytest.raises(ValueError):
        turn.TurnEndConfig(**settings)


def load_script(monkeypatch, name):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def test_scripted_replay_exposes_false_cut_and_missed_endpoint(monkeypatch):
    replay = load_script(monkeypatch, "voice_turn_end_replay")
    output = replay.report()
    assert output["real_chinese_model_accuracy"] is None
    assert output["effective_answer_audio_ms"] is None
    assert output["summary"]["off"] == output["summary"]["shadow"]
    enabled = output["summary"]["enabled"]
    assert enabled["false_cuts"] == 1
    assert enabled["pause_opportunities"] == 5
    assert enabled["missed_1200ms"] == 1
    assert enabled["endpoint_p95_ms"] == 1800


def make_manifest(tmp_path, **overrides):
    import hashlib
    import json
    import wave
    pcm = PCM * 20
    with wave.open(str(tmp_path / "synthetic.wav"), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(pcm)
    case = {"audio": "synthetic.wav", "audio_sha256": hashlib.sha256((tmp_path / "synthetic.wav").read_bytes()).hexdigest(),
            "speech_ms": [1200], "pause_ms": []}
    case.update(overrides)
    data = {"provenance": "synthetic", "language": "zh", "cases": [case]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_public_wav_replay_uses_measured_cpu_score_and_annotated_audio(monkeypatch, tmp_path):
    replay = load_script(monkeypatch, "voice_turn_end_replay")
    detector = Detector()
    result = replay.public_report(make_manifest(tmp_path), detector)
    assert len(result["rows"]) == 3
    assert result["rows"][-1]["endpoint_latency_ms"] == 420
    assert result["rows"][-1]["measured_model_p50_ms"] is not None
    assert result["effective_answer_audio_ms"] is None
    assert detector.calls and detector.calls[-1].startswith(PCM)


@pytest.mark.parametrize("overrides,reason", [
    ({"audio": "../other.wav"}, "outside_manifest"),
    ({"audio_sha256": "wrong"}, "hash_mismatch"),
    ({"speech_ms": [1250]}, "invalid_frame_labels"),
    ({"speech_ms": [1800]}, "shorter_than_labels"),
])
def test_public_replay_rejects_wrong_resource_or_labels(monkeypatch, tmp_path, overrides, reason):
    replay = load_script(monkeypatch, "voice_turn_end_replay")
    with pytest.raises(ValueError, match=reason):
        replay.load_public_manifest(make_manifest(tmp_path, **overrides))


def test_manifest_hash_covers_full_wave_file_not_only_pcm(monkeypatch, tmp_path):
    import hashlib
    replay = load_script(monkeypatch, "voice_turn_end_replay")
    path = make_manifest(tmp_path, audio_sha256=hashlib.sha256(PCM * 20).hexdigest())
    with pytest.raises(ValueError, match="hash_mismatch"):
        replay.load_public_manifest(path)


def test_replay_cli_refuses_existing_report_without_model_start(tmp_path):
    import subprocess
    target = tmp_path / "keep.json"
    target.write_text("original", encoding="utf-8")
    result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "voice_turn_end_replay.py"),
                             "--output", str(target)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    assert result.returncode == 2
    assert b"already exists" in result.stderr
    assert target.read_text(encoding="utf-8") == "original"


def test_model_preprocessing_is_pcm16le_tail_eight_seconds_and_left_padding(monkeypatch):
    import numpy as np
    model_module = load_script(monkeypatch, "voice_turn_end_model")
    model = object.__new__(model_module.SmartTurnCPU)
    model.np = np
    captured = []
    def extractor(audio, **kwargs):
        captured.append((audio, kwargs))
        return SimpleNamespace(input_features=np.zeros((1, 80, 800), dtype=np.float32))
    model.extractor = extractor
    class Session:
        def run(self, requested, feeds):
            assert feeds["input_features"].shape == (1, 80, 800)
            return [np.array([[0.9]])]
    model.session = Session()
    assert model.predict(b"\x00\x80\xff\x7f") == pytest.approx(0.9)
    audio, kwargs = captured[-1]
    assert len(audio) == 128000
    assert np.all(audio[:-2] == 0)
    assert audio[-2] == -1
    assert audio[-1] == pytest.approx(32767 / 32768)
    assert kwargs["do_normalize"] is True
    model.predict(b"\x01\x00" * 128000 + b"\x02\x00" * 128000)
    assert np.all(captured[-1][0] == 2 / 32768)


def test_model_rejects_wrong_size_and_hash_before_importing_runtime(monkeypatch, tmp_path):
    model_module = load_script(monkeypatch, "voice_turn_end_model")
    path = tmp_path / "invalid.onnx"
    path.write_bytes(b"not a model")
    with pytest.raises(ValueError, match="size_mismatch"):
        model_module.SmartTurnCPU(path)
    monkeypatch.setattr(model_module, "MODEL_SIZE", path.stat().st_size)
    with pytest.raises(ValueError, match="hash_mismatch"):
        model_module.SmartTurnCPU(path)
