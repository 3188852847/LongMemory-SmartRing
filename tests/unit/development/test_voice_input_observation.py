"""固定上游输入方法 + 合成队列/结果；不连接服务或加载声学模型。"""

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts/development/xiaozhi"


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    observer = importlib.import_module("voice_input_observation")
    probe = importlib.import_module("voice_input_interruption_probe")
    assert Path(observer.__file__).resolve() == SCRIPTS / "voice_input_observation.py"
    return observer, probe


def install(observer, h):
    base_cls = h.upstream.ASRProviderBase
    async def unused_formal(provider, connection, frames):
        return None
    async def open_audio(provider, connection):
        assert isinstance(connection.asr_audio_queue, observer._ObservedQueue)
        h.counts["open_with_observed_queue"] += 1
    base_cls.handle_voice_stop = unused_formal
    base_cls.open_audio_channels = open_audio
    base = SimpleNamespace(ASRProviderBase=base_cls, handleAudioMessage=h.upstream.handleAudioMessage)
    result = observer.install_voice_input_observation(type(h.connection), base, h.upstream,
                                                       asr_provider_classes=(type(h.provider),))
    return base, result


def test_import_and_getter_do_not_create_state_or_patch_connection(modules):
    observer, _ = modules
    connection = SimpleNamespace()
    value = observer.voice_input_observation_snapshot(connection)
    assert value["state"] == "not_observed" and value["counts"] is None
    assert observer.voice_input_observation_snapshot(None)["state"] == "no_connection"
    assert connection.__dict__ == {}


def test_route_queue_vad_receive_observed_while_playing_without_content(modules):
    observer, probe = modules
    async def run():
        h = probe.harness(speaking=True, aec=False)
        original_queue = h.connection.asr_audio_queue
        base, coverage = install(observer, h)
        await h.provider.open_audio_channels(h.connection)
        try:
            assert coverage["queue_before_worker"]
            assert h.connection.asr_audio_queue.original is original_queue
            await h.connection._route_message(b"never-export-packet")
            frame = h.connection.asr_audio_queue.get_nowait()
            assert frame is probe.PCM
            await base.handleAudioMessage(h.connection, frame)
            value = observer.voice_input_observation_snapshot(h.connection)
            assert [value["counts"][key] for key in ("route_begin", "route_return", "queue_put", "queue_get", "vad_check", "vad_speech", "receive_begin")] == [1] * 7
            assert not any(value["inflight"].values())
            assert value["last_handle_flags"]["client_is_speaking"] is True
            assert "never-export" not in json.dumps(value)
            assert "session_id" not in json.dumps(value)
        finally:
            await probe.stop(h)
    asyncio.run(run())


def test_wakeup_drop_is_counted_after_vad_but_not_mislabelled_as_empty_asr(modules):
    observer, probe = modules
    async def run():
        h = probe.harness(just_woken=True)
        base, _ = install(observer, h)
        try:
            await base.handleAudioMessage(h.connection, probe.PCM)
            counts = observer.voice_input_observation_snapshot(h.connection)["counts"]
            assert counts["vad_check"] == counts["just_woken_skipped"] == 1
            assert counts["receive_begin"] == counts["formal_begin"] == counts["result_empty"] == 0
        finally:
            await probe.stop(h)
    asyncio.run(run())


def test_prefetch_speaking_guard_does_not_prevent_formal_asr(modules):
    observer, probe = modules
    async def run():
        h = probe.harness(speaking=True, aec=False, prefetch=True)
        base, _ = install(observer, h)
        try:
            h.connection.asr_audio = [probe.PCM] * 20
            h.connection.client_have_voice = True
            h.connection.vad_last_voice_time = probe.time.time() * 1000 - 300
            await h.provider.receive_audio(h.connection, probe.PCM, False)
            from voice_asr_prefetch import voice_asr_prefetch_snapshot
            assert voice_asr_prefetch_snapshot(h.connection)["started"] == 0
            h.connection.client_voice_stop = True
            await h.provider.receive_audio(h.connection, probe.PCM, False)
            counts = observer.voice_input_observation_snapshot(h.connection)["counts"]
            assert counts["formal_begin"] == counts["formal_return"] == 1
            assert counts["speech_begin"] == counts["speech_return"] == counts["result_nonempty"] == 1
            assert counts["stop_without_formal"] == 0
            assert h.counts["synthetic_model_entered"] == 1
        finally:
            await probe.stop(h)
    asyncio.run(run())


@pytest.mark.parametrize("frames,formal", [(6, 0), (14, 0), (15, 1)])
def test_endpoint_without_formal_call_is_visible(modules, frames, formal):
    observer, probe = modules
    async def run():
        h = probe.harness(speaking=False)
        install(observer, h)
        try:
            h.connection.asr_audio = [probe.PCM] * frames
            h.connection.client_have_voice = h.connection.client_voice_stop = True
            await h.provider.receive_audio(h.connection, probe.PCM, False)
            value = observer.voice_input_observation_snapshot(h.connection)
            assert value["endpoint_packet_count"] == frames + 1
            assert value["endpoint_pcm_bytes"] == (frames + 1) * 1920
            assert value["buffer_frames_before_receive"] == frames
            assert value["formal_audio_frames"] == (1 if formal else None)
            assert value["formal_pcm_bytes"] == ((frames + 1) * 1920 if formal else None)
            assert value["counts"]["formal_begin"] == formal
            assert value["counts"]["stop_without_formal"] == 1 - formal
            assert value["counts"]["endpoint_length_rejected"] == 1 - formal
        finally:
            await probe.stop(h)
    asyncio.run(run())


