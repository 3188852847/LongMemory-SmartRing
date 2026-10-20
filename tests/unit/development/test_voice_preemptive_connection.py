import asyncio
from contextlib import asynccontextmanager
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

from test_voice_preemptive import FakeModel, context, drain, p


sys.modules["voice_preemptive"] = p
SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/voice_preemptive_connection.py"
SPEC = importlib.util.spec_from_file_location("ae_preemptive_connection", SCRIPT)
b = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = b
SPEC.loader.exec_module(b)


def event(kind, *, turn=0, audio=0, epoch=0, mode="enabled", authoritative=None, reason=None):
    if authoritative is None:
        authoritative = mode == "enabled" and kind != "provisional"
    return dict(version=1, type=kind, signal=b._SIGNALS[kind], turn_id=turn,
                audio_revision=audio, transcript_revision=None, cancel_epoch=epoch,
                mode=mode, authoritative=authoritative,
                reason=reason or ("speech_resumed" if kind in {"cancel", "continued"} else "model_complete"))


def bridge(model=None, *, concurrency=1):
    return b.PreemptiveConnections(model or FakeModel(), p.RequestBudget(max_active=concurrency),
                                  limits=p.Limits(enabled=True))


def bind(manager, conn, text="合成问题", *, audio=None, ctx=None):
    return manager.bind_transcript(conn, audio=audio or b.AudioStamp(0, 0, 0),
                                   text=text, context=ctx or context())


def test_bridge_import_source_is_assigned_tree():
    assert Path(b.__file__).resolve() == SCRIPT.resolve()


@pytest.mark.parametrize("text_first", [False, True])
def test_real_text_and_provisional_can_arrive_in_either_order(text_first):
    async def run():
        manager, conn, ctx = bridge(), SimpleNamespace(), context()
        binding = bind(manager, conn, ctx=ctx) if text_first else None
        manager.on_event(conn, event("provisional"))
        if binding is None:
            binding = bind(manager, conn, ctx=ctx)
        await drain()
        assert manager.snapshot(conn)["candidate"]["ready"] == 1
        assert manager.snapshot(conn)["candidate"]["hits"] == 0
        assert await manager.confirmed(conn, binding=binding, final_text="合成问题", context=ctx) is None
        manager.on_event(conn, event("confirmed"))
        lease = await manager.confirmed(conn, binding=binding, final_text="合成问题", context=ctx)
        assert lease.claim(conn, binding=binding, context=ctx) == "合成回答。"
        assert lease.claim(conn, binding=binding, context=ctx) is None
        assert await manager.aclose()
    asyncio.run(run())


def test_ac_confirmed_before_asr_does_not_start_model_or_grant_text_authority():
    async def run():
        manager, conn = bridge(), SimpleNamespace()
        manager.on_event(conn, event("confirmed"))
        binding = bind(manager, conn)
        assert binding.turn.transcript_revision == 1
        assert await manager.confirmed(conn, binding=binding, final_text="合成问题", context=context()) is None
        assert manager.model.started == 0
        assert await manager.aclose()
    asyncio.run(run())


def test_shadow_never_prepares_or_claims_and_provisional_is_never_authoritative():
    async def run():
        manager, conn = bridge(), SimpleNamespace()
        manager.on_event(conn, event("provisional", mode="shadow"))
        binding = bind(manager, conn)
        manager.on_event(conn, event("confirmed", mode="shadow"))
        assert await manager.confirmed(conn, binding=binding, final_text="合成问题", context=context()) is None
        assert manager.model.started == 0
        bad = event("provisional", authoritative=True)
        assert not manager.on_event(conn, bad)
        assert manager.snapshot(conn)["counts"]["malformed"] == 1
        assert await manager.aclose()
    asyncio.run(run())


