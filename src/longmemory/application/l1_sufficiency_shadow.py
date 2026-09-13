"""L1 证据充分性影子运行器；只记录旁路判断，不改变回答上下文。"""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol

from longmemory.core.memory.retrieval.sufficiency import (
    EvidenceCandidate,
    EvidenceSufficiencyError,
    EvidenceSufficiencyGate,
    EvidenceSufficiencyInput,
    EvidenceSufficiencyReview,
)
from longmemory.methods.contracts import RetrievedTrace


class L1SufficiencyShadowStore(Protocol):
    """持久化边界只接受已召回 L1 快照，不能修改记忆或回答。"""

    def start(self, *, user_message_id: str, candidates: tuple[RetrievedTrace, ...],
              retrieval_strategy: str, reviewer_version: str,
              prompt_sha256: str, provider: str, model: str,
              requested_at: datetime) -> bool: ...

    def complete(self, *, user_message_id: str,
                 review: EvidenceSufficiencyReview,
                 completed_at: datetime) -> None: ...

    def complete_empty(self, *, user_message_id: str,
                       completed_at: datetime) -> None: ...

    def fail(self, *, user_message_id: str, error_code: str,
             completed_at: datetime) -> None: ...


@dataclass(frozen=True, slots=True)
class L1SufficiencyShadowStatus:
    state: str
    submitted: int
    completed: int
    failed: int
    running_or_queued: int
    last_error_code: str | None

    def to_dict(self) -> dict:
        return {
            "enabled": True,
            "state": self.state,
            "submitted": self.submitted,
            "completed": self.completed,
            "failed": self.failed,
            "running_or_queued": self.running_or_queued,
            "last_error_code": self.last_error_code,
        }


class L1SufficiencyShadowObserver:
    """单线程复核同轮 L1；模型、队列或落库失败都不影响聊天。"""

    def __init__(self, *, gate: EvidenceSufficiencyGate,
                 store: L1SufficiencyShadowStore, prompt_sha256: str,
                 provider: str, model: str, clock=None) -> None:
        self._gate = gate
        self._store = store
        self._prompt_sha256 = prompt_sha256
        self._provider = provider
        self._model = model
        self._clock = clock or (lambda: datetime.now(UTC))
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="longmemory-l1-sufficiency-shadow",
        )
        self._lock = Lock()
        self._futures: set[Future] = set()
        self._submitted = self._completed = self._failed = 0
        self._last_error_code: str | None = None
        self._closed = False

    def submit(self, *, user_message_id: str, query: str,
               candidates: tuple[RetrievedTrace, ...],
               retrieval_strategy: str) -> bool:
        """快照提交后立即返回；正式回答不等待模型复核。"""

        with self._lock:
            if self._closed:
                return False
            future = self._executor.submit(
                self._run, user_message_id, query, candidates,
                retrieval_strategy,
            )
            self._futures.add(future)
            self._submitted += 1
        future.add_done_callback(self._done)
        return True

    def _run(self, user_message_id: str, query: str,
             candidates: tuple[RetrievedTrace, ...],
             retrieval_strategy: str) -> None:
        started = self._store.start(
            user_message_id=user_message_id,
            candidates=candidates,
            retrieval_strategy=retrieval_strategy,
            reviewer_version=self._gate.version,
            prompt_sha256=self._prompt_sha256,
            provider=self._provider,
            model=self._model,
            requested_at=self._clock(),
        )
        if not started:
            return
        if not candidates:
            self._store.complete_empty(
                user_message_id=user_message_id,
                completed_at=self._clock(),
            )
            return
        try:
            review = self._gate.review(EvidenceSufficiencyInput(
                query=query,
                candidates=tuple(
                    EvidenceCandidate(item.item_id, item.content)
                    for item in candidates
                ),
            ))
        except EvidenceSufficiencyError as error:
            code = str(error) or "evidence_sufficiency_review_failed"
            self._store.fail(
                user_message_id=user_message_id,
                error_code=code,
                completed_at=self._clock(),
            )
            raise
        self._store.complete(
            user_message_id=user_message_id,
            review=review,
            completed_at=self._clock(),
        )

    def _done(self, future: Future) -> None:
        try:
            future.result()
        except BaseException as error:
            failed, code = 1, (
                str(error) if isinstance(error, EvidenceSufficiencyError)
                else "l1_sufficiency_shadow_failed"
            )
        else:
            failed, code = 0, None
        with self._lock:
            self._futures.discard(future)
            self._completed += 1 - failed
            self._failed += failed
            self._last_error_code = code

    def status(self) -> L1SufficiencyShadowStatus:
        with self._lock:
            running = len(self._futures)
            state = "running" if running else (
                "failed" if self._last_error_code else
                "completed" if self._completed else "not_run"
            )
            return L1SufficiencyShadowStatus(
                state, self._submitted, self._completed, self._failed,
                running, self._last_error_code,
            )

    def wait(self) -> None:
        """仅供测试和受控停机等待已提交任务。"""

        while True:
            with self._lock:
                futures = tuple(self._futures)
            if not futures:
                return
            for future in futures:
                try:
                    future.result()
                except EvidenceSufficiencyError:
                    pass

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)