def test_abort_wait_inflight_is_visible_before_asr_receive(modules):
    observer, probe = modules
    async def run():
        h = probe.harness(aec=True, blocked_send=True)
        base, _ = install(observer, h)
        task = asyncio.create_task(base.handleAudioMessage(h.connection, probe.PCM))
        try:
            await asyncio.wait_for(h.raw.entered.wait(), .5)
            value = observer.voice_input_observation_snapshot(h.connection)
            assert value["inflight"]["handle"] == value["inflight"]["abort"] == 1
            assert value["counts"]["receive_begin"] == 0
            assert value["counts"]["abort_begin"] == 1 and value["counts"]["abort_return"] == 0
            h.raw.release.set()
            await task
            value = observer.voice_input_observation_snapshot(h.connection)
            assert value["counts"]["abort_return"] == value["counts"]["receive_begin"] == 1
        finally:
            h.raw.release.set()
            await asyncio.gather(task, return_exceptions=True)
            await probe.stop(h)
    asyncio.run(run())


def test_formal_wait_is_distinguished_from_no_input_and_no_implicit_timeout_added(modules):
    observer, probe = modules
    async def run():
        h = probe.harness(blocked_model=True, aec=False)
        install(observer, h)
        h.connection.asr_audio = [probe.PCM] * 16
        h.connection.client_have_voice = h.connection.client_voice_stop = True
        task = asyncio.create_task(h.provider.receive_audio(h.connection, probe.PCM, False))
        try:
            await probe.until(h.provider.model.entered.is_set)
            value = observer.voice_input_observation_snapshot(h.connection)
            assert value["inflight"]["formal"] == value["inflight"]["speech"] == 1
            assert value["counts"]["formal_timeout"] == value["counts"]["speech_timeout"] == 0
            assert not task.done()
        finally:
            h.provider.model.release.set()
            await task
            await probe.stop(h)
    asyncio.run(run())


def test_empty_result_is_only_classified_not_stored_or_replaced(modules):
    observer, probe = modules
    async def run():
        h = probe.harness()
        async def empty(provider, *args, **kwargs):
            return "", None
        type(h.provider).speech_to_text = empty
        install(observer, h)
        try:
            h.connection.asr_audio = [probe.PCM] * 16
            h.connection.client_have_voice = h.connection.client_voice_stop = True
            await h.provider.receive_audio(h.connection, probe.PCM, False)
            counts = observer.voice_input_observation_snapshot(h.connection)["counts"]
            assert counts["result_empty"] == 1 and counts["result_nonempty"] == 0
            assert counts["formal_return"] == 1
        finally:
            await probe.stop(h)
    asyncio.run(run())


def test_fixed_counts_saturate_and_repeat_install_does_not_wrap_twice(modules):
    observer, probe = modules
    async def run():
        h = probe.harness()
        base, _ = install(observer, h)
        observer.install_voice_input_observation(type(h.connection), base, h.upstream,
                                                asr_provider_classes=(type(h.provider),))
        await h.connection._route_message(b"synthetic")
        state = getattr(h.connection, observer.STATE)
        state.counts["queue_put"] = observer.LIMIT
        h.connection.asr_audio_queue.put_nowait(probe.PCM)
        value = observer.voice_input_observation_snapshot(h.connection)
        assert value["counter_saturated"] and value["counts"]["queue_put"] == observer.LIMIT
        assert value["counts"]["route_begin"] == 1
        await probe.stop(h)
        assert observer.voice_input_observation_snapshot(h.connection)["state"] == "closed"
    asyncio.run(run())


def test_manual_noise_or_stream_not_misclassified_as_length_rejection(modules):
    observer, probe = modules
    async def run():
        for mode in ("manual", "noise", "stream"):
            h = probe.harness()
            install(observer, h)
            h.connection.client_voice_stop = True
            if mode == "manual":
                h.connection.client_listen_mode = "manual"
            elif mode == "stream":
                h.connection.client_have_voice = True
                h.provider.interface_type = probe.InterfaceType.STREAM
            await h.provider.receive_audio(h.connection, probe.PCM, False)
            value = observer.voice_input_observation_snapshot(h.connection)
            assert value["counts"]["endpoint_length_rejected"] == 0
            assert value["endpoint_packet_count"] is None and value["endpoint_pcm_bytes"] is None
            await probe.stop(h)
    asyncio.run(run())


def test_observer_bookkeeping_fault_does_not_break_put_or_getter(modules):
    observer, probe = modules
    async def run():
        h = probe.harness()
        install(observer, h)
        await h.connection._route_message(b"first")
        state = getattr(h.connection, observer.STATE)
        state.counts = None
        await h.connection._route_message(b"second")
        assert h.connection.asr_audio_queue.qsize() == 2
        result = observer.voice_input_observation_snapshot(h.connection)
        assert result["state"] == "unavailable" and result["counts"] is None
        await probe.stop(h)
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["timeout", "async_timeout", "cancel"])
def test_original_exception_and_cancellation_are_preserved(modules, kind):
    observer, probe = modules
    async def run():
        h = probe.harness()
        expected = (TimeoutError("synthetic") if kind == "timeout" else
                    asyncio.TimeoutError("synthetic") if kind == "async_timeout" else asyncio.CancelledError())
        async def fail(provider, *args, **kwargs):
            raise expected
        type(h.provider).speech_to_text = fail
        install(observer, h)
        h.connection.asr_audio = [probe.PCM] * 16
        h.connection.client_have_voice = h.connection.client_voice_stop = True
        try:
            with pytest.raises(type(expected)) as info:
                await h.provider.receive_audio(h.connection, probe.PCM, False)
            assert info.value is expected
            result = observer.voice_input_observation_snapshot(h.connection)
            assert result["counts"]["speech_" + ("timeout" if kind == "async_timeout" else kind)] == 1
            assert not any(result["inflight"].values())
        finally:
            await probe.stop(h)
    asyncio.run(run())
