"""输出撤权边界与固定上游合同；无模型、设备、私有配置或日用服务。"""

import asyncio
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/development/xiaozhi"))
import voice_interruption as guard
from voice_waiting import WaitingTurn, AnswerPacket, WaitingPacket


def connection():
    return NS(sentence_id="old", tts=NS(_longmemory_cosy_streaming_installed=True),
              client_abort=False, stop_event=threading.Event(), sample_rate=16000,
              _longmemory_cosy_delivery_mode="adaptive")


def test_revoke_is_permanent_for_producer_late_invocation_and_waiting_packets():
    conn = connection()
    waiting = conn._longmemory_waiting = WaitingTurn(conn, "model", packets=(b"cue",))
    old = guard.OutputLease(conn, "old", producing=True)
    state = guard.state_for(conn)
    state.revoke("asr_handoff_revoked")
    conn.client_abort = False  # 识别交接后，上游可能先复位布尔、稍后才创建新UUID。
    assert not old.current()
    assert not guard.OutputLease(conn, "old", producing=True).current()
    assert not waiting.current()
    assert waiting.closed
    old.release()
    assert state.producers == 0
    conn.sentence_id = "new"
    fresh = guard.OutputLease(conn, "new", producing=True)
    assert fresh.current()
    fresh.release()


def test_snapshot_is_readonly_bounded_and_separates_config_branch_and_send():
    assert guard.snapshot(None)["status"] == "no_connection"
    conn = connection()
    assert guard.snapshot(conn)["status"] == "not_installed"
    assert not hasattr(conn, guard.STATE)
    conn._longmemory_audio_revocation_installed = True
    assert guard.snapshot(conn)["status"] == "idle_no_samples"
    assert not hasattr(conn, guard.STATE)
    lease = guard.OutputLease(conn, "old")
    lease.state.producer("adaptive_buffer", "incremental", lease=lease)
    for _ in range(500):
        lease.state.note("asr_handoff")
    value = guard.snapshot(conn)
    assert value["status"] == "observed"
    assert value["configuration"] == {"delivery_mode": "adaptive", "value_kind": "configuration"}
    assert value["observed"]["producer_path"] == "adaptive_buffer"
    assert value["observed"]["request_delivery_mode"] == "incremental"
    assert value["observed"]["server_model_delivery_mode"] == "unconfirmed"
    assert value["observed"]["server_reply_cache_hit"] == "unconfirmed"
    assert value["counts"]["first_answer_send_returned"] == 0
    assert value["device_playback_acknowledged"] is False
    encoded = json.dumps(value)
    assert len(encoded) < 2400
    assert '"old"' not in encoded and "events" not in value
    value["counts"]["asr_handoff"] = 0
    value["last_stage"]["event"] = "modified"
    assert guard.snapshot(conn)["counts"]["asr_handoff"] == 500
    assert guard.snapshot(conn)["last_stage"]["event"] == "asr_handoff"
    lease.state.revoke("asr_handoff_revoked")
    lease.state.producer("complete_wav_fallback", "full_wav", lease=lease)
    assert guard.snapshot(conn)["observed"]["producer_path"] == "adaptive_buffer"


@pytest.fixture
def upstream():
    sys.path.insert(0, str(ROOT / "tests/fixtures"))
    from voice_interruption_upstream import build
    try:
        return build()
    except FileNotFoundError:
        pytest.skip("owner-installed pinned SDK unavailable")


def install(u):
    return guard.install_voice_interruption(u.Connection, u.receive, u.asr, u.send,
                                            tts_base_module=u.ttsbase)


def test_recognized_handoff_revokes_before_intent_with_stale_speaking_flag(upstream):
    u = upstream
    lease = guard.OutputLease(u.conn, "old", producing=True)
    async def existing_wrapper(conn, text):
        u.calls.append("prior_wrapper")
        assert not lease.current()
        return await u.receive.startToChat(conn, text)
    u.asr.startToChat = existing_wrapper
    assert install(u)["requires_preemptive"] is False
    assert install(u)["installed"] is True
    asyncio.run(u.asr.startToChat(u.conn, "合成输入"))
    assert u.calls == ["prior_wrapper", "intent", "submit"]
    assert json.loads(u.messages[0])["state"] == "stop"
    assert u.conn.client_abort is False
    assert u.conn.sentence_id == "old"
    assert not lease.current()
    counts = guard.snapshot(u.conn)["counts"]
    assert counts["asr_handoff_revoked"] == counts["queues_cleared"] == 1
    assert counts["upstream_abort_revoked"] == 0
    lease.release()


def test_native_vad_revokes_before_asr_recognition_and_keeps_existing_early_path(upstream):
    u = upstream
    install(u)
    lease = guard.OutputLease(u.conn, "old", producing=True)
    u.conn.client_is_speaking = True
    u.conn.vad = NS(is_vad=lambda *_: True)
    async def receive(conn, pcm, have_voice):
        assert have_voice and not lease.current()
        u.calls.append("asr_audio")
    u.conn.asr = NS(receive_audio=receive)
    asyncio.run(u.receive.handleAudioMessage(u.conn, b"synthetic"))
    assert u.calls == ["asr_audio"]
    assert guard.snapshot(u.conn)["counts"]["upstream_abort_revoked"] == 1
    assert guard.snapshot(u.conn)["counts"]["asr_handoff"] == 0
    lease.release()


