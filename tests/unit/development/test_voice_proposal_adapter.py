"""真实固定上游ASR/reset/调度/chat方法，显式屏障复现竞争；外设全部合成。"""

import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import threading
import ast
from datetime import datetime
import json
import re
from types import ModuleType
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts/development/xiaozhi"


@pytest.fixture
def boundary(monkeypatch):
    if not os.environ.get("LONGMEMORY_TEST_XIAOZHI_ROOT"):
        pytest.skip("explicit existing native repository required; never download")
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("ae_adapter_native", ROOT / "tests/fixtures/voice_proposal_adapter_native.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_off_has_no_patches_or_provider_capability_changes(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    from voice_proposal_adapter import install_voice_proposal_adapter
    adapter = install_voice_proposal_adapter(object, None, None)
    value = NS(identity="same")
    assert adapter.bind_provider(None, value) is value
    assert not adapter.enabled


@pytest.mark.parametrize("blocked_worker", [True, False])
def test_actual_native_buffer_reset_before_or_after_worker_keeps_same_verified_turn(boundary, blocked_worker):
    async def run():
        h = boundary.harness()
        try:
            await boundary.begin(h)
            if blocked_worker:
                h.executor.release.clear()
            await boundary.endpoint(h)
            assert h.connection.asr_audio == []  # 原reset确实执行，不是跳过清空。
            assert getattr(h.connection, h.prefetch._STATE).generation == 1
            h.executor.release.set()
            for future in h.executor.futures:
                await asyncio.wrap_future(future)
            assert h.connection.memory.prepares == 1
            assert h.stored == ["合成候选回答"] and not h.requests
            assert h.rpc.calls.count("start") == h.rpc.calls.count("confirm") == 1
            assert h.adapter.snapshot(h.connection)["adopted"] == 1
        finally:
            await boundary.finish(h)
    asyncio.run(run())


@pytest.mark.parametrize("cancel", ["explicit_reset", "abort", "continued", "close"])
def test_explicit_cancel_after_handoff_before_worker_never_revives_old_turn(boundary, cancel):
    async def run():
        h = boundary.harness()
        try:
            await boundary.begin(h)
            h.executor.release.clear()
            await boundary.endpoint(h)
            if cancel == "explicit_reset":
                h.connection.reset_audio_states()
            elif cancel == "abort":
                h.connection.clear_queues()
            elif cancel == "continued":
                h.connection.client_have_voice = True
                h.connection.vad_last_voice_time = boundary.time.time() * 1000
                await h.provider.receive_audio(h.connection, boundary.PCM, True)
            else:
                await h.connection.close()
            h.executor.release.set()
            for future in h.executor.futures:
                await asyncio.wrap_future(future)
            assert not h.stored and not h.requests
            assert not any(row.role == "assistant" for row in h.connection.dialogue.dialogue)
            assert "confirm" not in h.rpc.calls
        finally:
            await boundary.finish(h)
    asyncio.run(run())


def test_tools_preflight_skips_before_any_candidate_rpc(boundary):
    async def run():
        h = boundary.harness(tools=True)
        try:
            await boundary.begin(h)
            assert h.rpc.calls == []
            await boundary.endpoint(h)
            for future in h.executor.futures:
                await asyncio.wrap_future(future)
            assert h.connection.memory.prepares == 1
            assert h.stored == ["原正式回答"] and len(h.requests) == 1
            assert h.adapter.snapshot(h.connection)["skipped_tools"] == 1
        finally:
            await boundary.finish(h)
    asyncio.run(run())


def test_provider_preserves_all_methods_and_does_not_invent_functions(boundary):
    async def run():
        h = boundary.harness()
        try:
            assert h.connection.llm.identity == "synthetic-original"
            assert not hasattr(h.connection.llm, "response_with_functions")
        finally:
            await boundary.finish(h)
    asyncio.run(run())


def test_pcm_prefix_change_invalidates_before_formal_reuse(boundary):
    async def run():
        h = boundary.harness()
        try:
            await boundary.begin(h)
            h.connection.asr_audio[0] = b"\x22\x00" * 960
            await boundary.endpoint(h)
            for future in h.executor.futures:
                await asyncio.wrap_future(future)
            assert "confirm" not in h.rpc.calls
            assert h.stored == ["原正式回答"]
        finally:
            await boundary.finish(h)
    asyncio.run(run())


@pytest.mark.parametrize("change", ["emotion", "speaker", "date", "role", "history"])
def test_real_final_provider_changes_miss_and_do_not_repeat_formal_prepare(boundary, change):
    async def run():
        h = boundary.harness()
        try:
            await boundary.begin(h)
            build = h.connection.dialogue.get_llm_dialogue_with_memory
            def changed(*args):
                rows = build(*args)
                if change in {"emotion", "speaker"}:
                    data = boundary.json.loads(rows[-1]["content"])
                    data[change] = "实际值已改变"
                    rows[-1]["content"] = boundary.json.dumps(data, ensure_ascii=False)
                elif change == "history":
                    rows.insert(1, {"role": "assistant", "content": "实际历史已改变"})
                else:
                    rows[0]["content"] += "实际" + change + "已改变"
                return rows
            h.connection.dialogue.get_llm_dialogue_with_memory = changed
            await boundary.endpoint(h)
            for future in h.executor.futures:
                await asyncio.wrap_future(future)
            assert h.connection.memory.prepares == 1
            assert "confirm" not in h.rpc.calls
            assert h.rpc.calls.count("start") == 1
            assert h.stored == ["原正式回答"] and len(h.requests) == 1
        finally:
            await boundary.finish(h)
    asyncio.run(run())


def test_cancel_between_candidate_yield_and_native_enqueue_blocks_queues_store_and_history(boundary):
    async def run():
        h = boundary.harness()
        delivered, release = threading.Event(), threading.Event()
        try:
            await boundary.begin(h)
            captured = []
            put = h.connection.dialogue.put
            def completion_capture(message):
                if message.role == "assistant":
                    captured.append(message.content)
                return put(message)
            h.connection.dialogue.put = completion_capture
            response = h.connection.llm.response
            def paused(*args, **kwargs):
                for text in response(*args, **kwargs):
                    delivered.set()
                    assert release.wait(5)
                    yield text
            h.connection.llm.response = paused
            await boundary.endpoint(h)
            assert await asyncio.to_thread(delivered.wait, 3)
            old_sentence = h.connection.sentence_id
            h.connection.clear_queues()  # 故意不置client_abort，证明不是原for循环挡住输出。
            assert h.connection.client_abort is False
            # 独立TTS生产者没有chat ContextVar，同一旧句子也不能重新入音频队列。
            await asyncio.to_thread(h.connection.tts.tts_audio_queue.put, ("middle", [b"synthetic"], None, old_sentence))
            release.set()
            for future in h.executor.futures:
                await asyncio.wrap_future(future)
            assert h.connection.tts.tts_text_queue.empty() and h.connection.tts.tts_audio_queue.empty()
            assert not h.stored and not any(row.role == "assistant" for row in h.connection.dialogue.dialogue)
            assert not captured  # 后装的完成回执捕获器也在同一原子门内。
            assert h.adapter.snapshot(h.connection)["dropped_output"] >= 4
        finally:
            release.set()
            await boundary.finish(h)
    asyncio.run(run())


def test_new_asr_turn_cannot_receive_previous_paused_answer(boundary):
    async def run():
        h = boundary.harness()
        delivered, release = threading.Event(), threading.Event()
        try:
            await boundary.begin(h)
            response, first = h.connection.llm.response, [True]
            def paused(*args, **kwargs):
                for text in response(*args, **kwargs):
                    if first[0]:
                        first[0] = False
                        delivered.set()
                        assert release.wait(5)
                    yield text
            h.connection.llm.response = paused
            await boundary.endpoint(h)
            assert await asyncio.to_thread(delivered.wait, 3)
            old_sentence = h.connection.sentence_id
            h.connection.client_have_voice = True
            h.connection.vad_last_voice_time = boundary.time.time() * 1000 - 300
            await boundary.begin(h)
            await boundary.endpoint(h)
            await asyncio.wrap_future(h.executor.futures[-1])
            assert h.connection.sentence_id != old_sentence
            release.set()
            await asyncio.wrap_future(h.executor.futures[0])
            assert h.connection.memory.prepares == 2
            assert h.stored == ["合成候选回答"]
            assert len([row for row in h.connection.dialogue.dialogue if row.role == "assistant"]) == 1
            assert h.rpc.calls.count("start") == h.rpc.calls.count("confirm") == 2
        finally:
            release.set()
            await boundary.finish(h)
    asyncio.run(run())


def test_unconfirmed_owned_close_keeps_slot_and_blocks_next_ticket(boundary):
    async def run():
        h = boundary.harness()
        try:
            await boundary.begin(h)
            h.rpc.close_owned = False
            await boundary.endpoint(h)
            for future in h.executor.futures:
                await asyncio.wrap_future(future)
            assert h.adapter.snapshot(h.connection)["blocked"] and h.rpc.active == 1
            h.connection.client_have_voice = True
            h.connection.vad_last_voice_time = boundary.time.time() * 1000 - 300
            await boundary.begin(h)
            assert h.rpc.calls.count("start") == 1
            assert not await h.adapter.aclose_connection(h.connection)
        finally:
            h.rpc.close_owned = True
            await boundary.finish(h)
    asyncio.run(run())


def test_snapshot_wait_does_not_reread_live_dialogue_after_worker_has_added_current_user(boundary):
    async def run():
        snapshot_entered, snapshot_release, formal_prepared = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class DelayedRPC(boundary.SyntheticRPC):
            async def snapshot(self, **kwargs):
                snapshot_entered.set()
                await snapshot_release.wait()
                return await super().snapshot(**kwargs)
        rpc = DelayedRPC()
        h = boundary.harness(rpc_factory=lambda **_kwargs: rpc)
        try:
            original = h.connection.memory.query_memory
            async def prepare(raw):
                result = await original(raw)
                formal_prepared.set()
                return result
            h.connection.memory.query_memory = prepare
            for _ in range(16):
                await h.provider.receive_audio(h.connection, boundary.PCM, True)
            await h.provider.receive_audio(h.connection, boundary.PCM, False)
            await getattr(h.connection, h.prefetch._STATE).ticket.task
            await asyncio.wait_for(snapshot_entered.wait(), 2)
            await boundary.endpoint(h)
            await asyncio.wait_for(formal_prepared.wait(), 2)
            assert len(h.connection.dialogue.dialogue) == 1
            snapshot_release.set()
            for future in h.executor.futures:
                await asyncio.wrap_future(future)
            assert h.stored == ["合成候选回答"] and not h.requests
            assert rpc.calls.count("start") == rpc.calls.count("confirm") == 1
        finally:
            snapshot_release.set()
            await boundary.finish(h)
    asyncio.run(run())


@pytest.mark.parametrize("introduced", [False, True])
def test_pure_native_preview_preserves_speaker_projection_and_real_style_without_mutating_sets(boundary, monkeypatch, introduced):
    import voice_proposal_adapter as proposal
    import voice_web_search as web
    from voice_response_policy import prepare_voice_dialogue
    monkeypatch.setattr(web, "load_config", lambda: pytest.fail("pure preview must not read private config"))
    source = boundary.native_source("core/utils/dialogue.py")
    cls = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "Dialogue")
    methods = [node.name for node in cls.body if isinstance(node, ast.FunctionDef)]
    module = ModuleType("synthetic_native_dialogue")
    vars(module).update(datetime=datetime, re=re, json=json)
    boundary.load_nodes(source, module, methods, "Dialogue")
    Dialogue = type("Dialogue", (), {name: vars(module)[name] for name in methods})
    dialogue = Dialogue()
    dialogue.dialogue.append(NS(role="system", content="合成角色<memory>原内容</memory>", is_temporary=False,
                                tool_calls=None, tool_call_id=None))
    conn = NS(dialogue=dialogue, introduced_speakers={"合成说话人"} if introduced else set(),
        system_introduced_speakers={"合成说话人"} if introduced else set(),
        config={"voiceprint": {"speakers": ["id,合成说话人,合成说明"]}})
    raw = json.dumps({"content": "检查资料", "emotion": "calm", "language": "zh", "speaker": "合成说话人", "extra": "保留"}, ensure_ascii=False)
    before = (list(dialogue.dialogue), set(conn.introduced_speakers), set(conn.system_introduced_speakers))
    plan = proposal.preview_native_input(conn, raw, tools_required=False, web_configured=False, style="realtime")
    effective = plan.with_memory("实际六项合成记忆")
    actual_user = "检查资料" if introduced else raw
    dialogue.put(NS(role="user", content=actual_user, is_temporary=False, tool_calls=None, tool_call_id=None))
    actual = dialogue.get_llm_dialogue_with_memory(proposal.project_voice_memory_context("实际六项合成记忆"),
                                                   conn.config["voiceprint"], None if introduced else "合成说话人")
    actual = web._with_system_instruction(prepare_voice_dialogue(actual, style="realtime"), web._instruction(False))
    assert effective.model_user_message == actual_user
    assert effective.matches(proposal.capture_effective_voice_input("检查资料", actual, tools_required=False))
    assert dialogue.dialogue[:-1] == before[0]
    assert conn.introduced_speakers == before[1] and conn.system_introduced_speakers == before[2]


