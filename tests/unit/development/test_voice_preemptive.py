"""CPU/内存中的候选生命周期回放；不连接服务或个人库。"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import importlib.util
from pathlib import Path
import sqlite3
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/development/xiaozhi/voice_preemptive.py"
SPEC = importlib.util.spec_from_file_location("ae_voice_preemptive", SCRIPT)
p = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = p
SPEC.loader.exec_module(p)


def context(**versions):
    values = dict(memory_revision="engine-instance:m0", context_revision="c0",
                  tools_revision="none:t0", policy_revision="school-role:p0")
    values.update(versions)
    return p.ContextSnapshot(p.SnapshotVersion(**values),
                             (("system", "合成角色，直接回答。"), ("assistant", "请说。")))


def stamp(turn=1, revision=1, epoch=0):
    return p.TurnStamp(turn, revision, epoch)


class FakeModel:
    billing_class = "campus_free_verified"
    automatic_retries = False

    def __init__(self, *, text="合成回答。", gate=None, close_gate=None,
                 ignore_cancel=False, usage=True, error=None):
        self.text, self.gate, self.close_gate = text, gate, close_gate
        self.ignore_cancel, self.error = ignore_cancel, error
        self.usage = {"prompt_tokens": 10, "completion_tokens": 4} if usage else None
        self.started = self.closed = 0
        self.entered, self.exiting = asyncio.Event(), asyncio.Event()
        self.requests = []

    @asynccontextmanager
    async def open(self, request):
        self.requests.append(request)
        self.started += 1
        self.entered.set()
        try:
            yield self
        finally:
            self.exiting.set()
            if self.close_gate is not None:
                await self.close_gate.wait()
            self.closed += 1

    async def __aiter__(self):
        if self.gate is not None:
            try:
                await self.gate.wait()
            except asyncio.CancelledError:
                if not self.ignore_cancel:
                    raise
                await self.gate.wait()
        if self.error is not None:
            raise self.error
        yield self.text


def controller(model=None, budget=None, **limits):
    return p.VoicePreemptive(model or FakeModel(), budget or p.RequestBudget(),
                             limits=p.Limits(enabled=True, **limits))


async def drain():
    for _ in range(4):
        await asyncio.sleep(0)


def test_imports_resolve_to_assigned_worktree():
    import longmemory
    assert Path(p.__file__).resolve() == SCRIPT.resolve()
    assert Path(longmemory.__file__).resolve().is_relative_to(ROOT / "src")


def test_default_disabled_and_unverified_or_retrying_routes_never_start():
    async def run():
        model = FakeModel()
        disabled = p.VoicePreemptive(model, p.RequestBudget())
        assert not disabled.provisional(turn=stamp(), transcript="合成问题", context=context())
        for billing, retries in (("paid", False), ("unverified", False), ("campus_free_verified", True)):
            model.billing_class, model.automatic_retries = billing, retries
            c = controller(model)
            assert not c.provisional(turn=stamp(), transcript="合成问题", context=context())
            assert c.snapshot()["skipped_policy"] == 1
        await drain()
        assert model.started == 0
    asyncio.run(run())


def test_candidate_is_invisible_until_confirmed_and_claimed_once():
    async def run():
        model, ctx, turn = FakeModel(), context(), stamp()
        c = controller(model)
        assert c.provisional(turn=turn, transcript="合成问题", context=ctx)
        await drain()
        assert c.snapshot()["ready"] == 1
        assert c.snapshot()["hits"] == 0
        assert model.closed == 1
        lease = await c.confirmed(turn=turn, transcript="合成问题", context=ctx)
        assert lease.claim(turn=turn, context=ctx) == "合成回答。"
        assert lease.claim(turn=turn, context=ctx) is None
        assert c.snapshot()["hits"] == 1
        assert c.snapshot()["observed_output_tokens"] == 4
        assert await c.aclose()
    asyncio.run(run())


def test_duplicate_and_revised_transcript_never_retry_this_turn():
    async def run():
        model, ctx = FakeModel(), context()
        c = controller(model)
        assert c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        assert not c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        await drain()
        assert not c.provisional(turn=stamp(revision=2), transcript="合成问题续句", context=ctx)
        assert await c.confirmed(turn=stamp(revision=2), transcript="合成问题续句", context=ctx) is None
        assert model.started == 1
        assert c.snapshot()["discarded"] == 1
        assert await c.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("change", ["revision", "text", "epoch", "memory", "context", "tools", "policy", "messages"])
def test_confirmation_requires_exact_input_and_snapshot(change):
    async def run():
        ctx, turn, text = context(), stamp(), "合成问题"
        c = controller()
        c.provisional(turn=turn, transcript=text, context=ctx)
        await drain()
        if change == "revision":
            turn = stamp(revision=2)
        elif change == "text":
            text += "续句"
        elif change == "epoch":
            turn = stamp(epoch=1)
        elif change == "messages":
            ctx = replace(ctx, messages=(("system", "变更角色"),))
        else:
            ctx = context(**{change + "_revision": "changed"})
        assert await c.confirmed(turn=turn, transcript=text, context=ctx) is None
        assert c.snapshot()["discarded"] == 1
        assert await c.aclose()
    asyncio.run(run())


def test_continued_wakes_confirmation_even_if_stream_ignores_cancel():
    async def run():
        gate, ctx, turn = asyncio.Event(), context(), stamp()
        model = FakeModel(gate=gate, ignore_cancel=True, usage=False)
        budget = p.RequestBudget()
        c = controller(model, budget)
        c.provisional(turn=turn, transcript="合成问题", context=ctx)
        await model.entered.wait()
        confirm = asyncio.create_task(c.confirmed(turn=turn, transcript="合成问题", context=ctx))
        await drain()
        c.continued(turn_id=1, cancel_epoch=1)
        assert await asyncio.wait_for(confirm, 1) is None
        assert budget.active == 1  # 实际流尚未退出，不能虚报空闲。
        other = controller(FakeModel(), budget)
        assert not other.provisional(turn=stamp(2, epoch=1), transcript="新合成问题", context=ctx)
        assert other.snapshot()["skipped_busy"] == 1
        assert not await c.aclose(timeout_seconds=0.01)
        gate.set()
        await drain()
        assert model.closed == 1 and budget.active == 0
        assert c.snapshot()["unknown_usage"] == 1
        assert c.snapshot()["hits"] == 0
        assert await c.aclose()
        assert await other.aclose()
    asyncio.run(run())


def test_response_close_retains_slot_and_ready_waits_for_close():
    async def run():
        close_gate = asyncio.Event()
        model, budget, ctx = FakeModel(close_gate=close_gate), p.RequestBudget(), context()
        c = controller(model, budget)
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        await model.exiting.wait()
        assert budget.active == 1 and c.snapshot()["ready"] == 0
        close_gate.set()
        lease = await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx)
        assert lease.claim(turn=stamp(), context=ctx)
        assert model.closed == 1 and budget.active == 0
        assert await c.aclose()
    asyncio.run(run())


def test_timeout_during_response_cleanup_does_not_cancel_cleanup_or_release_slot():
    async def run():
        close_gate, ctx = asyncio.Event(), context()
        model = FakeModel(close_gate=close_gate)
        c = controller(model, timeout_seconds=0.02)
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        await model.exiting.wait()
        assert await asyncio.wait_for(c.confirmed(turn=stamp(), transcript="合成问题", context=ctx), 1) is None
        assert model.closed == 0 and c.budget.active == 1
        assert not await c.aclose(timeout_seconds=0.01)
        close_gate.set()
        assert await c.aclose()
        assert model.closed == 1 and c.budget.active == 0
        assert c.snapshot()["ready"] == 0
    asyncio.run(run())


def test_cancel_after_confirmation_before_dispatch_invalidates_lease():
    async def run():
        c, ctx = controller(), context()
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        lease = await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx)
        c.continued(turn_id=1, cancel_epoch=1)
        assert lease.claim(turn=stamp(), context=ctx) is None
        assert c.snapshot()["hits"] == 0
        assert await c.aclose()
    asyncio.run(run())


def test_new_turn_out_of_order_events_and_restart_do_not_reuse_candidate():
    async def run():
        c, ctx = controller(), context()
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        old = await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx)
        assert c.provisional(turn=stamp(2), transcript="新合成问题", context=ctx)
        c.continued(turn_id=1, cancel_epoch=0)  # 迟到旧轮事件不能杀死新轮。
        assert old.claim(turn=stamp(), context=ctx) is None
        lease = await c.confirmed(turn=stamp(2), transcript="新合成问题", context=ctx)
        assert lease.claim(turn=stamp(2), context=ctx)
        assert not c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        assert await c.aclose()
        restarted = controller()
        assert await restarted.confirmed(turn=stamp(), transcript="合成问题", context=ctx) is None
        assert await restarted.aclose()
    asyncio.run(run())


def test_timeout_is_bounded_without_waiting_for_transport_ack():
    async def run():
        gate, ctx = asyncio.Event(), context()
        model = FakeModel(gate=gate, ignore_cancel=True)
        c = controller(model, timeout_seconds=0.02)
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        await model.entered.wait()
        assert await asyncio.wait_for(c.confirmed(turn=stamp(), transcript="合成问题", context=ctx), 1) is None
        assert c.snapshot()["timeouts"] == 1 and c.budget.active == 1
        gate.set()
        assert await c.aclose()
        assert c.snapshot()["ready"] == 0
    asyncio.run(run())


def test_ready_expires_and_context_update_revokes_immediately():
    async def run():
        ctx = context()
        # Windows 计时器粒度可能超过 10ms；留出确认回调运行的实际时间。
        c = controller(ready_ttl_seconds=0.2)
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        lease = await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx)
        await asyncio.sleep(0.25)
        assert lease.claim(turn=stamp(), context=ctx) is None
        assert c.snapshot()["state"] == "expired"
        assert await c.aclose()
        c = controller()
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        lease = await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx)
        c.context_changed(context(tools_revision="changed").version)
        assert lease.claim(turn=stamp(), context=ctx) is None
        assert await c.aclose()
    asyncio.run(run())


def test_cancelling_confirm_waiter_cancels_candidate_and_closes_response():
    async def run():
        model, ctx = FakeModel(gate=asyncio.Event()), context()
        c = controller(model)
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        await model.entered.wait()
        confirm = asyncio.create_task(c.confirmed(turn=stamp(), transcript="合成问题", context=ctx))
        await drain()
        confirm.cancel()
        with pytest.raises(asyncio.CancelledError):
            await confirm
        assert await c.aclose()
        assert model.closed == 1 and c.budget.active == 0
    asyncio.run(run())


def test_budget_reservations_survive_cancel_and_no_auto_retry():
    async def run():
        budget, ctx, model = p.RequestBudget(max_requests=1), context(), FakeModel(usage=False)
        c = controller(model, budget)
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        await drain()
        c.cancel(turn_id=1, cancel_epoch=1)
        assert not c.provisional(turn=stamp(2, epoch=1), transcript="新问题", context=ctx)
        assert c.snapshot()["skipped_budget"] == 1
        assert model.started == 1 and budget.requests == 1
        assert budget.output_tokens == 256
        assert c.snapshot()["unknown_usage"] == 1
        assert c.snapshot()["discarded_reserved_output_tokens"] == 256
        assert await c.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("budget", [dict(max_input_chars=1), dict(max_reserved_output_tokens=1)])
def test_input_and_token_budget_do_not_start_model(budget):
    async def run():
        c = controller(budget=p.RequestBudget(**budget))
        assert not c.provisional(turn=stamp(), transcript="合成问题", context=context())
        assert c.snapshot()["started"] == 0
        assert await c.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("model", [dict(text=""), dict(text="x" * 2049), dict(error=RuntimeError("敏感供应商正文"))])
def test_empty_oversize_and_failure_fall_back_without_retry_or_sensitive_diagnostics(model):
    async def run():
        fake, ctx = FakeModel(**model), context()
        c = controller(fake)
        c.provisional(turn=stamp(), transcript="敏感合成问题", context=ctx)
        assert await c.confirmed(turn=stamp(), transcript="敏感合成问题", context=ctx) is None
        assert fake.started == fake.closed == 1
        assert c.snapshot()["failed"] == 1
        assert "敏感" not in repr(c.snapshot())
        assert ctx.digest not in repr(c.snapshot())
        assert await c.aclose()
    asyncio.run(run())


def test_no_candidate_archive_pending_memory_audio_or_subtitle_before_formal_claim(tmp_path):
    # 合成正式链路的副作用收据；候选模块没有这些能力，确认前数据库字节不变。
    database = tmp_path / "synthetic.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("create table formal_turns (text text)")
    before = database.read_bytes()
    outputs = []

    async def run():
        ctx, c = context(), controller()
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        await drain()
        assert database.read_bytes() == before and outputs == []
        c.continued(turn_id=1, cancel_epoch=1)
        assert await c.confirmed(turn=stamp(epoch=1), transcript="合成问题续句", context=ctx) is None
        assert database.read_bytes() == before and outputs == []
        assert c.provisional(turn=stamp(2, epoch=1), transcript="完整合成问题", context=ctx)
        lease = await c.confirmed(turn=stamp(2, epoch=1), transcript="完整合成问题", context=ctx)
        answer = lease.claim(turn=stamp(2, epoch=1), context=ctx)
        assert database.read_bytes() == before and outputs == []
        # 仅测试装配器模拟正式提交；不代表生产接线已经完成。
        with sqlite3.connect(database) as db:
            db.execute("insert into formal_turns values (?)", (answer,))
        outputs.append(("formal_subtitle_and_audio", answer))
        assert await c.aclose()
    asyncio.run(run())
    with sqlite3.connect(database) as db:
        assert db.execute("select count(*) from formal_turns").fetchone()[0] == 1
    assert len(outputs) == 1


def test_confirmed_without_candidate_forbids_late_provisional():
    async def run():
        c, ctx = controller(), context()
        assert await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx) is None
        assert not c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        assert c.model.started == 0
        assert await c.aclose()
    asyncio.run(run())


def test_snapshot_immutable_and_system_order_or_tool_histories_fail_closed():
    ctx = context()
    with pytest.raises(Exception):
        ctx.messages += (("user", "修改"),)
    for messages in ([[("system", "可变")]], (("user", "非system起始"),),
                     (("system", "一"), ("system", "二")),
                     (("system", "一"), ("tool", "外部工具"))):
        with pytest.raises(ValueError):
            p.ContextSnapshot(ctx.version, messages)


def test_normal_prepare_object_is_rejected_without_reading_its_attributes():
    class UnsafePrepare:
        @property
        def messages(self):
            raise AssertionError("不能触碰普通prepare结果或惰性查询属性")

    async def run():
        c = controller()
        with pytest.raises(ValueError, match="frozen_snapshot_required"):
            c.provisional(turn=stamp(), transcript="合成问题", context=UnsafePrepare())
        with pytest.raises(ValueError, match="frozen_snapshot_required"):
            await c.confirmed(turn=stamp(), transcript="合成问题", context=UnsafePrepare())
        assert c.model.started == 0
        assert await c.aclose()
    asyncio.run(run())


def test_dispatch_mismatch_irreversibly_revokes_old_lease():
    async def run():
        c, ctx = controller(), context()
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        lease = await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx)
        assert lease.claim(turn=stamp(), context=context(memory_revision="changed")) is None
        assert lease.claim(turn=stamp(), context=ctx) is None
        assert c.snapshot()["state"] == "mismatch"
        assert await c.aclose()
    asyncio.run(run())


def test_one_budget_cannot_be_reused_from_another_event_loop():
    budget = p.RequestBudget()
    async def reserve():
        budget.reserve(1, 1)
        budget.release()
    asyncio.run(reserve())
    with pytest.raises(RuntimeError, match="event_loop_mismatch"):
        asyncio.run(reserve())


def test_cancel_before_worker_starts_releases_slot_without_call():
    async def run():
        model, cctx = FakeModel(), context()
        c = controller(model)
        assert c.provisional(turn=stamp(), transcript="合成问题", context=cctx)
        c.continued(turn_id=1, cancel_epoch=1)
        assert await c.aclose()
        assert model.started == 0 and c.budget.active == 0
        assert c.budget.requests == 1  # 已预留的累计限额不会凭取消返还。
    asyncio.run(run())


def test_late_cancel_resistant_old_result_cannot_override_new_candidate():
    async def run():
        gate, ctx = asyncio.Event(), context()
        old = FakeModel(text="旧结果", gate=gate, ignore_cancel=True)
        c = controller(old, p.RequestBudget(max_active=2))
        c.provisional(turn=stamp(), transcript="旧合成问题", context=ctx)
        await old.entered.wait()
        new = FakeModel(text="新结果")
        c.model = new  # 纯合成模型，为两请求注入独立的响应顺序。
        c.provisional(turn=stamp(2), transcript="新合成问题", context=ctx)
        lease = await c.confirmed(turn=stamp(2), transcript="新合成问题", context=ctx)
        gate.set()
        await drain()
        assert lease.claim(turn=stamp(2), context=ctx) == "新结果"
        assert c.snapshot()["ready"] == 1 and old.closed == new.closed == 1
        assert await c.aclose()
    asyncio.run(run())


def test_raw_begin_turn_and_asr_revision_revoke_without_retrieval_snapshot():
    async def run():
        c, ctx = controller(), context()
        c.begin_turn(turn_id=1, cancel_epoch=0)
        assert c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        lease = await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx)
        c.revised(turn=stamp(revision=2))
        assert lease.claim(turn=stamp(), context=ctx) is None
        assert not c.provisional(turn=stamp(revision=2), transcript="合成修订", context=ctx)
        c.begin_turn(turn_id=2, cancel_epoch=0)
        assert c.provisional(turn=stamp(2), transcript="新合成问题", context=ctx)
        lease = await c.confirmed(turn=stamp(2), transcript="新合成问题", context=ctx)
        c.begin_turn(turn_id=3, cancel_epoch=0)
        assert lease.claim(turn=stamp(2), context=ctx) is None
        assert c.provisional(turn=stamp(3), transcript="第三轮合成问题", context=ctx)
        c.context_changed()  # 只知道上下文变更时也能立即取消。
        assert await c.confirmed(turn=stamp(3), transcript="第三轮合成问题", context=ctx) is None
        assert await c.aclose()
    asyncio.run(run())


def test_message_count_overflow_is_rejected_before_reserving_capacity():
    async def run():
        ctx = replace(context(), messages=(("system", "合成角色"),) + (("assistant", "合成历史"),) * 127)
        c = controller()
        assert not c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        assert c.budget.active == c.budget.requests == 0
        assert c.snapshot()["skipped_size"] == 1
        assert await c.aclose()
    asyncio.run(run())


def test_context_manager_suppression_cannot_promote_partial_answer():
    class SuppressingModel(FakeModel):
        @asynccontextmanager
        async def open(self, request):
            self.started += 1
            try:
                yield self
            except OSError:
                pass
            finally:
                self.closed += 1

        async def __aiter__(self):
            yield "未完成的合成片段"
            raise OSError("模拟读取中断")

    async def run():
        model, ctx = SuppressingModel(), context()
        c = controller(model)
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        assert await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx) is None
        assert model.started == model.closed == 1
        assert c.snapshot()["ready"] == 0
        assert await c.aclose()
    asyncio.run(run())
