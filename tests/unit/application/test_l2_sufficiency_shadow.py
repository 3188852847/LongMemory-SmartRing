"""L2 影子门控的后台、失败隔离和无候选行为。"""

from datetime import UTC, datetime
from threading import Event

from longmemory.application.l2_sufficiency_shadow import (
    L2SufficiencyShadowObserver,
)
from longmemory.application.scenario_recall import (
    ScenarioRecallItem,
    ScenarioRecallResult,
)
from longmemory.core.memory.retrieval.sufficiency import (
    EvidenceSufficiencyDecision,
    EvidenceSufficiencyError,
    EvidenceSufficiencyReview,
)


class RecordingStore:
    def __init__(self):
        self.events = []

    def start(self, **values):
        self.events.append(("start", values))
        return True

    def complete(self, **values):
        self.events.append(("complete", values))

    def complete_empty(self, **values):
        self.events.append(("complete_empty", values))

    def fail(self, **values):
        self.events.append(("fail", values))


def _candidates():
    return ScenarioRecallResult("ignored", (ScenarioRecallItem(
        "scene-a", "答辩", "用户周五答辩。", (), (), keyword_score=1,
    ),))


def test_shadow_submit_returns_before_gate_and_records_completion():
    release = Event()

    class Gate:
        version = "gate-v1"

        def review(self, value):
            assert value.query == "我什么时候答辩"
            release.wait(timeout=2)
            return EvidenceSufficiencyReview((EvidenceSufficiencyDecision(
                "scene-a", True, "direct_support",
            ),), self.version)

    store = RecordingStore()
    observer = L2SufficiencyShadowObserver(
        gate=Gate(), store=store, prompt_sha256="a" * 64,
        provider="synthetic", model="synthetic", clock=lambda: datetime.now(UTC),
    )
    try:
        assert observer.submit(
            user_message_id="turn-a", query="我什么时候答辩",
            candidates=_candidates(),
        ) is True
        assert observer.status().running_or_queued == 1
        release.set()
        observer.wait()
        assert [name for name, _values in store.events] == ["start", "complete"]
        assert observer.status().completed == 1
    finally:
        release.set()
        observer.close()


def test_shadow_failure_is_stable_and_zero_candidates_skip_gate():
    class Gate:
        version = "gate-v1"

        def __init__(self):
            self.calls = 0

        def review(self, _value):
            self.calls += 1
            raise EvidenceSufficiencyError("evidence_sufficiency_http_error")

    gate, store = Gate(), RecordingStore()
    observer = L2SufficiencyShadowObserver(
        gate=gate, store=store, prompt_sha256="a" * 64,
        provider="synthetic", model="synthetic",
    )
    try:
        observer.submit(user_message_id="failed", query="问题", candidates=_candidates())
        observer.wait()
        assert observer.status().failed == 1
        assert observer.status().last_error_code == "evidence_sufficiency_http_error"
        observer.submit(
            user_message_id="empty", query="未知问题",
            candidates=ScenarioRecallResult("", ()),
        )
        observer.wait()
        assert gate.calls == 1
        assert [name for name, _ in store.events][-2:] == ["start", "complete_empty"]
    finally:
        observer.close()
