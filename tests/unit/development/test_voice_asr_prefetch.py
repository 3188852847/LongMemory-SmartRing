"""用合成 PCM 和可控模型线程验证预识别的提交边界及取消竞争。"""

import asyncio
import importlib.util
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/voice_asr_prefetch.py"
SPEC = importlib.util.spec_from_file_location("voice_asr_prefetch_test", SCRIPT)
prefetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prefetch)
PCM = b"\x11\x00" * 960


def harness(monkeypatch, *, blocked=False, first_result="candidate", enabled=True):
    monkeypatch.setattr(prefetch.time, "time", lambda: 100.0)

    class Model:
        kwargs = {}

        def __init__(self):
            self.calls = []
            self.entered = threading.Event()
            self.release = threading.Event()
            self.active = 0
            self.peak_active = 0

        def generate(self, **kwargs):
            self.calls.append(kwargs["input"])
            number = len(self.calls)
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
            try:
                if number == 1:
                    self.entered.set()
                    if blocked:
                        assert self.release.wait(5), "test did not release model"
                    if isinstance(first_result, Exception):
                        raise first_result
                    return [{"text": first_result}]
                return [{"text": "complete"}]
            finally:
                self.active -= 1

    class Connection:
        def __init__(self):
            self.asr_audio = []
            self.client_listen_mode = "auto"
            self.voiceprint_provider = None
            self.stop_event = threading.Event()
            self.client_voice_stop = False
            self.client_have_voice = True
            self.client_is_speaking = False
            self.vad_last_voice_time = 99_700
            self.session_id = "synthetic-session"
            self.submitted = []

        def reset_audio_states(self):
            self.asr_audio.clear()
            self.client_have_voice = False
            self.client_voice_stop = False
            self.vad_last_voice_time = 0

        async def close(self):
            self.stop_event.set()
            self.reset_audio_states()

    def clean(text):
        return {"content": text, "language": "zh", "emotion": "neutral"}

    class Provider:
        model_dir = "models/SenseVoiceSmall"
        interface_type = SimpleNamespace(value="LOCAL")
        delete_audio_file = True
        language = "zh"

        def __init__(self, model):
            self.model = model

        async def receive_audio(self, connection, pcm, have_voice):
            connection.asr_audio.append(pcm)
            if connection.client_voice_stop:
                audio = b"".join(connection.asr_audio)
                if len(audio) > 1920 * 15:
                    await self.handle_voice_stop(connection, [audio])
                connection.reset_audio_states()

        async def handle_voice_stop(self, connection, audio):
            artifacts = SimpleNamespace(pcm_bytes=b"".join(audio), file_path=None)
            result, _ = await self.speech_to_text(audio, connection.session_id, artifacts)
            if isinstance(result, dict) and result.get("content"):
                connection.submitted.append(result)

        async def speech_to_text(self, pcm, session_id, artifacts=None):
            result = await asyncio.to_thread(
                self.model.generate, input=artifacts.pcm_bytes, cache={},
                language=self.language, use_itn=True, batch_size_s=60,
            )
            return clean(result[0]["text"]), artifacts.file_path

    module = SimpleNamespace(ASRProvider=Provider, lang_tag_filter=clean)
    original = (Provider.receive_audio, Provider.handle_voice_stop, Provider.speech_to_text,
                Connection.reset_audio_states, Connection.close)
    installed = prefetch.install_voice_asr_prefetch(Connection, module, enabled=enabled)
    model = Model()
    return SimpleNamespace(provider=Provider(model), model=model, connection=Connection(),
                           Provider=Provider, Connection=Connection, module=module,
                           original=original, installed=installed)


async def begin_candidate(h):
    for _ in range(16):
        await h.provider.receive_audio(h.connection, PCM, True)
    await h.provider.receive_audio(h.connection, PCM, False)
    state = getattr(h.connection, prefetch._STATE, None)
    return state.ticket if state else None


async def endpoint(h):
    h.connection.client_voice_stop = True
    await h.provider.receive_audio(h.connection, PCM, False)


def test_disabled_installer_leaves_upstream_untouched(monkeypatch):
    h = harness(monkeypatch, enabled=False)
    assert h.installed == {"enabled": False, "installed": False}
    assert h.original == (h.Provider.receive_audio, h.Provider.handle_voice_stop,
                          h.Provider.speech_to_text, h.Connection.reset_audio_states, h.Connection.close)
    assert prefetch.voice_asr_prefetch_snapshot(h.connection) == {"version": 1, "enabled": False}


def test_installed_connection_reports_enabled_before_any_audio(monkeypatch):
    h = harness(monkeypatch)
    snapshot = h.connection._longmemory_asr_prefetch_snapshot()
    assert snapshot["enabled"] is True
    assert snapshot["started"] == 0
    assert snapshot["latest_status"] == "idle"
    assert not hasattr(h.connection, prefetch._STATE)


