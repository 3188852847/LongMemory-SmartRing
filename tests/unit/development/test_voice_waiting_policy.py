"""等待提示静默/冷却/并发与完整观测包装；合成缓存、包和时钟，不启动模型。"""

import asyncio
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS

import pytest

from test_voice_waiting_cache import connection
import voice_waiting as w
import voice_latency as latency
import voice_interruption as guard

ROOT = Path(__file__).resolve().parents[3]


def next_round(c, now, at, name):
    now[0] = at
    old = getattr(c, "_longmemory_waiting", None)
    if old is not None:
        old.cancel()
    c._longmemory_voice_latency.begin()
    c.sentence_id = name
    c._longmemory_voice_latency.bind_sentence()
    w.begin_waiting(c, None)
    return c._longmemory_waiting


def sender_module(sent):
    async def send(conn, packet, flow):
        sent.append(bytes(packet))
        w.record_packet_sent(packet)
        flow["packet_count"] = flow.get("packet_count", 0) + 1
    module = NS(_do_send_audio=send)
    w.install_waiting_sender(module)
    return module


def test_three_seconds_silent_then_one_enqueue_despite_concurrent_timer_calls(monkeypatch, tmp_path):
    c, now = connection(monkeypatch, tmp_path)
    w.begin_waiting(c, None)
    state = c._longmemory_waiting
    assert state.timer.delay == 3.0
    for at in (.9, 2.999):
        now[0] = at
        state.enqueue()
        assert c.tts.tts_audio_queue.empty()
    now[0] = 3.0
    threads = [threading.Thread(target=state.enqueue) for _ in range(8)]
    for thread in threads: thread.start()
    for thread in threads:
        thread.join(1)
        assert not thread.is_alive()
    assert c.tts.tts_audio_queue.qsize() == 1
    assert state.budget.last_sent_at is None  # 入队没有消费冷却。
    state.enqueue()
    assert c.tts.tts_audio_queue.qsize() == 1


def test_cooldown_is_ninety_seconds_from_successful_first_send_across_rounds(monkeypatch, tmp_path):
    c, now = connection(monkeypatch, tmp_path)
    state = next_round(c, now, 0, "first")
    now[0] = 3
    state.enqueue()
    sent = []
    module = sender_module(sent)
    packets = c.tts.tts_audio_queue.get_nowait()[1]
    asyncio.run(module._do_send_audio(c, packets[0], {}))
    assert state.first_feedback_ms == 3000 and state.budget.last_sent_at == 3
    # 同一条提示的尾帧可以继续；不再改写首包的冷却起点。
    now[0] = 3.06
    asyncio.run(module._do_send_audio(c, w.WaitingPacket(b"tail", state), {}))
    assert state.budget.last_sent_at == 3
    second = next_round(c, now, 10, "second")
    now[0] = 13
    second.enqueue()
    assert second.cue_state == "skipped" and c.tts.tts_audio_queue.empty()
    now[0] = 92.999
    assert not second.budget.eligible(second)
    now[0] = 93
    assert second.budget.eligible(second)
    third = next_round(c, now, 93, "third")
    now[0] = 96
    third.enqueue()
    assert c.tts.tts_audio_queue.qsize() == 1
    # 冷却属于连接，不能成为全局限额。
    other, other_now = connection(monkeypatch, tmp_path / "other")
    w.begin_waiting(other, None)
    other_now[0] = 3
    other._longmemory_waiting.enqueue()
    assert other.tts.tts_audio_queue.qsize() == 1