def test_native_preview_with_tools_skips_without_reading_live_dialogue_or_config(boundary):
    import voice_proposal_adapter as proposal
    conn = NS()  # 未触碰任何dialogue/角色/声纹/配置对象。
    raw = '{"content":"检查资料","emotion":"calm"}'
    plan = proposal.preview_native_input(conn, raw, tools_required=True, web_configured=True)
    assert plan.input.tools_required and plan.with_memory("unused") is None


def test_new_audio_revokes_queued_output_and_background_put_before_sentence_id_changes(boundary):
    async def run():
        h = boundary.harness()
        try:
            await boundary.begin(h)
            await boundary.endpoint(h)
            for future in h.executor.futures:
                await asyncio.wrap_future(future)
            old_sentence = h.connection.sentence_id
            assert h.connection.tts.tts_text_queue.qsize() > 0
            h.connection.tts.tts_audio_queue.put(("middle", [b"synthetic"], None, old_sentence))
            h.connection.client_have_voice = True
            h.connection.vad_last_voice_time = boundary.time.time() * 1000
            await h.provider.receive_audio(h.connection, boundary.PCM, True)
            assert h.connection.sentence_id == old_sentence  # 故意停在尚未调度新chat的空档。
            await asyncio.to_thread(h.connection.tts.tts_audio_queue.put, ("middle", [b"late"], None, old_sentence))
            assert h.connection.tts.tts_audio_queue.qsize() == 1  # 已有旧包仍待消费者清理，晚包已拒绝。
            for q in (h.connection.tts.tts_text_queue, h.connection.tts.tts_audio_queue):
                with pytest.raises(boundary.queue.Empty):
                    q.get_nowait()
                assert q.empty()
            assert h.adapter.snapshot(h.connection)["dropped_output"] >= 4
        finally:
            await boundary.finish(h)
    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_actual_fast_reply_retires_candidate_and_never_archives_revoked_text(boundary, monkeypatch, cancel):
    import launch_with_memory as launch
    import fast_voice_responses as fast
    import voice_proposal_adapter as proposal
    dto = ModuleType("frozen_native_tts_dto")
    exec(boundary.native_source("core/providers/tts/dto/dto.py"), vars(dto))
    monkeypatch.setitem(sys.modules, "core.providers.tts.dto.dto", dto)
    monkeypatch.setitem(sys.modules, "core.utils.dialogue", NS(Message=lambda **kwargs: NS(**kwargs)))
    monkeypatch.setattr(fast, "fast_response_for", lambda _query: "合成快捷回复")
    monkeypatch.setattr(fast, "_uses_cosyvoice3", lambda _conn: True)
    monkeypatch.setattr(fast, "default_voice_active", lambda: True)
    async def run():
        h = boundary.harness(install_adapter=False)
        receipts = []
        memory = h.connection.memory
        memory.begin_turn = lambda: ("synthetic-turn", None)
        memory.end_turn = lambda _token: None
        memory.cancel_turn = lambda *_args: None
        memory.record_completed_turn = lambda text, **kwargs: receipts.append(text)
        original_query = memory.query_memory
        async def query(raw):
            result = await original_query(raw)
            if cancel:
                h.adapter.invalidate(h.connection, "synthetic_cancel_during_fast_reply")
            return result
        memory.query_memory = query
        fast.install_fast_voice_responses(type(h.connection))
        launch.install_answer_completion(type(h.connection))
        h.adapter = proposal.install_voice_proposal_adapter(type(h.connection), h.fun, h.native.base,
            enabled=True, preview_effective_input=h.preview, formal_metadata=lambda _conn: h.metadata,
            rpc_factory=lambda **_kwargs: h.rpc)
        try:
            await boundary.begin(h)
            await boundary.endpoint(h)
            for future in h.executor.futures:
                await asyncio.wrap_future(future)
            for _ in range(20):
                if h.rpc.active == 0:
                    break
                await asyncio.sleep(.005)
            assert h.rpc.active == 0 and h.rpc.calls.count("cancel") == 1
            assert "confirm" not in h.rpc.calls and not h.requests
            assert memory.prepares == 1
            assert receipts == ([] if cancel else ["合成快捷回复"])
            assert [row.content for row in h.connection.dialogue.dialogue if row.role == "assistant"] == receipts
            assert h.connection.tts.tts_text_queue.qsize() == (0 if cancel else 3)
        finally:
            await boundary.finish(h)
    asyncio.run(run())