def test_candidate_never_submits_until_formal_endpoint_and_reuses_quiet_tail(monkeypatch):
    h = harness(monkeypatch)

    async def run():
        ticket = await begin_candidate(h)
        await ticket.task
        assert h.connection.submitted == []
        assert ticket.pcm == b""
        # 正式音频多出静音帧，不能用完整音频 hash 误判成另一句话。
        await endpoint(h)

    asyncio.run(run())
    assert len(h.model.calls) == 1
    assert h.connection.submitted == [{"content": "candidate", "language": "zh", "emotion": "neutral"}]
    snapshot = prefetch.voice_asr_prefetch_snapshot(h.connection)
    assert snapshot["reused"] == 1
    assert snapshot["latest_status"] == "reused"
    assert snapshot["latest_overlap_ms"] >= 0
    assert all(item not in repr(snapshot) for item in ("candidate", "synthetic-session", "digest", "pcm"))


def test_formal_endpoint_awaits_the_same_running_job_without_duplicate_inference(monkeypatch):
    h = harness(monkeypatch, blocked=True)

    async def run():
        ticket = await begin_candidate(h)
        assert await asyncio.to_thread(h.model.entered.wait, 2)
        formal = asyncio.create_task(endpoint(h))
        await asyncio.sleep(0.01)
        assert h.connection.submitted == []
        assert len(h.model.calls) == 1
        h.model.release.set()
        await formal
        assert ticket.task.done()

    asyncio.run(run())
    assert len(h.model.calls) == 1
    assert len(h.connection.submitted) == 1


def test_resumed_speech_discards_candidate_and_serializes_actual_model_work(monkeypatch):
    h = harness(monkeypatch, blocked=True)

    async def run():
        ticket = await begin_candidate(h)
        assert await asyncio.to_thread(h.model.entered.wait, 2)
        h.connection.vad_last_voice_time += 100
        await h.provider.receive_audio(h.connection, PCM, True)
        assert not ticket.valid.is_set()
        assert not ticket.task.cancelled()
        formal = asyncio.create_task(endpoint(h))
        await asyncio.sleep(0.02)
        assert len(h.model.calls) == 1
        assert not formal.done()
        h.model.release.set()
        await formal
        await ticket.task

    asyncio.run(run())
    assert len(h.model.calls) == 2
    assert h.model.peak_active == 1
    assert h.connection.submitted[0]["content"] == "complete"
    assert prefetch.voice_asr_prefetch_snapshot(h.connection)["invalidated"] == 1


@pytest.mark.parametrize("lifecycle", ["reset", "close"])
def test_reset_or_close_while_formal_waits_never_commits_old_candidate(monkeypatch, lifecycle):
    h = harness(monkeypatch, blocked=True)

    async def run():
        ticket = await begin_candidate(h)
        assert await asyncio.to_thread(h.model.entered.wait, 2)
        formal = asyncio.create_task(endpoint(h))
        await asyncio.sleep(0.01)
        if lifecycle == "reset":
            h.connection.reset_audio_states()
        else:
            await h.connection.close()
        h.model.release.set()
        await formal
        await ticket.task

    asyncio.run(run())
    assert h.connection.submitted == []
    assert len(h.model.calls) == 1


def test_cancelled_coroutine_does_not_release_lock_around_still_running_thread(monkeypatch):
    h = harness(monkeypatch, blocked=True)

    async def run():
        ticket = await begin_candidate(h)
        assert await asyncio.to_thread(h.model.entered.wait, 2)
        ticket.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await ticket.task
        h.connection.vad_last_voice_time += 100
        await h.provider.receive_audio(h.connection, PCM, True)
        formal = asyncio.create_task(endpoint(h))
        await asyncio.sleep(0.02)
        assert len(h.model.calls) == 1
        h.model.release.set()
        await formal

    asyncio.run(run())
    assert h.model.peak_active == 1
    assert h.connection.submitted[0]["content"] == "complete"


@pytest.mark.parametrize("first_result", ["", ValueError("synthetic failure")])
def test_empty_or_failed_prefetch_falls_back_to_complete_audio(monkeypatch, first_result):
    h = harness(monkeypatch, first_result=first_result)

    async def run():
        ticket = await begin_candidate(h)
        await ticket.task
        await endpoint(h)

    asyncio.run(run())
    assert len(h.model.calls) == 2
    assert h.connection.submitted[0]["content"] == "complete"
    assert prefetch.voice_asr_prefetch_snapshot(h.connection)["fallback"] == 1