def test_text_revision_is_independent_and_changes_immediately_cancel_candidate():
    async def run():
        manager, conn, ctx = bridge(), SimpleNamespace(), context()
        manager.on_event(conn, event("provisional", audio=17))
        audio = b.AudioStamp(0, 17, 0)
        first = bind(manager, conn, audio=audio, ctx=ctx)
        await drain()
        second = bind(manager, conn, "合成修订", audio=audio, ctx=ctx)
        assert first.turn.transcript_revision == 1
        assert second.turn.transcript_revision == 2
        assert second.turn.transcript_revision != second.audio.audio_revision
        manager.on_event(conn, event("confirmed", audio=17))
        assert await manager.confirmed(conn, binding=first, final_text="合成问题", context=ctx) is None
        assert await manager.confirmed(conn, binding=second, final_text="合成修订", context=ctx) is None
        assert manager.model.started == 1  # 修订不为同轮发第二请求。
        assert await manager.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("changed", ["text", "version", "messages"])
def test_actual_final_text_and_current_context_are_mandatory(changed):
    async def run():
        manager, conn, ctx = bridge(), SimpleNamespace(), context()
        manager.on_event(conn, event("provisional"))
        binding = bind(manager, conn, ctx=ctx)
        manager.on_event(conn, event("confirmed"))
        final_text, final_ctx = "合成问题", ctx
        if changed == "text":
            final_text += "续句"
        elif changed == "version":
            final_ctx = context(memory_revision="new")
        else:
            final_ctx = p.ContextSnapshot(ctx.version, (("system", "不同角色"),))
        assert await manager.confirmed(conn, binding=binding, final_text=final_text, context=final_ctx) is None
        assert await manager.confirmed(conn, binding=binding, final_text="合成问题", context=ctx) is None
        assert manager.snapshot(conn)["candidate"]["hits"] == 0
        assert await manager.aclose()
    asyncio.run(run())


class EchoModel(FakeModel):
    @asynccontextmanager
    async def open(self, request):
        self.requests.append(request)
        self.started += 1
        text = request.messages[-1][1]
        class Stream:
            usage = {"prompt_tokens": 10, "completion_tokens": 4}
            async def __aiter__(self):
                await asyncio.sleep(0)
                yield "回答：" + text
        try:
            yield Stream()
        finally:
            self.closed += 1


def test_two_connections_same_audio_ids_are_isolated_in_payloads_leases_and_cancel():
    async def run():
        model = EchoModel()
        manager, a, c, ctx = bridge(model, concurrency=2), SimpleNamespace(), SimpleNamespace(), context()
        manager.on_event(a, event("provisional"))
        manager.on_event(c, event("provisional"))
        first = bind(manager, a, "连接A合成问题", ctx=ctx)
        second = bind(manager, c, "连接B合成问题", ctx=ctx)
        manager.on_event(a, event("confirmed"))
        manager.on_event(c, event("confirmed"))
        al, cl = await asyncio.gather(
            manager.confirmed(a, binding=first, final_text="连接A合成问题", context=ctx),
            manager.confirmed(c, binding=second, final_text="连接B合成问题", context=ctx))
        assert al.claim(c, binding=first, context=ctx) is None
        assert cl.claim(a, binding=second, context=ctx) is None
        manager.on_event(a, event("cancel", epoch=1))
        manager.on_event(a, event("continued", audio=1, epoch=1))
        assert al.claim(a, binding=first, context=ctx) is None
        assert cl.claim(c, binding=second, context=ctx) == "回答：连接B合成问题"
        assert {request.messages[-1][1] for request in model.requests} == {"连接A合成问题", "连接B合成问题"}
        assert len({request.scope.connection_id for request in model.requests}) == 2
        assert {request.scope.owner_id for request in model.requests} == {manager.owner_id}
        assert all(request.scope.turn.transcript_revision == 1 for request in model.requests)
        assert all(request.scope.audio_revision == 0 for request in model.requests)
        assert getattr(a, b.STATE) is not getattr(c, b.STATE)
        assert "连接A" not in repr(manager.snapshot(a))
        assert await manager.aclose()
    asyncio.run(run())


