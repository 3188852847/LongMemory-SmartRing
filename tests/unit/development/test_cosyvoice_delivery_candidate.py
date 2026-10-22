"""连接内交付模式、故障降级及不重播边界；没有真实HTTP/模型或偏好写入。"""
import json
import re
import sys
from types import SimpleNamespace as NS

import pytest

from test_cosyvoice_streaming import cancellable_stream, streaming
from cosyvoice_delivery import ATTRIBUTE, delivery_snapshot, session_for


def quiet(state):
    state.connection.logger = NS(bind=lambda **_: NS(warning=lambda *_: None))
    class Encoder:
        def reset_state(self):
            state.resets += 1
        def encode_pcm_to_opus_stream(self, pcm, *, end_of_stream, callback):
            if pcm:
                callback(b"encoded:" + pcm)
    state.tts.opus_encoder = Encoder()


def test_cleaned_empty_segments_do_not_degrade_or_replay_following_incremental_text(cancellable_stream, monkeypatch):
    state = cancellable_stream
    quiet(state)
    cleaner = sys.modules['core.utils.tts'].MarkdownCleaner
    monkeypatch.setattr(cleaner, 'clean_markdown', lambda text: '' if text == '🙂' else text)
    modes = []
    original_open = streaming._open_stream
    def open_stream(*args, **kwargs):
        modes.append(kwargs['json']['delivery_mode'])
        return original_open(*args, **kwargs)
    monkeypatch.setattr(streaming, '_open_stream', open_stream)

    state.tts.to_tts_stream('🙂', opus_handler=state.packets.append)
    assert state.requests == 0 and state.packets == state.queued == []
    assert not hasattr(state.connection, ATTRIBUTE)

    state.tts.to_tts_stream('公开正文', opus_handler=state.packets.append)
    before = delivery_snapshot(state.connection)
    state.tts._correct_words_pattern = re.compile('silent')
    state.tts.correct_words = {'silent': ''}
    for text in ('🙂', ' \t\n', 'silent'):
        state.tts.to_tts_stream(text, opus_handler=state.packets.append)
    assert state.requests == 1 and state.packets == [b'encoded:abcdef']
    assert len(state.queued) == 1 and state.resets == 0
    assert delivery_snapshot(state.connection) == before

    state.tts.to_tts_stream('继续公开正文', opus_handler=state.packets.append)
    assert modes == ['incremental', 'incremental'] and state.requests == 2
    assert state.packets == [b'encoded:abcdef', b'encoded:abcdef'] and len(state.queued) == 2
    after = delivery_snapshot(state.connection)
    assert after['effective_mode'] == 'incremental' and after['failure_code'] is None
    assert after['outcomes']['completed'] == 2 and after['outcomes']['failed'] == 0


def test_snapshot_is_readonly_and_default_legacy_configuration_is_buffered():
    conn = NS()
    assert delivery_snapshot(None)["state"] == "no_connection"
    assert delivery_snapshot(conn)["requested_mode"] == "buffered"
    assert not hasattr(conn, ATTRIBUTE)


@pytest.mark.parametrize("value", [None, True, "fast", {}, 1])
def test_invalid_configuration_does_not_silently_enable_a_mode(value):
    conn = NS(_longmemory_cosy_delivery_mode=value)
    assert delivery_snapshot(conn)["state"] == "invalid_configuration"
    with pytest.raises(ValueError):
        session_for(conn)


def test_persisted_requested_choice_survives_roundtrip_but_runtime_failure_does_not():
    # 合成设置只在内存；实际偏好文件/启动参数接线由AI负责。
    saved = json.dumps({"cosy_delivery_mode": "adaptive"})
    conn = NS(_longmemory_cosy_delivery_mode=json.loads(saved)["cosy_delivery_mode"])
    state = session_for(conn)
    state.degrade("after_handoff")
    assert state.select("adaptive") == "buffered"
    assert conn._longmemory_cosy_delivery_mode == "adaptive"
    snap = delivery_snapshot(conn)
    assert snap["requested_mode"] == "adaptive" and snap["effective_mode"] == "buffered"
    snap["outcomes"]["failed"] = 999
    assert delivery_snapshot(conn)["outcomes"]["failed"] == 0
    restarted = NS(_longmemory_cosy_delivery_mode=json.loads(saved)["cosy_delivery_mode"])
    assert session_for(restarted).select("adaptive") == "adaptive"
    rollback = NS(_longmemory_cosy_delivery_mode="buffered")
    assert session_for(rollback).select("buffered") == "buffered"