def test_same_vad_timestamp_cannot_reuse_a_replaced_audio_prefix(monkeypatch):
    h = harness(monkeypatch)

    async def run():
        ticket = await begin_candidate(h)
        await ticket.task
        h.connection.asr_audio[0] = b"\x22\x00" * 960
        await endpoint(h)

    asyncio.run(run())
    assert len(h.model.calls) == 2
    assert h.connection.submitted[0]["content"] == "complete"


def test_new_voice_timestamp_invalidates_even_if_final_vad_window_returns_false(monkeypatch):
    h = harness(monkeypatch)

    async def run():
        ticket = await begin_candidate(h)
        await ticket.task
        # 一个60ms输入内前半窗口有语音，后半窗口无声：返回False仍不能复用。
        h.connection.vad_last_voice_time += 60
        await h.provider.receive_audio(h.connection, PCM, False)
        await endpoint(h)

    asyncio.run(run())
    assert h.connection.submitted[0]["content"] == "complete"
    assert len(h.model.calls) == 2


def test_positive_voice_frame_invalidates_even_if_wall_clock_stamp_is_equal(monkeypatch):
    h = harness(monkeypatch)

    async def run():
        ticket = await begin_candidate(h)
        await ticket.task
        await h.provider.receive_audio(h.connection, PCM, True)
        await endpoint(h)

    asyncio.run(run())
    assert h.connection.submitted[0]["content"] == "complete"
    assert len(h.model.calls) == 2


def test_only_one_attempt_per_utterance_after_a_false_pause(monkeypatch):
    h = harness(monkeypatch)

    async def run():
        ticket = await begin_candidate(h)
        await ticket.task
        h.connection.vad_last_voice_time += 1
        await h.provider.receive_audio(h.connection, PCM, True)
        h.connection.vad_last_voice_time -= 1
        for _ in range(10):
            await h.provider.receive_audio(h.connection, PCM, False)
        assert len(h.model.calls) == 1
        assert prefetch.voice_asr_prefetch_snapshot(h.connection)["started"] == 1

    asyncio.run(run())


def test_shared_model_busy_slot_skips_second_connection_prefetch(monkeypatch):
    h = harness(monkeypatch, blocked=True)
    second = SimpleNamespace(provider=h.Provider(h.model), connection=h.Connection())

    async def run():
        first_ticket = await begin_candidate(h)
        assert await asyncio.to_thread(h.model.entered.wait, 2)
        second_ticket = await begin_candidate(second)
        await second_ticket.task
        assert second_ticket.status == "busy"
        assert len(h.model.calls) == 1
        h.model.release.set()
        await first_ticket.task
        await endpoint(second)

    asyncio.run(run())
    assert len(h.model.calls) == 2
    assert h.model.peak_active == 1
    assert prefetch.voice_asr_prefetch_snapshot(second.connection)["skipped_busy"] == 1


def test_formal_asr_before_first_prefetch_already_owns_shared_model_lock(monkeypatch):
    h = harness(monkeypatch, blocked=True)

    async def run():
        artifacts = SimpleNamespace(pcm_bytes=PCM * 18, file_path=None)
        formal = asyncio.create_task(h.provider.speech_to_text([artifacts.pcm_bytes], "synthetic", artifacts))
        assert await asyncio.to_thread(h.model.entered.wait, 2)
        ticket = await begin_candidate(h)
        await ticket.task
        assert ticket.status == "busy"
        assert len(h.model.calls) == 1
        h.model.release.set()
        await formal

    asyncio.run(run())
    assert h.model.peak_active == 1


@pytest.mark.parametrize("condition", ["manual", "voiceprint", "other_model", "recording", "output_dir", "speaking", "too_short", "too_long", "nonstandard_pcm", "early_silence"])
def test_unsupported_or_unbounded_input_does_not_schedule_speculation(monkeypatch, condition):
    h = harness(monkeypatch)
    if condition == "manual":
        h.connection.client_listen_mode = "manual"
    elif condition == "voiceprint":
        h.connection.voiceprint_provider = object()
    elif condition == "other_model":
        h.provider.model_dir = "models/other"
    elif condition == "recording":
        h.provider.delete_audio_file = False
    elif condition == "output_dir":
        h.model.kwargs = {"output_dir": "never-created"}
    elif condition == "speaking":
        h.connection.client_is_speaking = True
    elif condition == "early_silence":
        h.connection.vad_last_voice_time = 99_900

    async def run():
        frames = 3 if condition == "too_short" else 134 if condition == "too_long" else 16
        pcm = b"\x00\x00" if condition == "nonstandard_pcm" else PCM
        for _ in range(frames):
            await h.provider.receive_audio(h.connection, pcm, True)
        await h.provider.receive_audio(h.connection, pcm, False)
        await asyncio.sleep(0)

    asyncio.run(run())
    assert h.model.calls == []
    assert h.connection.submitted == []