def test_shared_budget_is_occupied_by_other_connection_until_actual_close():
    async def run():
        gate, ctx = asyncio.Event(), context()
        model = FakeModel(gate=gate, ignore_cancel=True)
        manager, a, c = bridge(model), SimpleNamespace(), SimpleNamespace()
        manager.on_event(a, event("provisional"))
        ab = bind(manager, a, ctx=ctx)
        await model.entered.wait()
        manager.on_event(a, event("continued", audio=1, epoch=1))
        manager.on_event(c, event("provisional"))
        bind(manager, c, ctx=ctx)
        assert manager.snapshot(c)["candidate"]["skipped_busy"] == 1
        assert manager.budget.active == 1
        assert await manager.confirmed(a, binding=ab, final_text="合成问题", context=ctx) is None
        gate.set()
        assert await manager.aclose()
        assert manager.budget.active == 0
    asyncio.run(run())


def test_old_cancel_text_and_reset_events_cannot_adopt_back_old_audio():
    async def run():
        manager, conn, ctx = bridge(), SimpleNamespace(), context()
        manager.on_event(conn, event("provisional"))
        old = bind(manager, conn, ctx=ctx)
        manager.on_event(conn, event("cancel", epoch=1))
        manager.on_event(conn, event("continued", audio=1, epoch=1))
        assert bind(manager, conn, audio=old.audio) is None
        assert not manager.on_event(conn, event("cancel", epoch=1))  # 旧audio_revision。
        manager.reset(conn)
        assert bind(manager, conn, audio=b.AudioStamp(0, 1, 1)) is None
        await drain()  # 等旧请求的真实关闭回调释放工位；事件撤销本身不会释放。
        manager.on_event(conn, event("provisional", turn=2, epoch=1))
        new = bind(manager, conn, audio=b.AudioStamp(2, 0, 1), ctx=ctx)
        assert new is not None
        manager.on_event(conn, event("confirmed", turn=2, epoch=1))
        lease = await manager.confirmed(conn, binding=new, final_text="合成问题", context=ctx)
        assert lease.claim(conn, binding=new, context=ctx)
        assert await manager.aclose()
    asyncio.run(run())


def test_threaded_continuation_blocks_claim_before_loop_delivers_cancel():
    async def run():
        manager, conn, ctx = bridge(), SimpleNamespace(), context()
        manager.on_event(conn, event("provisional"))
        binding = bind(manager, conn, ctx=ctx)
        manager.on_event(conn, event("confirmed"))
        lease = await manager.confirmed(conn, binding=binding, final_text="合成问题", context=ctx)
        worker = threading.Thread(target=lambda: manager.on_event(conn, event("continued", audio=1, epoch=1)))
        worker.start()
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert manager.snapshot(conn)["quarantined"]
        assert lease.claim(conn, binding=binding, context=ctx) is None
        await drain()
        assert not manager.snapshot(conn)["quarantined"]
        assert lease.claim(conn, binding=binding, context=ctx) is None
        assert await manager.aclose()
    asyncio.run(run())


def test_foreign_binding_cannot_confirm_other_connection():
    async def run():
        manager, a, c = bridge(), SimpleNamespace(), SimpleNamespace()
        manager.on_event(a, event("provisional"))
        binding = bind(manager, a)
        manager.on_event(c, event("confirmed"))
        assert await manager.confirmed(c, binding=binding, final_text="合成问题", context=context()) is None
        assert manager.snapshot(c)["counts"]["foreign_binding"] == 1
        assert await manager.aclose()
    asyncio.run(run())


