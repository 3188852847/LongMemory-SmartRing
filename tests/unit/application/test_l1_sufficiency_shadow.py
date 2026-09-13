"""L1 影子复核异步运行，并且失败与聊天隔离。"""

from datetime import UTC, datetime
from threading import Event

from longmemory.application.l1_sufficiency_shadow import (
    L1SufficiencyShadowObserver,
)
from longmemory.core.memory.retrieval.sufficiency import (
    EvidenceSufficiencyDecision,
    EvidenceSufficiencyError,
    EvidenceSufficiencyReview,
)
from longmemory.methods.contracts import RetrievedTrace


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


def _candidate():
    return (RetrievedTrace("memory-a", "用户的猫叫豆包。", ("l0-a",), 2),)


def test_l1_shadow_returns_before_gate_and_preserves_retrieval_metadata():
    release = Event()

    class Gate:
        version = "gate-v1"

        def review(self, value):
            assert value.query == "我的猫叫什么"
            release.wait(timeout=2)
            return EvidenceSufficiencyReview((EvidenceSufficiencyDecision(
                "memory-a", True, "direct_support",
            ),), self.version)

    store = RecordingStore()
    observer = L1SufficiencyShadowObserver(
        gate=Gate(), store=store, prompt_sha256="a" * 64,
        provider="synthetic", model="synthetic",
        clock=lambda: datetime.now(UTC),
    )
    try:
        assert observer.submit(
            user_message_id="turn-a", query="我的猫叫什么",
            candidates=_candidate(), retrieval_strategy="hybrid-v1",
        )
        assert observer.status().running_or_queued == 1
        release.set()
        observer.wait()
        assert [name for name, _ in store.events] == ["start", "complete"]
        assert store.events[0][1]["retrieval_strategy"] == "hybrid-v1"
        assert observer.status().completed == 1
    finally:
        release.set()
        observer.close()


def test_l1_shadow_failure_is_stable_and_empty_candidates_skip_gate():
    class Gate:
        version = "gate-v1"

        def __init__(self):
            self.calls = 0

        def review(self, _value):
            self.calls += 1
            raise EvidenceSufficiencyError("evidence_sufficiency_http_error")

    gate, store = Gate(), RecordingStore()
    observer = L1SufficiencyShadowObserver(
        gate=gate, store=store, prompt_sha256="b" * 64,
        provider="synthetic", model="synthetic",
    )
    try:
        observer.submit(user_message_id="failed", query="问题",
                        candidates=_candidate(), retrieval_strategy="keyword-v1")
        observer.wait()
        assert observer.status().last_error_code == "evidence_sufficiency_http_error"
        observer.submit(user_message_id="empty", query="未知问题",
                        candidates=(), retrieval_strategy="keyword-v1")
        observer.wait()
        assert gate.calls == 1
        assert [name for name, _ in store.events][-2:] == ["start", "complete_empty"]
    finally:
        observer.close()