@pytest.mark.parametrize("reason", ["answer", "cancel", "old_round", "send_noop", "send_error", "other_packet_increased_count"])
def test_unsent_or_cancelled_cue_does_not_consume_next_round_budget(monkeypatch, tmp_path, reason):
    c, now = connection(monkeypatch, tmp_path)
    state = next_round(c, now, 0, "first")
    now[0] = 3
    state.enqueue()
    packet = c.tts.tts_audio_queue.get_nowait()[1][0]
    sent = []
    module = sender_module(sent)
    if reason == "answer": w.mark_answer_ready(c)
    elif reason == "cancel": state.cancel()
    elif reason == "old_round": c.sentence_id = "other"
    else:
        async def no_send(conn, packet, flow):
            if reason == "send_error": raise RuntimeError("synthetic_send_failure")
            if reason == "other_packet_increased_count":
                flow["packet_count"] = flow.get("packet_count", 0) + 1
        module = NS(_do_send_audio=no_send)
        w.install_waiting_sender(module)
    if reason == "send_error":
        with pytest.raises(RuntimeError, match="synthetic_send_failure"):
            asyncio.run(module._do_send_audio(c, packet, {}))
    else:
        asyncio.run(module._do_send_audio(c, packet, {}))
    assert state.budget.last_sent_at is None and state.budget.inflight is None
    newer = next_round(c, now, 4, "next")
    now[0] = 7
    newer.enqueue()
    assert c.tts.tts_audio_queue.qsize() == 1


@pytest.mark.parametrize("actually_sent", [False, True])
def test_cancelled_inflight_cue_consumes_only_confirmed_send_and_keeps_new_reservation(monkeypatch, tmp_path, actually_sent):
    c, now = connection(monkeypatch, tmp_path)
    async def run():
        old = next_round(c, now, 0, "old")
        now[0] = 3
        entered, release = asyncio.Event(), asyncio.Event()
        async def send(conn, packet, flow):
            if bytes(packet) == b"old":
                entered.set()
                await release.wait()
                if actually_sent:
                    w.record_packet_sent(packet)
                return
            w.record_packet_sent(packet)
            flow["packet_count"] = flow.get("packet_count", 0) + 1
        module = NS(_do_send_audio=send)
        w.install_waiting_sender(module)
        task = asyncio.create_task(module._do_send_audio(c, w.WaitingPacket(b"old", old), {}))
        await entered.wait()
        assert old.budget.last_sent_at is None
        # 并发首包预留不等于已消费；旧轮cancel必须释放自己的预留。
        new = next_round(c, now, 4, "new")
        now[0] = 7
        await module._do_send_audio(c, w.WaitingPacket(b"new", new), {})
        assert new.budget.last_sent_at == 7
        now[0] = 8
        release.set()
        await task
        assert new.budget.last_sent_at == (8 if actually_sent else 7)
        assert new.budget.last_token is (old.cue_token if actually_sent else new.cue_token)
        assert old.first_feedback_ms == (8000 if actually_sent else None)
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["cue", "answer"])
def test_guard_envelope_keeps_packet_role_bytes_and_original_cancellation(kind):
    live = [True]
    state = NS(current=lambda: True, answer_ready=False, cue_current=lambda: True)
    cls = w.WaitingPacket if kind == "cue" else w.AnswerPacket
    value = cls(b"synthetic-opus", state)
    value._longmemory_cosy_cancelled = lambda: not live[0]
    lease = NS(sentence_id="synthetic-turn", current=lambda: True)
    wrapped = guard._ControlPacket(value, lease)
    assert type(wrapped) is cls and wrapped.state is state and bytes(wrapped) == bytes(value)
    assert not wrapped._longmemory_cosy_cancelled()
    live[0] = False
    assert wrapped._longmemory_cosy_cancelled()