def test_lifecycle_hooks_preserve_original_calls_and_cancel_on_close_exception():
    async def run():
        manager = bridge()
        class Conn:
            def reset_audio_states(self):
                self.resets = getattr(self, "resets", 0) + 1
                return "original-reset"
            async def close(self):
                raise OSError("模拟原关闭异常")
        b.install_preemptive_connection_lifecycle(Conn, manager)
        conn = Conn()
        manager.on_event(conn, event("provisional"))
        binding = bind(manager, conn)
        assert conn.reset_audio_states() == "original-reset" and conn.resets == 1
        assert await manager.confirmed(conn, binding=binding, final_text="合成问题", context=context()) is None
        with pytest.raises(OSError):
            await conn.close()
        assert manager.snapshot(conn)["closed"]
        assert manager.budget.active == 0
        with pytest.raises(RuntimeError, match="already_installed"):
            b.install_preemptive_connection_lifecycle(Conn, manager)
        assert await manager.aclose()
    asyncio.run(run())


def test_untrusted_transcript_version_field_cannot_supply_text_authority():
    async def run():
        manager, conn = bridge(), SimpleNamespace()
        invalid = event("confirmed")
        invalid["transcript_revision"] = 17
        assert not manager.on_event(conn, invalid)
        assert manager.snapshot(conn)["counts"]["malformed"] == 1
        assert manager.model.started == 0
        assert await manager.aclose()
    asyncio.run(run())


def test_reset_without_prior_binding_uses_explicit_audio_floor():
    async def run():
        manager, conn = bridge(), SimpleNamespace()
        manager.reset(conn, last_turn_id=9)
        assert bind(manager, conn, audio=b.AudioStamp(9, 0, 0)) is None
        manager.on_event(conn, event("provisional", turn=10))
        assert bind(manager, conn, audio=b.AudioStamp(10, 0, 0)) is not None
        assert await manager.aclose()
    asyncio.run(run())


BASE_PCM = b"\x17\x00" * 960 * 40


def baseline(model=None, *, enabled=True):
    return b.PreemptiveConnections(model or FakeModel(), p.RequestBudget(),
                                  limits=p.Limits(enabled=enabled), candidate_source="baseline_asr")


def baseline_input(manager, conn, *, text="合成当前问题", ctx=None, pcm=BASE_PCM):
    proof = b.ASRPrefetchProof(3, 1000.0, len(pcm), hashlib.sha256(pcm).digest(), "zh")
    binding = manager.baseline_asr_provisional(
        conn, audio=b.AudioStamp(3, 17, 0), text=text, context=ctx or context(), proof=proof)
    return binding, proof


def test_baseline_prefetch_can_hit_with_nonempty_memory_without_smart_turn_enabled():
    async def run():
        manager, conn = baseline(), SimpleNamespace()
        ctx = p.ContextSnapshot(p.SnapshotVersion("synthetic-L2-source-1", "c", "no-tools", "school-role"),
                                (("system", "合成角色。记忆证据：用户偏好无糖茶；来源synthetic-source-1。"),))
        binding, proof = baseline_input(manager, conn, ctx=ctx)
        await drain()
        assert manager.snapshot(conn)["candidate"]["ready"] == 1
        assert manager.snapshot(conn)["candidate"]["hits"] == 0
        assert binding.turn.transcript_revision == 1 and binding.audio.audio_revision == 17
        # AC shadow 的无权威事件不能启动或确认baseline，也不能混用它的音频命名空间。
        manager.on_event(conn, event("provisional", turn=99, audio=99, epoch=99, mode="shadow"))
        manager.on_event(conn, event("confirmed", turn=99, audio=99, epoch=99, mode="shadow"))
        assert await manager.confirmed(conn, binding=binding, final_text="合成当前问题", context=ctx) is None
        lease = await manager.baseline_confirmed(
            conn, binding=binding, final_text="合成当前问题", context=ctx,
            final_pcm=BASE_PCM + b"\0" * 1920, generation=proof.generation,
            voice_stamp=proof.voice_stamp, language=proof.language)
        assert lease.claim(conn, binding=binding, context=ctx) == "合成回答。"
        assert manager.snapshot(conn)["candidate"]["hits"] == 1 and manager.model.started == 1
        assert "无糖茶" not in repr(manager.snapshot(conn))
        assert await manager.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("change", ["generation", "voice", "language", "prefix", "short", "text", "context"])
