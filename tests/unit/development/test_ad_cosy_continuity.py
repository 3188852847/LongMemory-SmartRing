"""AD的CPU供给回放、缓冲和取消边界；不访问模型、声线或日用服务。"""

import threading
import time
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/development/xiaozhi"))
from cosyvoice_streaming import AdaptivePCMBuffer, PlaybackTimeline, CosyVoicePacket, _SpeechCancelled
from voice_latency import (VoiceLatencyTracker, _observe_components, observed_audio_sender,
                           observed_cosy_packet_sender, install_audio_send_observer)


def test_synthetic_timeline_quantifies_first_answer_duration_and_all_gaps():
    now = [0.0]
    timeline = PlaybackTimeline(clock=lambda: now[0])
    now[0] = .8
    for _ in range(16):
        timeline.packet()
    now[0] = 4.8
    for _ in range(32):
        timeline.packet()
    now[0] = 8
    timeline.packet()
    timeline.packet()
    result = timeline.snapshot()
    assert result["first_effective_packet_ms"] == 800
    assert result["playable_ms"] == 3000
    assert result["max_underflow_ms"] == pytest.approx(3040)
    assert result["total_underflow_ms"] == pytest.approx(4320)
    assert result["underflow_count"] == 2
    assert result["estimated_end_ms"] == pytest.approx(8120)
    assert result["measurement"] == "estimated_opus_supply"