@pytest.mark.parametrize("kind", ["cue", "answer"])
def test_shared_counter_change_cannot_confirm_this_packet(monkeypatch, tmp_path, kind):
    c, now = connection(monkeypatch, tmp_path)
    state = next_round(c, now, 0, "current")
    now[0] = 3
    async def another_packet_changed_counter(conn, packet, flow):
        flow["packet_count"] = flow.get("packet_count", 0) + 1
        # 此包没有传输成功标记；增量来自别的并发包，不能归给当前包。
    module = NS(_do_send_audio=another_packet_changed_counter)
    w.install_waiting_sender(module)
    cls = w.WaitingPacket if kind == "cue" else w.AnswerPacket
    packet = cls(b"not-sent", state)
    asyncio.run(module._do_send_audio(c, packet, {}))
    assert packet._longmemory_send_receipt.sent_at is None
    assert state.first_feedback_ms is state.first_answer_ms is None
    assert c._longmemory_voice_latency.snapshot()["timings_ms"]["first_audio_sent_ms"] is None
    assert state.budget.last_sent_at is None


def test_packet_cancel_callback_error_fails_closed_without_weakening_original_lease():
    from voice_output_protocol import _PacketLease
    def failed():
        raise RuntimeError("synthetic_cancel_check_failure")
    assert not _PacketLease(NS(current=lambda: True), failed).current()
    called = []
    assert not _PacketLease(NS(current=lambda: False), lambda: called.append(True)).current()
    assert called == []


def test_fixed_vendor_complete_wrapper_order_marks_only_actual_answer_send(monkeypatch):
    sys.path.insert(0, str(ROOT / "tests/fixtures"))
    from voice_interruption_upstream import build
    try:
        u = build()
    except FileNotFoundError:
        pytest.skip("owner-installed fixed vendor unavailable")
    c = u.conn
    c.config = {"selected_module": {"TTS": "CustomTTS"},
        "TTS": {"CustomTTS": {"url": "http://127.0.0.1:18770/v1/audio/speech"}}}
    now = [0.0]
    monkeypatch.setattr(w, "time", NS(perf_counter=lambda: now[0]))
    tracker = c._longmemory_voice_latency = latency.VoiceLatencyTracker(c, clock=lambda: now[0])
    tracker.begin()
    c.sentence_id = c.tts.current_sentence_id = "synthetic-current"
    tracker.bind_sentence()
    state = c._longmemory_waiting = w.WaitingTurn(c, "model", packets=(b"cue",))
    u.ttsbase.sendAudioMessage = latency.observed_audio_sender(u.ttsbase.sendAudioMessage)
    u.send._do_send_audio = latency.observed_cosy_packet_sender(u.send._do_send_audio)
    w.install_waiting_sender(u.send)
    guard.install_voice_interruption(u.Connection, u.receive, u.asr, u.send, tts_base_module=u.ttsbase)
    kinds = []
    original = c.websocket.send
    async def socket(value):
        if isinstance(value, bytes): kinds.append(type(value).__name__)
        result = await original(value)
        if isinstance(value, bytes): w.record_packet_sent(value)
        return result
    c.websocket.send = socket
    async def run():
        now[0] = 3
        await u.ttsbase.sendAudioMessage(c, "middle", w.WaitingPacket(b"cue", state), None, c.sentence_id)
        assert tracker.snapshot()["timings_ms"]["first_audio_sent_ms"] is None
        assert state.first_feedback_ms == 3000
        now[0] = 3.3
        w.mark_answer_ready(c)
        await u.ttsbase.sendAudioMessage(c, "middle", w.WaitingPacket(b"cue-tail", state), None, c.sentence_id)
        await u.ttsbase.sendAudioMessage(c, "middle", w.AnswerPacket(b"answer", state), None, c.sentence_id)
        assert kinds == ["WaitingPacket", "AnswerPacket"]
        assert tracker.snapshot()["timings_ms"]["first_audio_sent_ms"] == 3300
        assert state.first_answer_ms == 3300
        assert guard.snapshot(c)["counts"]["cue_send_returned"] == 1
        assert guard.snapshot(c)["counts"]["answer_send_returned"] == 1
        c.audio_rate_controller.stop_sending()
        await asyncio.gather(c.audio_rate_controller.pending_send_task, return_exceptions=True)
    asyncio.run(run())