def test_baseline_original_endpoint_requires_full_matching_pcm_text_and_context(change):
    async def run():
        manager, conn, ctx = baseline(), SimpleNamespace(), context()
        binding, proof = baseline_input(manager, conn, ctx=ctx)
        kwargs = dict(final_text="合成当前问题", context=ctx, final_pcm=BASE_PCM,
                      generation=proof.generation, voice_stamp=proof.voice_stamp, language=proof.language)
        if change == "generation": kwargs["generation"] += 1
        elif change == "voice": kwargs["voice_stamp"] += 1
        elif change == "language": kwargs["language"] = "en"
        elif change == "prefix": kwargs["final_pcm"] = b"\0" * len(BASE_PCM)
        elif change == "short": kwargs["final_pcm"] = BASE_PCM[:-1920]
        elif change == "text": kwargs["final_text"] += "续句"
        else: kwargs["context"] = context(memory_revision="changed")
        assert await manager.baseline_confirmed(conn, binding=binding, **kwargs) is None
        assert manager.snapshot(conn)["candidate"]["hits"] == 0
        assert await manager.aclose()
    asyncio.run(run())


def test_baseline_continuation_cancels_old_result_without_retry_but_next_generation_can_prepare():
    async def run():
        manager, conn, ctx = baseline(), SimpleNamespace(), context()
        first, proof = baseline_input(manager, conn, ctx=ctx)
        await drain()
        manager.baseline_continued(conn, audio=b.AudioStamp(3, 18, 1))
        assert await manager.baseline_confirmed(
            conn, binding=first, final_text="合成当前问题", context=ctx, final_pcm=BASE_PCM,
            generation=3, voice_stamp=1000.0, language="zh") is None
        newer = b.ASRPrefetchProof(3, 2000.0, len(BASE_PCM), hashlib.sha256(BASE_PCM).digest(), "zh")
        manager.baseline_asr_provisional(conn, audio=b.AudioStamp(3, 18, 1), text="合成续句", context=ctx, proof=newer)
        assert manager.model.started == 1
        manager.reset(conn, last_turn_id=3)
        # 新轮首个发声事件不应消耗这轮唯一准备机会。
        manager.baseline_continued(conn, audio=b.AudioStamp(4, 0, 1))
        next_proof = b.ASRPrefetchProof(4, 3000.0, len(BASE_PCM), hashlib.sha256(BASE_PCM).digest(), "zh")
        next_binding = manager.baseline_asr_provisional(
            conn, audio=b.AudioStamp(4, 0, 1), text="新轮合成问题", context=ctx, proof=next_proof)
        lease = await manager.baseline_confirmed(
            conn, binding=next_binding, final_text="新轮合成问题", context=ctx, final_pcm=BASE_PCM,
            generation=4, voice_stamp=3000.0, language="zh")
        assert lease.claim(conn, binding=next_binding, context=ctx)
        assert manager.model.started == 2
        assert await manager.aclose()
    asyncio.run(run())


def test_baseline_candidate_switch_off_and_missing_proof_do_not_request_model():
    async def run():
        manager, conn = baseline(enabled=False), SimpleNamespace()
        baseline_input(manager, conn)
        await drain()
        assert manager.model.started == 0
        with pytest.raises(ValueError, match="baseline_proof_required"):
            manager.bind_transcript(conn, audio=b.AudioStamp(3, 17, 0), text="合成问题", context=context())
        with pytest.raises(ValueError, match="prefetch_proof_invalid"):
            manager.baseline_asr_provisional(conn, audio=b.AudioStamp(3, 17, 0), text="合成问题",
                                             context=context(), proof=True)
        assert await manager.aclose()
    asyncio.run(run())