@pytest.mark.parametrize("case", ["manual", "binding", "no_output", "other_tts", "empty"])
def test_handoff_preserves_non_candidate_paths(upstream, case):
    u = upstream
    async def prior(conn, text):
        u.calls.append("prior")
    u.receive.startToChat = u.asr.startToChat = prior
    if case != "no_output":
        guard.OutputLease(u.conn, "old", producing=True)
    if case == "manual": u.conn.client_listen_mode = "manual"
    if case == "binding": u.conn.need_bind = True
    if case == "other_tts": u.conn.tts._longmemory_cosy_streaming_installed = False
    install(u)
    asyncio.run(u.asr.startToChat(u.conn, "" if case == "empty" else "合成输入"))
    assert u.messages == []
    assert u.calls == ["prior"]


def test_delayed_old_stop_cannot_stop_new_round_even_before_uuid_changes(upstream):
    u = upstream
    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()
        async def wait(conn):
            entered.set()
            await release.wait()
        u.send._wait_for_audio_completion = wait
        stopped = []
        u.conn.audio_rate_controller = NS(stop_sending=lambda: stopped.append("stop"), reset=lambda: None)
        install(u)
        guard.OutputLease(u.conn, "old", producing=True)
        old_stop = asyncio.create_task(u.send.send_tts_message(u.conn, "stop"))
        await entered.wait()
        await u.asr.startToChat(u.conn, "合成新输入")
        assert u.conn.client_abort is False and u.conn.sentence_id == "old"
        release.set()
        await old_stop
        assert stopped == []
        assert u.conn.client_is_speaking  # 新start不能被旧stop清除。
        assert [json.loads(v)["state"] for v in u.messages if json.loads(v)["type"] == "tts"] == ["stop", "start"]
        u.conn.sentence_id = u.conn.tts.current_sentence_id = "new"
        await u.send.send_tts_message(u.conn, "stop")
        assert stopped == ["stop"]
        assert not u.conn.client_is_speaking
        assert guard.snapshot(u.conn)["counts"]["stale_stop_dropped"] == 1
    asyncio.run(run())


def test_old_message_suspended_before_last_stop_keeps_original_epoch(upstream):
    u = upstream
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def audio(conn, audios, *args, **kwargs):
            entered.set()
            await release.wait()
        u.send.sendAudio = audio
        install(u)
        guard.OutputLease(u.conn, "old", producing=True)
        message = asyncio.create_task(u.ttsbase.sendAudioMessage(u.conn, "last", [b"old"], None, "old"))
        await entered.wait()
        await u.asr.startToChat(u.conn, "合成输入")
        u.conn.sentence_id = u.conn.tts.current_sentence_id = "new"
        release.set()
        await message
        assert u.conn.client_is_speaking
        assert [json.loads(v)["state"] for v in u.messages if json.loads(v)["type"] == "tts"] == ["stop", "start"]
    asyncio.run(run())


def test_final_sender_rejects_old_queued_and_late_tuple_but_sends_new(upstream):
    u = upstream
    async def run():
        install(u)
        old_waiting = u.conn._longmemory_waiting = WaitingTurn(u.conn, "model", packets=(b"cue",))
        old_flow = {"sentence_id": "old", "packet_count": 5}
        guard.OutputLease(u.conn, "old", producing=True)
        await u.asr.startToChat(u.conn, "合成输入")
        u.conn.sentence_id = u.conn.tts.current_sentence_id = "new"
        for packet in (b"plain-old", AnswerPacket(b"answer-old", old_waiting), WaitingPacket(b"cue-old", old_waiting)):
            await u.send._do_send_audio(u.conn, packet, old_flow)
        await u.ttsbase.sendAudioMessage(u.conn, "last", [b"late-old"], "private-not-recorded", "old")
        new_flow = {"sentence_id": "new", "packet_count": 0}
        await u.send._do_send_audio(u.conn, b"new", new_flow)
        assert [v for v in u.messages if isinstance(v, bytes)] == [b"new"]
        value = guard.snapshot(u.conn)
        assert value["counts"]["stale_packet_dropped"] == 3
        assert value["counts"]["stale_message_dropped"] == 1
        assert value["counts"]["first_answer_send_returned"] == 1
        assert value["device_playback_acknowledged"] is False
        assert "private-not-recorded" not in json.dumps(value)
    asyncio.run(run())


def test_inflight_socket_return_is_not_counted_as_new_first_answer(upstream):
    u = upstream
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def socket_send(value):
            entered.set()
            await release.wait()
        u.conn.websocket.send = socket_send
        install(u)
        flow = {"sentence_id": "old", "packet_count": 0}
        task = asyncio.create_task(u.send._do_send_audio(u.conn, b"already-inflight", flow))
        await entered.wait()
        guard.state_for(u.conn).revoke("upstream_abort_revoked")
        u.conn.client_abort = False
        release.set()
        await task
        counts = guard.snapshot(u.conn)["counts"]
        assert counts["inflight_old_send_returned"] == 1
        assert counts["first_answer_send_returned"] == counts["answer_send_returned"] == 0
        assert not guard.snapshot(u.conn)["active_output"]
    asyncio.run(run())


def test_cancelled_stop_joins_its_owned_wait_task(upstream):
    u = upstream
    async def run():
        entered, exited = asyncio.Event(), asyncio.Event()
        async def wait(conn):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                exited.set()
        u.send._wait_for_audio_completion = wait
        install(u)
        stop = asyncio.create_task(u.send.send_tts_message(u.conn, "stop"))
        await entered.wait()
        stop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stop
        assert exited.is_set()
        assert len(asyncio.all_tasks()) == 1
    asyncio.run(run())
