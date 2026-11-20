from datetime import UTC, datetime

from longmemory.application.memory_runtime import MemoryRuntime
from longmemory.application.temporary_interaction import (
    classify_next_turn_interaction,
    directive_context,
)
from longmemory.methods.contracts import (
    MemorySupport,
    MethodCapabilities,
    ObservationResult,
)


NOW = datetime(2026, 9, 10, 4, 0, tzinfo=UTC)


def test_directive_context_is_fixed_and_does_not_include_source_text():
    context = directive_context("listen_only")
    assert "只倾听" in context
    assert "用户今天只想让你听我说" not in context


def test_next_turn_classifier_is_explicit_and_does_not_accept_extra_text():
    assert classify_next_turn_interaction("下一轮只听我说。") == "listen_only"
    assert classify_next_turn_interaction("下一轮先问我要不要建议") == "ask_before_advice"
    assert classify_next_turn_interaction("下一轮直接给我建议") == "direct_advice"
    assert classify_next_turn_interaction("取消下一轮互动方式") == "cancel"
    assert classify_next_turn_interaction("下一轮只听我说，我今天很累") is None


class EmptyMethod:
    name = "synthetic"
    implementation_version = "1"
    capabilities = MethodCapabilities(source_trace=True)

    def __init__(self):
        self.observed = []
        self.archived = []

    def observe(self, event):
        self.observed.append(event)
        return ObservationResult(event.event_id, ())

    def archive(self, event):
        self.archived.append(event)
        return ObservationResult(event.event_id, ())

    def recall(self, _query):
        return MemorySupport("call-1", "", (), "synthetic", None)

    def wait_until_ready(self):
        pass

    def close(self):
        pass


def test_next_turn_mode_is_l0_only_consumed_once_then_default_resumes(tmp_path):
    method = EmptyMethod()
    runtime = MemoryRuntime(
        tmp_path / "unused.db", method=method, clock=lambda: NOW,
    )
    try:
        armed = runtime.prepare_user("下一轮直接给我建议")
        assert armed.memory_command.kind == "set_next_interaction"
        assert armed.memory_command.status == "armed"
        assert armed.temporary_interaction is None
        assert runtime.status()["next_interaction_armed"] is True
        assert len(method.archived) == 1
        assert method.observed == []

        used = runtime.prepare_user("最近项目总是推进不下去")
        assert used.temporary_interaction.mode == "direct_advice"
        assert used.temporary_interaction.scope == "next_turn"
        assert used.temporary_interaction.source_memory_id is None
        assert used.support.retrieval_strategy == (
            "synthetic+temporary_interaction_next_turn_v1"
        )
        assert runtime.status()["next_interaction_armed"] is False

        resumed = runtime.prepare_user("我还有点担心")
        assert resumed.temporary_interaction is None
    finally:
        runtime.close()


def test_next_turn_mode_can_be_cancelled_before_consumption(tmp_path):
    runtime = MemoryRuntime(
        tmp_path / "unused.db", method=EmptyMethod(), clock=lambda: NOW,
    )
    try:
        runtime.prepare_user("下一轮直接给我建议")
        cancelled = runtime.prepare_user("取消下一轮互动方式")
        assert cancelled.memory_command.status == "applied"
        assert cancelled.temporary_interaction is None

        following = runtime.prepare_user("我最近有点累")
        assert following.temporary_interaction is None
    finally:
        runtime.close()
