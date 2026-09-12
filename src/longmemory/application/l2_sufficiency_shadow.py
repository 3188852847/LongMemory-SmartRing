"""L2 证据充分性影子运行器；只记录旁路判断，不改变回答上下文。"""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol

from longmemory.application.scenario_recall import ScenarioRecallResult
from longmemory.core.memory.retrieval.sufficiency import (
    EvidenceCandidate,
    EvidenceSufficiencyError,
    EvidenceSufficiencyGate,
    EvidenceSufficiencyInput,
    EvidenceSufficiencyReview,
)


class L2SufficiencyShadowStore(Protocol):
    """影子审计的最小持久化边界；实现不得修改 L2 或聊天正文。"""

    def start(self, *, user_message_id: str, candidates: ScenarioRecallResult,
              reviewer_version: str, prompt_sha256: str, provider: str,
              model: str, requested_at: datetime) -> bool: ...

    def complete(self, *, user_message_id: str,
                 review: EvidenceSufficiencyReview,
                 completed_at: datetime) -> None: ...

    def complete_empty(self, *, user_message_id: str,
                       completed_at: datetime) -> None: ...

    def fail(self, *, user_message_id: str, error_code: str,
             completed_at: datetime) -> None: ...


@dataclass(frozen=True, slots=True)
class L2SufficiencyShadowStatus:
    """只暴露计数和稳定错误码，不返回用户问题或候选正文。"""

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


class L2SufficiencyShadowObserver:
    """单线程旁路复核同轮 L2 候选；模型失败不会影响正式回答。"""

    def __init__(self, *, gate: EvidenceSufficiencyGate,
                 store: L2SufficiencyShadowStore, prompt_sha256: str,
                 provider: str, model: str, clock=None) -> None:
        self._gate = gate
        self._store = store
        self._prompt_sha256 = prompt_sha256
        self._provider = provider
        self._model = model
        self._clock = clock or (lambda: datetime.now(UTC))
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="longmemory-l2-shadow",
        )
        self._lock = Lock()
        self._futures: set[Future] = set()
        self._submitted = self._completed = self._failed = 0
        self._last_error_code: str | None = None
        self._closed = False

    def submit(self, *, user_message_id: str, query: str,
               candidates: ScenarioRecallResult) -> bool:
        """提交候选快照后立即返回；不等待审计落库或模型完成。"""

        with self._lock:
            if self._closed:
                return False
            future = self._executor.submit(
                self._run, user_message_id, query, candidates,
            )
            self._futures.add(future)
            self._submitted += 1
        # 极快任务可能在注册回调前已经完成，此时 Python 会在当前线程
        # 同步执行回调；因此必须离开状态锁后注册，避免回调再次取锁自锁。
        future.add_done_callback(self._done)
        return True

    def _run(self, user_message_id: str, query: str,
             candidates: ScenarioRecallResult) -> None:
        started = self._store.start(
            user_message_id=user_message_id,
            candidates=candidates,
            reviewer_version=self._gate.version,
            prompt_sha256=self._prompt_sha256,
            provider=self._provider,
            model=self._model,
            requested_at=self._clock(),
        )
        if not started:
            return
        if not candidates.items:
            self._store.complete_empty(
                user_message_id=user_message_id,
                completed_at=self._clock(),
            )
            return
        try:
            review = self._gate.review(EvidenceSufficiencyInput(
                query=query,
                candidates=tuple(EvidenceCandidate(
                    item.scenario_id, f"{item.title}：{item.summary}",
                ) for item in candidates.items),
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
                else "l2_sufficiency_shadow_failed"
            )
        else:
            failed, code = 0, None
        with self._lock:
            self._futures.discard(future)
            self._completed += 1 - failed
            self._failed += failed
            self._last_error_code = code

    def status(self) -> L2SufficiencyShadowStatus:
        with self._lock:
            running = len(self._futures)
            state = "running" if running else (
                "failed" if self._last_error_code else
                "completed" if self._completed else "not_run"
            )
            return L2SufficiencyShadowStatus(
                state, self._submitted, self._completed, self._failed,
                running, self._last_error_code,
            )

    def wait(self) -> None:
        """仅供测试和受控停机等待已经提交的影子任务。"""

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
