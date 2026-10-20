"""平台来源优先的投递适配：不拆解引擎 add 的私有组合 pipeline。"""

from dataclasses import replace
from threading import RLock

from longmemory.methods.contracts import ObservationResult, UnsupportedCapabilityError


class ManagedMemoryMethod:
    """为新引擎保存来源和投递结果；旧引擎继续使用原有同库事务。

    助手仅归档，不投给用户事实引擎。archive 不派生，recall 不归档查询。
    失败不自动重放；跨存储提交窗口显示 uncertain，绝不保证 exactly-once。
    """

    def __init__(self, engine, journal):
        self.engine, self.journal = engine, journal
        self.name, self.implementation_version = engine.name, engine.implementation_version
        self.capabilities = replace(
            engine.capabilities, deferred_observation=True,
            failed_observation_recovery=engine.capabilities.idempotent_observation,
        )
        self.retrieval_name = getattr(engine, "retrieval_name", "method_defined")
        self._lock = RLock()
        self._closed = False

    def _check(self):
        if self._closed:
            raise RuntimeError("记忆方法已经关闭。")

    def archive(self, event):
        with self._lock:
            self._check()
            self.journal.archive(event)
            return ObservationResult(event.event_id, ())

    def _dispatch(self, event, *, retry=False, expected_attempt_id=None):
        attempt = self.journal.begin(event.event_id, retry=retry, expected_attempt_id=expected_attempt_id)
        try:
            if event.session_id is not None and not self.engine.capabilities.session_metadata:
                result = ObservationResult(event.event_id, None, "source_only", "engine_session_metadata_unsupported")
                self.journal.finish(event.event_id, attempt, result)
                return result
            result = self.engine.observe(event)
            if result.event_id != event.event_id:
                raise ValueError("engine_event_mismatch")
        except Exception:
            # 错误原文可能含私人正文或供应商凭据，只保存稳定原因码。
            result = ObservationResult(event.event_id, None, "source_only", "engine_observation_failed")
        # finish 若失败不能假称成功；重启后 running 会显示 uncertain。
        self.journal.finish(event.event_id, attempt, result)
        return result

    def defer_observation(self, event):
        with self._lock:
            self.archive(event)
            self.journal.defer(event.event_id)
            return ObservationResult(event.event_id, (), "source_only", "engine_observation_deferred")

    def observe(self, event):
        with self._lock:
            self._check()
            self.journal.archive(event)
            if event.role == "assistant":
                return ObservationResult(event.event_id, ())
            _, dispatch = self.journal.get(event.event_id)
            if dispatch["state"] == "completed":
                return self.journal.result(dispatch["result"])
            if dispatch["state"] not in {"archived", "pending"}:
                return ObservationResult(event.event_id, None, "source_only", "engine_explicit_retry_required")
            return self._dispatch(event)

    def complete_archived_observation(self, event):
        """Runtime 在同一锁内执行整个引擎调用；不要求外部拆开提取/持久化。"""
        return self.observe(event)

    def retry_observation(self, event_id, *, expected_attempt_id):
        with self._lock:
            self._check()
            event, status = self.journal.get(event_id)
            if status["state"] != "pending" and not self.engine.capabilities.idempotent_observation:
                raise UnsupportedCapabilityError("engine_retry_requires_idempotency")
            if event.role != "user":
                raise ValueError("source_retry_role_invalid")
            return self._dispatch(event, retry=True, expected_attempt_id=expected_attempt_id)

    def source_status(self, event_id):
        with self._lock:
            self._check()
            event, status = self.journal.get(event_id)
            return {"event_id": event.event_id, "role": event.role,
                    "occurred_at": event.occurred_at.isoformat(), **{
                        key: status[key] for key in ("state", "attempt_id")}}

    def source_detail(self, event_id):
        with self._lock:
            self._check()
            event, _ = self.journal.get(event_id)
            return {**self.source_status(event_id), "content": event.content,
                    "session_id": event.session_id}

    def recall(self, query):
        with self._lock:
            self._check()
            return self.engine.recall(query)

    def wait_until_ready(self):
        with self._lock:
            self._check()
            self.engine.wait_until_ready()

    def configure_background_writes(self, *, write_enabled):
        """显式穿透来源包装的后台写门；不归档事件、不把暂停变成一次observe。"""
        with self._lock:
            self._check()
            gate = getattr(self.engine, "configure_background_writes", None)
            if callable(gate):
                return gate(write_enabled=write_enabled)

    def candidate_snapshot(self, *, query_embedding, limit=5):
        """候选专用能力；不能通过来源包装器的普通recall猜测只读语义。"""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("candidate_memory_busy")
        try:
            self._check()
            snapshot = getattr(self.engine, "candidate_snapshot", None)
            if not callable(snapshot):
                raise UnsupportedCapabilityError("candidate_memory_unsupported")
            return snapshot(query_embedding=query_embedding, limit=limit)
        finally:
            self._lock.release()

    def candidate_validate(self, *, snapshot_token, memory_digest=None):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("candidate_memory_busy")
        try:
            self._check()
            validate = getattr(self.engine, "candidate_validate", None)
            if not callable(validate):
                raise UnsupportedCapabilityError("candidate_memory_unsupported")
            return validate(snapshot_token=snapshot_token, memory_digest=memory_digest)
        finally:
            self._lock.release()

    def close(self):
        with self._lock:
            if not self._closed:
                try:
                    self.engine.close()
                finally:
                    self.journal.close()
                    self._closed = True
