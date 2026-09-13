from datetime import UTC, datetime

from longmemory.application.memory_runtime import MemoryRuntime
from longmemory.application.temporal_recall import (
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
