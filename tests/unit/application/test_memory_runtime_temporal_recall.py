from datetime import UTC, datetime

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.application.memory_runtime import MemoryRuntime
from longmemory.application.temporal_recall import (
    TemporalDateTarget,
    TemporalQueryIntent,
    TemporalRecallItem,
    TemporalRecallResult,
)
from longmemory.methods.contracts import (
    MemorySupport,
    MethodCapabilities,
    ObservationResult,
    RetrievedTrace,
)


class _CurrentMemoryMethod:
    name = "current-only"
    implementation_version = "test"
    capabilities = MethodCapabilities(source_trace=True)

    def observe(self, event):
        return ObservationResult(event.event_id, ())

    archive = observe

    def recall(self, _query):
        return MemorySupport(
            "call-current",
            "[当前 L1]\n用户住在合肥。",
            (RetrievedTrace("new-place", "用户住在合肥。", ("source-new",)),),
            "current-only",
        )

    def wait_until_ready(self):
        return None

    def close(self):
        return None


class _HistoricalProvider:
    def __init__(self):
        self.calls = []
        self.closed = False

    def recall(self, query, *, current_memory_ids, limit=10):
        self.calls.append((query, current_memory_ids, limit))
        return TemporalRecallResult(
            "[历史事实]\n用户住在南京。",
            (TemporalRecallItem(
                "old-place", "用户住在南京。",
                None, "2026-05-01T00:00:00+00:00",
                ("source-old",),
            ),),
            TemporalQueryIntent.HISTORY,
        )

    def close(self):
        self.closed = True


def test_runtime_adds_historical_trace_after_current_recall(tmp_path):
    provider = _HistoricalProvider()

    class Shadow:
        def __init__(self):
            self.calls = []

        def submit(self, **values):
            self.calls.append(values)

        def status(self):
            class Status:
                def to_dict(self):
                    return {"enabled": True, "state": "not_run"}
            return Status()

        def wait(self):
            return None

        def close(self):
            return None

    shadow = Shadow()
    runtime = MemoryRuntime(
        tmp_path / "unused.db",
        method=_CurrentMemoryMethod(),
        temporal_provider=provider,
        l1_sufficiency_shadow=shadow,
        clock=lambda: datetime(2026, 9, 13, tzinfo=UTC),
    )
    try:
        prepared = runtime.prepare_user("我以前住在哪里？")

        assert provider.calls == [("我以前住在哪里？", ("new-place",), 10)]
        assert "用户住在合肥" in prepared.support.context
        assert "用户住在南京" in prepared.support.context
        assert prepared.support.retrieval_strategy == (
            "current-only+explicit_temporal_history_v2"
        )
        historical = prepared.support.retrieved[1]
        assert historical.item_id == "old-place"
        assert historical.temporal_role == "historical"
        assert historical.valid_to == "2026-05-01T00:00:00+00:00"
        assert historical.source_event_ids == ("source-old",)
        assert runtime.status()["temporal_history_available"] is True
        assert [item.item_id for item in shadow.calls[0]["candidates"]] == [
            "new-place"
        ]
    finally:
        runtime.close()
    assert provider.closed is True


def test_runtime_filters_current_l1_when_date_has_no_evidence(tmp_path):
    class DateProvider(_HistoricalProvider):
        def recall(self, query, *, current_memory_ids, limit=10):
            self.calls.append((query, current_memory_ids, limit))
            target = TemporalDateTarget(
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 1, tzinfo=UTC),
                "2025年",
            )
            return TemporalRecallResult(
                "问题指定了2025年，但现有记忆不足以确定。", (),
                TemporalQueryIntent.DATE, "explicit_temporal_date_v1",
                target, (),
            )

    provider = DateProvider()
    runtime = MemoryRuntime(
        tmp_path / "unused.db", method=_CurrentMemoryMethod(),
        temporal_provider=provider,
    )
    try:
        prepared = runtime.prepare_user("2025年我住在哪里？")
        assert "现有记忆不足以确定" in prepared.support.context
        assert "用户住在合肥" not in prepared.support.context
        assert prepared.support.retrieved == ()
        assert prepared.support.retrieval_strategy == (
            "current-only+explicit_temporal_date_v1"
        )
        assert FakeAnswerGenerator().generate(
            query="2025年我的猫叫什么？",
            memory_context=prepared.support.context,
        ) == "我还没有找到相关记忆。"
    finally:
        runtime.close()


def test_runtime_date_uses_historical_l1_without_injecting_current_state(tmp_path):
    class DateProvider(_HistoricalProvider):
        def recall(self, query, *, current_memory_ids, limit=10):
            target = TemporalDateTarget(
                datetime(2026, 4, 1, tzinfo=UTC),
                datetime(2026, 5, 1, tzinfo=UTC),
                "2026年4月",
            )
            return TemporalRecallResult(
                "历史事实覆盖目标日期：\n- 用户住在南京。",
                (TemporalRecallItem(
                    "old-place", "用户住在南京。", None,
                    "2026-05-01T00:00:00+00:00", ("source-old",),
                ),),
                TemporalQueryIntent.DATE, "explicit_temporal_date_v1",
                target, (),
            )

    runtime = MemoryRuntime(
        tmp_path / "unused.db", method=_CurrentMemoryMethod(),
        temporal_provider=DateProvider(),
    )
    try:
        prepared = runtime.prepare_user("2026年4月我住在哪里？")
        assert "用户住在合肥" not in prepared.support.context
        assert "用户住在南京" in prepared.support.context
        assert [item.item_id for item in prepared.support.retrieved] == ["old-place"]
        assert prepared.support.retrieved[0].temporal_role == "historical"
    finally:
        runtime.close()


def test_runtime_keeps_current_l1_only_when_it_covers_date_target(tmp_path):
    class DateProvider(_HistoricalProvider):
        def recall(self, query, *, current_memory_ids, limit=10):
            target = TemporalDateTarget(
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2027, 1, 1, tzinfo=UTC),
                "2026年",
            )
            return TemporalRecallResult(
                "当前事实覆盖目标日期。", (), TemporalQueryIntent.DATE,
                "explicit_temporal_date_v1", target, ("new-place",),
            )

    class UnexpectedDerivedProvider:
        def recall(self, _query):
            raise AssertionError("明确日期问题不得注入无目标区间的 L2/L3")

        def close(self):
            return None

    runtime = MemoryRuntime(
        tmp_path / "unused.db", method=_CurrentMemoryMethod(),
        temporal_provider=DateProvider(),
        scenario_provider=UnexpectedDerivedProvider(),
        persona_provider=UnexpectedDerivedProvider(),
    )
    try:
        runtime.configure(
            write_enabled=True, use_enabled=True,
            scenario_use_enabled=True, persona_use_enabled=True,
        )
        prepared = runtime.prepare_user("2026年我住在哪里？")
        assert "用户住在合肥" in prepared.support.context
        assert [item.item_id for item in prepared.support.retrieved] == ["new-place"]
        assert prepared.scenarios == ()
        assert prepared.personas == ()
    finally:
        runtime.close()