def test_baseline_two_connections_cannot_use_each_others_final_audio_or_binding():
    async def run():
        manager, a, c = baseline(), SimpleNamespace(), SimpleNamespace()
        binding, proof = baseline_input(manager, a)
        assert await manager.baseline_confirmed(
            c, binding=binding, final_text="合成当前问题", context=context(), final_pcm=BASE_PCM,
            generation=3, voice_stamp=1000.0, language="zh") is None
        assert manager.snapshot(c)["counts"]["foreign_binding"] == 1
        assert await manager.aclose()
    asyncio.run(run())


def test_baseline_continuation_after_final_asr_before_claim_revokes_lease():
    async def run():
        manager, conn, ctx = baseline(), SimpleNamespace(), context()
        binding, proof = baseline_input(manager, conn, ctx=ctx)
        lease = await manager.baseline_confirmed(
            conn, binding=binding, final_text="合成当前问题", context=ctx, final_pcm=BASE_PCM,
            generation=3, voice_stamp=1000.0, language="zh")
        assert lease is not None
        manager.baseline_continued(conn, audio=b.AudioStamp(3, 18, 1))
        assert lease.claim(conn, binding=binding, context=ctx) is None
        assert manager.snapshot(conn)["candidate"]["hits"] == 0
        assert await manager.aclose()
    asyncio.run(run())


def test_baseline_json_payload_preserved_and_metadata_revision_is_not_audio_revision():
    async def run():
        manager, conn, ctx = baseline(), SimpleNamespace(), context()
        proof = b.ASRPrefetchProof(3, 1000., len(BASE_PCM), hashlib.sha256(BASE_PCM).digest(), "zh")
        raw = json.dumps({"content": "合成问题", "language": "zh", "emotion": "NEUTRAL", "speaker": "合成说话人"}, ensure_ascii=False)
        binding = manager.baseline_asr_provisional(conn, audio=b.AudioStamp(3, 17, 0), text="合成问题",
            context=ctx, proof=proof, model_user_message=raw)
        lease = await manager.baseline_confirmed(conn, binding=binding, final_text="合成问题", context=ctx,
            final_pcm=BASE_PCM, generation=3, voice_stamp=1000., language="zh", model_user_message=raw)
        assert lease.claim(conn, binding=binding, context=ctx, model_user_message=raw) == "合成回答。"
        assert manager.model.requests[0].messages[-1] == ("user", raw)
        assert binding.turn.transcript_revision == 1 and binding.audio.audio_revision == 17
        assert await manager.aclose()
    asyncio.run(run())


def test_baseline_metadata_change_cancels_old_candidate_without_reissuing_or_stripping_metadata():
    async def run():
        manager, conn, ctx = baseline(), SimpleNamespace(), context()
        proof = b.ASRPrefetchProof(3, 1000., len(BASE_PCM), hashlib.sha256(BASE_PCM).digest(), "zh")
        first = '{"content":"合成问题","emotion":"NEUTRAL"}'
        second = '{"content":"合成问题","emotion":"HAPPY"}'
        old = manager.baseline_asr_provisional(conn, audio=b.AudioStamp(3, 17, 0), text="合成问题",
            context=ctx, proof=proof, model_user_message=first)
        await drain()
        current = manager.baseline_asr_provisional(conn, audio=b.AudioStamp(3, 17, 0), text="合成问题",
            context=ctx, proof=proof, model_user_message=second)
        assert current.turn.transcript_revision == old.turn.transcript_revision + 1
        assert current.audio == old.audio
        assert await manager.baseline_confirmed(conn, binding=current, final_text="合成问题", context=ctx,
            final_pcm=BASE_PCM, generation=3, voice_stamp=1000., language="zh", model_user_message=second) is None
        assert manager.model.started == 1 and manager.model.requests[0].messages[-1][1] == first
        assert await manager.aclose()
    asyncio.run(run())