def test_native_dto_and_final_packet_sender_drop_old_output_after_new_speech(boundary):
    from cosyvoice_streaming import CosyVoicePacket
    from voice_latency import observed_audio_sender, observed_cosy_packet_sender
    dto = ModuleType("frozen_native_tts_dto")
    exec(boundary.native_source("core/providers/tts/dto/dto.py"), vars(dto))
    async def run():
        h = boundary.harness()
        sent = []
        async def send(_conn, _kind, audios, _text, _sentence):
            sent.extend(audios)
        async def socket(_conn, packet, _control):
            sent.append(packet)
        try:
            await boundary.begin(h)
            await boundary.endpoint(h)
            for future in h.executor.futures:
                await asyncio.wrap_future(future)
            state = vars(h.connection)["_longmemory_proposal_adapter_state"]
            old_sentence = h.connection.sentence_id
            h.connection.tts.tts_text_queue.put(dto.TTSMessageDTO(sentence_id=old_sentence,
                sentence_type=dto.SentenceType.MIDDLE, content_type=dto.ContentType.TEXT, content_detail="合成文字"))
            packet = CosyVoicePacket(b"old", old_sentence, lambda: not state.output_current(old_sentence))
            h.connection.client_have_voice = True
            h.connection.vad_last_voice_time = boundary.time.time() * 1000
            await h.provider.receive_audio(h.connection, boundary.PCM, True)
            assert h.connection.sentence_id == old_sentence
            with pytest.raises(boundary.queue.Empty):
                h.connection.tts.tts_text_queue.get_nowait()
            await observed_audio_sender(send)(h.connection, "middle", [packet, b"current"], None, old_sentence)
            await observed_cosy_packet_sender(socket)(h.connection, packet, None)
            assert sent == [b"current"]
        finally:
            await boundary.finish(h)
    asyncio.run(run())