def test_live_configuration_change_blocks_old_connection_until_restart():
    conn = NS(_longmemory_cosy_delivery_mode="adaptive")
    state = session_for(conn)
    conn._longmemory_cosy_delivery_mode = "buffered"
    assert delivery_snapshot(conn)["restart_required"]
    assert state.select("buffered") is None
    assert delivery_snapshot(conn)["failure_code"] == "configuration_changed"


def test_callback_that_may_have_enqueued_then_fails_never_replays_whole_sentence(cancellable_stream):
    state = cancellable_stream
    quiet(state)
    replay = []
    state.fallback = lambda *a, **k: replay.append(True)
    def uncertain(packet):
        state.packets.append(packet)
        raise OSError("synthetic failure after enqueue")
    state.tts.to_tts_stream("public-synthetic", opus_handler=uncertain)
    assert state.packets == [b"encoded:abcdef"] and not replay
    assert delivery_snapshot(state.connection)["failure_code"] == "after_handoff"
    assert delivery_snapshot(state.connection)["effective_mode"] == "buffered"


def test_stream_failure_after_first_audio_latches_only_later_segments_to_buffered(cancellable_stream, monkeypatch):
    state = cancellable_stream
    quiet(state)
    original_open = streaming._open_stream
    requested = []
    def opened(*args, **kwargs):
        requested.append(kwargs["json"]["delivery_mode"])
        return original_open(*args, **kwargs)
    def chunks(*_a, **_k):
        yield b"abcdef"
        if len(requested) == 1:
            raise EOFError("synthetic missing EOS")
    monkeypatch.setattr(streaming, "_open_stream", opened)
    monkeypatch.setattr(streaming, "iter_wav_chunks", chunks)
    state.tts.to_tts_stream("old", opus_handler=state.packets.append)
    assert state.packets == [b"encoded:abcdef"]
    state.connection.sentence_id = state.tts.current_sentence_id = "new"
    state.tts.to_tts_stream("new", opus_handler=state.packets.append)
    assert requested == ["incremental", "buffered"]
    assert state.packets == [b"encoded:abcdef"] * 2
    assert delivery_snapshot(state.connection)["outcomes"]["failed"] == 1
    assert delivery_snapshot(state.connection)["outcomes"]["completed"] == 1


def test_failure_before_handoff_can_use_existing_full_wav_fallback_once(cancellable_stream, monkeypatch):
    state = cancellable_stream
    quiet(state)
    fallback = []
    def failed(*_a, **_k):
        raise OSError("synthetic stream unavailable")
    def complete(_text, *, opus_handler):
        fallback.append(True)
        opus_handler(b"full-wav")
    state.fallback = complete
    monkeypatch.setattr(streaming, "_open_stream", failed)
    state.tts.to_tts_stream("public", opus_handler=state.packets.append)
    assert fallback == [True] and state.packets == [b"full-wav"]
    assert delivery_snapshot(state.connection)["outcomes"]["fallback"] == 1
    assert delivery_snapshot(state.connection)["effective_mode"] == "buffered"
    assert delivery_snapshot(state.connection)["handoff_started"]


def test_uncertain_reader_cleanup_blocks_future_requests_even_for_new_sentence(cancellable_stream, monkeypatch):
    state = cancellable_stream
    quiet(state)
    state.connection._longmemory_cosy_delivery_mode = "adaptive"
    original = streaming.AdaptivePCMBuffer
    class BrokenCleanup(original):
        def close(self):
            super().close()  # 合成测试先回收实际线程，再模拟“不确定”，不留真线程。
            raise streaming._ReaderCleanupTimeout("synthetic")
    monkeypatch.setattr(streaming, "AdaptivePCMBuffer", BrokenCleanup)
    state.tts.to_tts_stream("old", opus_handler=state.packets.append)
    before = state.requests
    state.connection.sentence_id = state.tts.current_sentence_id = "new"
    state.tts.to_tts_stream("new", opus_handler=state.packets.append)
    snap = delivery_snapshot(state.connection)
    assert state.requests == before == 1
    assert snap["restart_required"] and snap["failure_code"] == "reader_cleanup_timeout"
    assert snap["outcomes"]["blocked"] == 1
    assert snap["outcomes"]["failed"] == 1 and snap["outcomes"]["completed"] == 0