@pytest.mark.parametrize("length", [0, 2, 2878, 2880, 2882, 17002])
def test_short_eos_and_arbitrary_pcm_boundaries_preserve_every_sample(length):
    pcm = b"\x02\x01" * (length // 2)
    def source(_cancelled):
        for offset in range(0, len(pcm), 334):
            yield pcm[offset:offset + 334]
    timeline = PlaybackTimeline()
    buffer = AdaptivePCMBuffer(source, 24000, lambda: False, timeline)
    try:
        pieces = list(buffer)
    finally:
        buffer.close()
    assert b"".join(pieces) == pcm
    assert all(0 < len(piece) <= 2880 for piece in pieces)
    assert all(len(piece) == 2880 for piece in pieces[:-1])
    assert buffer.snapshot()["reader_stopped"]
    assert buffer.snapshot()["received_audio_ms"] == pytest.approx(length / 48)


def test_initial_buffer_waits_for_audio_inventory_and_eos_unblocks_short_tail():
    release, first = threading.Event(), threading.Event()
    delivered = []
    def source(cancelled):
        yield b"\0" * 2880
        first.set()
        while not release.wait(.005):
            if cancelled():
                return
        yield b"\1" * 2880
    buffer = AdaptivePCMBuffer(source, 24000, lambda: False, PlaybackTimeline())
    consumer = threading.Thread(target=lambda: delivered.extend(buffer))
    consumer.start()
    try:
        assert first.wait(1)
        assert delivered == []
        release.set()
        consumer.join(1)
        assert not consumer.is_alive()
        assert delivered == [b"\0" * 2880, b"\1" * 2880]
    finally:
        release.set()
        buffer.close()
        consumer.join(1)


@pytest.mark.parametrize("stage", ["initial", "after_audio", "backpressure"])
def test_cancel_discards_only_own_queue_and_joins_reader(stage):
    cancelled, reached = threading.Event(), threading.Event()
    delivered, errors = [], []
    def source(stop):
        yield b"\0" * (2880 * (100 if stage == "backpressure" else 1))
        reached.set()
        while not stop():
            time.sleep(.002)
    timeline = PlaybackTimeline(clock=(lambda: 0.0) if stage == "backpressure" else time.perf_counter)
    buffer = AdaptivePCMBuffer(source, 24000, cancelled.is_set, timeline,
                               initial_ms=60 if stage != "initial" else 360)
    def consume():
        try:
            for pcm in buffer:
                delivered.append(pcm)
                timeline.packet()
                if stage == "after_audio":
                    reached.set()
                    cancelled.set()
        except _SpeechCancelled:
            errors.append("cancelled")
    consumer = threading.Thread(target=consume)
    consumer.start()
    try:
        if stage == "backpressure":
            # 消费端最多向下游提前3s，预取队列另有3s上限；不会无限抢读。
            deadline = time.monotonic() + 2
            while buffer.peak_frames < buffer.capacity and time.monotonic() < deadline:
                time.sleep(.002)
            assert buffer.peak_frames == buffer.capacity
        else:
            assert reached.wait(1)
        cancelled.set()
        consumer.join(1)
        assert not consumer.is_alive()
        assert errors == ["cancelled"]
        assert len(delivered) <= 50
        if stage == "initial":
            assert delivered == []
    finally:
        cancelled.set()
        buffer.close()
        consumer.join(1)
    assert buffer.snapshot()["reader_stopped"]
    assert not buffer.queue


def test_upstream_failure_discards_unplayed_pcm_and_is_never_normal_eos():
    closed = []
    def source(_cancelled):
        try:
            yield b"\0" * 2880
            raise EOFError("missing explicit EOS")
        finally:
            closed.append(True)
    buffer = AdaptivePCMBuffer(source, 24000, lambda: False, PlaybackTimeline())
    delivered = []
    try:
        with pytest.raises(EOFError):
            for pcm in buffer:
                delivered.append(pcm)
    finally:
        buffer.close()
    assert not delivered and closed == [True]


def test_underflow_rebuffers_with_bounded_increase_and_carries_playout_between_segments():
    now = [0.0]
    timeline = PlaybackTimeline(clock=lambda: now[0])
    next_chunk, waiting = threading.Event(), threading.Event()
    def source(stop):
        yield b"\0" * 2880
        waiting.set()
        while not next_chunk.wait(.002):
            if stop():
                return
        yield b"\1" * (2880 * 5)
    buffer = AdaptivePCMBuffer(source, 24000, lambda: False, timeline, initial_ms=60)
    iterator = iter(buffer)
    try:
        assert len(next(iterator)) == 2880
        timeline.packet()
        assert waiting.wait(1)
        now[0] = .2
        # producer晚到；消费端识别库存用完后增加恢复阈值到240ms。
        resumed = []
        consumer = threading.Thread(target=lambda: resumed.append(next(iterator)))
        consumer.start()
        deadline = time.monotonic() + 1
        while buffer.rebuffers == 0 and time.monotonic() < deadline:
            time.sleep(.002)
        assert buffer.rebuffers == 1
        assert buffer.target_ms == 240
        next_chunk.set()
        consumer.join(1)
        assert not consumer.is_alive() and resumed
        timeline.packet()
        for _ in iterator:
            timeline.packet()
        assert timeline.snapshot()["max_underflow_ms"] == pytest.approx(140)
        assert timeline.ahead_ms() == pytest.approx(300)
    finally:
        next_chunk.set()
        iterator.close()
        buffer.close()


def test_continuity_telemetry_rejects_stale_round_and_keeps_device_v6_unchanged():
    connection = SimpleNamespace(sentence_id="previous", config={},
        logger=SimpleNamespace(bind=lambda **_: SimpleNamespace(info=lambda _: None)))
    tracker = VoiceLatencyTracker(connection)
    tracker.begin()
    tracker.bind_sentence("current")
    tracker.record_continuity({"outcome": "completed", "text": "must never persist",
                              "max_underflow_ms": 20}, sentence_id="current")
    tracker.record_continuity({"outcome": "cancelled"}, sentence_id="previous")
    assert tracker.continuity_snapshot()["segments"] == [{"outcome": "completed", "max_underflow_ms": 20}]
    assert "continuity" not in tracker.snapshot()
    assert tracker.snapshot()["version"] == 6
    tracker.begin()
    assert tracker.continuity_snapshot()["segments"] == []


@pytest.mark.parametrize("args", [{"initial_ms": 0}, {"initial_ms": True},
    {"initial_ms": 901}, {"maximum_ms": 900}, {"maximum_ms": 6001}])
def test_policy_validation_is_bounded(args):
    with pytest.raises(ValueError):
        AdaptivePCMBuffer(lambda _: iter(()), 24000, lambda: False, PlaybackTimeline(), **args)


def test_packet_identity_survives_handoff_race_without_marking_new_answer_ready():
    mutable = ["old"]
    packet = CosyVoicePacket(b"old-frame", "old", lambda: mutable[0] != "old")
    delivered = []
    connection = SimpleNamespace(sentence_id="old", config={}, tts=SimpleNamespace(
        current_sentence_id="old", handle_opus=delivered.append),
        logger=SimpleNamespace(bind=lambda **_: SimpleNamespace(info=lambda _: None)))
    connection._longmemory_voice_latency = VoiceLatencyTracker(connection)
    connection._longmemory_voice_latency.begin()
    connection._longmemory_voice_latency.bind_sentence("new")
    _observe_components(connection)
    mutable[0] = connection.sentence_id = connection.tts.current_sentence_id = "new"
    connection.tts.handle_opus(packet)
    assert packet._longmemory_cosy_sentence_id == "old"
    assert not delivered
    assert connection._longmemory_voice_latency.snapshot()["timings_ms"]["audio_ready_ms"] is None
    connection.tts.handle_opus(b"new-frame")
    assert delivered == [b"new-frame"]


def test_final_sender_drops_old_identity_but_keeps_current_packet_in_same_batch():
    import asyncio
    forwarded = []
    async def original(_conn, _type, audios, _text, _sentence_id):
        forwarded.append(audios)
    sender = observed_audio_sender(original)
    old = CosyVoicePacket(b"old", "old", lambda: True)
    new = CosyVoicePacket(b"new", "new", lambda: False)
    conn = SimpleNamespace()
    asyncio.run(sender(conn, "middle", old, None, "new"))
    asyncio.run(sender(conn, "middle", [old, new], None, "new"))
    asyncio.run(sender(conn, "last", [], None, "new"))
    assert forwarded == [[new], []]


def test_packet_becoming_stale_in_rate_queue_is_checked_at_final_send_boundary():
    import asyncio
    forwarded = []
    state = [True]
    packet = CosyVoicePacket(b"old", "old", lambda: not state[0])
    async def original(_conn, value, _flow):
        forwarded.append(value)
    final = observed_cosy_packet_sender(original)
    # 出流控队列之前已开始新轮；client_abort也许已经复位，包身份仍永久过期。
    state[0] = False
    asyncio.run(final(SimpleNamespace(client_abort=False), packet, {}))
    asyncio.run(final(SimpleNamespace(client_abort=False), b"new", {}))
    assert forwarded == [b"new"]


def test_install_observer_guards_actual_packet_hook_once_and_preserves_other_audio(monkeypatch):
    import asyncio
    import types
    forwarded = []
    async def send_message(*_args):
        pass
    async def send_packet(_conn, packet, _flow):
        forwarded.append(packet)
    base = SimpleNamespace(sendAudioMessage=send_message)
    send_module = SimpleNamespace(_do_send_audio=send_packet)
    providers = types.ModuleType("core.providers.tts")
    providers.base = base
    handle = types.ModuleType("core.handle")
    handle.sendAudioHandle = send_module
    monkeypatch.setitem(sys.modules, "core.providers.tts", providers)
    monkeypatch.setitem(sys.modules, "core.handle", handle)
    install_audio_send_observer()
    wrapped = send_module._do_send_audio
    install_audio_send_observer()
    assert send_module._do_send_audio is wrapped
    asyncio.run(wrapped(SimpleNamespace(), CosyVoicePacket(b"old", "old", lambda: True), {}))
    asyncio.run(wrapped(SimpleNamespace(), b"other-engine-packet", {}))
    assert forwarded == [b"other-engine-packet"]