def test_fallback_callback_failure_cannot_make_sdk_retry_already_queued_audio(cancellable_stream, monkeypatch):
    state = cancellable_stream
    quiet(state)
    attempts = []
    def failed(*_a, **_k):
        raise OSError("synthetic stream unavailable")
    def upstream_retry(_text, *, opus_handler):
        # 固定SDK的Exception重试语义；不运行实际HTTP。
        for _ in range(5):
            attempts.append(True)
            try:
                opus_handler(b"possibly-queued")
                opus_handler(b"tail")
                break
            except Exception:
                continue
    state.fallback = upstream_retry
    monkeypatch.setattr(streaming, "_open_stream", failed)
    def uncertain(packet):
        state.packets.append(packet)
        raise OSError("synthetic delivery error after queue")
    state.tts.to_tts_stream("public", opus_handler=uncertain)
    assert attempts == [True] and state.packets == [b"possibly-queued"]
    snap = delivery_snapshot(state.connection)
    assert snap["last_outcome"] == "failed" and snap["failure_code"] == "after_handoff"
    assert snap["outcomes"]["completed"] == snap["outcomes"]["fallback"] == 0


def test_cleanup_error_during_cancel_still_blocks_future_synthesis(cancellable_stream, monkeypatch):
    state = cancellable_stream
    quiet(state)
    state.connection._longmemory_cosy_delivery_mode = "adaptive"
    original = streaming.AdaptivePCMBuffer
    class BrokenCleanup(original):
        def close(self):
            super().close()
            raise OSError("synthetic cleanup unknown")
    monkeypatch.setattr(streaming, "AdaptivePCMBuffer", BrokenCleanup)
    def stop(packet):
        state.packets.append(packet)
        state.connection.client_abort = True
    state.tts.to_tts_stream("old", opus_handler=stop)
    snap = delivery_snapshot(state.connection)
    assert snap["restart_required"] and snap["reader_cleanup"] == "unconfirmed"
    assert snap["failure_code"] == "reader_cleanup_unconfirmed"
    assert snap["last_outcome"] == "failed" and not snap["next_segment_allowed"]
    state.connection.client_abort = False
    state.connection.sentence_id = state.tts.current_sentence_id = "new"
    state.tts.to_tts_stream("new", opus_handler=state.packets.append)
    assert state.requests == 1


def test_expected_barge_in_cancellation_does_not_degrade_mode(cancellable_stream):
    state = cancellable_stream
    quiet(state)
    def stop(packet):
        state.packets.append(packet)
        state.connection.client_abort = True
    state.tts.to_tts_stream("old", opus_handler=stop)
    snap = delivery_snapshot(state.connection)
    assert snap["effective_mode"] == "incremental" and snap["failure_code"] is None
    assert snap["outcomes"]["cancelled"] == 1


def test_latency_exposes_same_delivery_snapshot_without_changing_v6():
    import voice_latency
    assert voice_latency.delivery_snapshot is delivery_snapshot


def test_fixed_snapshot_schema_remains_under_512_bytes_with_saturated_counters():
    import cosyvoice_delivery as policy
    fields = {"version", "state", "requested_mode", "effective_mode", "failure_code", "last_outcome",
              "handoff_started", "reader_cleanup", "segment_active", "next_segment_allowed",
              "restart_required", "outcomes", "physical_playback_verified"}
    conn = NS(_longmemory_cosy_delivery_mode="incremental")
    state = session_for(conn)
    state.begin()
    state.reader_started()
    state.mark_handoff()
    running = delivery_snapshot(conn)
    assert running["segment_active"] and running["handoff_started"] and not running["next_segment_allowed"]
    state.degrade("reader_cleanup_unconfirmed", blocked=True)
    state.note("failed", handoff=True, cleanup="unconfirmed")
    for key in policy.OUTCOMES:
        state.outcomes[key] = 1_000_000
        state.note(key)
    for value in (delivery_snapshot(None), delivery_snapshot(NS()), delivery_snapshot(conn),
                  policy._payload("invalid_configuration", "incremental", "incremental",
                      failure="reader_cleanup_unconfirmed", outcome="completed", cleanup="not_observed",
                      outcomes={key: 1_000_000 for key in policy.OUTCOMES})):
        assert set(value) == fields
        assert len(json.dumps(value).encode("utf-8")) <= 512
        assert all(0 <= count <= 1_000_000 for count in value["outcomes"].values())
