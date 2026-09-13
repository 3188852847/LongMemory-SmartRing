"""日常模型辅助提取：L0 优先持久化，L1 失败显式降级。"""

from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from time import perf_counter
from uuid import uuid4

from longmemory.adapters.storage.sqlite_l1_extraction_audit import (
    L1ExtractionAuditMetadata,
    SQLiteL1ExtractionAuditStore,
)
from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.core.memory.extraction.candidates import (
    CandidateExtractionError,
    CandidateExtractionService,
    PREPROCESSOR_VERSION,
)
from longmemory.core.memory.l1_atomic.models import (
    AtomicMemory,
    CURRENT_USER_SUBJECT_ID,
    MemoryOperationType,
)
from longmemory.core.memory.extraction.temporary_scope import explicit_temporary_window
from longmemory.methods.contracts import (
    MemoryEvent, MethodCapabilities,
    ObservationResult,
    UnsupportedCapabilityError,
    WriteTrace,
)
from longmemory.methods.longmemory_v1.method import LongMemoryV1


class DailyLLMMemory:
    """只替换 L1 提取，存储、去重和关键词召回继续沿用 v1。

    与冻结实验方法的关键区别是先提交 L0。候选模型不可用或返回非法结构
    时，本轮仍可继续召回和回答，但结果会明确标记为 source_only。
    """

    name = "longmemory_daily_llm_v2"
    implementation_version = "1"
    capabilities = MethodCapabilities(
        source_trace=True,
        deferred_observation=True,
        failed_observation_recovery=True,
    )

    def __init__(
        self,
        database_path: Path,
        *,
        producer,
        existing_only: bool = True,
        allow_cross_thread: bool = False,
        retriever_factory=None,
        audit_metadata: L1ExtractionAuditMetadata | None = None,
    ) -> None:
        if producer is None:
            raise ValueError("日常模型提取必须显式提供候选生成器。")
        self._base = LongMemoryV1(
            database_path,
            existing_only=existing_only,
            allow_cross_thread=allow_cross_thread,
            retriever_factory=retriever_factory,
        )
        self._extractor = CandidateExtractionService(producer)
        self._audit_store = SQLiteL1ExtractionAuditStore(self._base.connection)
        self._audit_metadata = audit_metadata or L1ExtractionAuditMetadata(
            method_version=self.implementation_version,
            prompt_version=None,
            preprocessor_version=PREPROCESSOR_VERSION,
            prompt_sha256=None,
            provider="synthetic",
            model="synthetic",
        )
        # 模型调用与最终写库分处两个阶段；只在内存中关联本进程的尝试。
        # 若进程中途退出，数据库仍保留没有终态的 started 事件。
        self._pending_audits: dict[str, tuple[str, float]] = {}
        self.retrieval_name = self._base.retrieval_name

    def _start_audit(self, event: MemoryEvent) -> str | None:
        attempt_id = str(uuid4())
        try:
            self._audit_store.start(
                attempt_id=attempt_id,
                source_message_id=event.event_id,
                metadata=self._audit_metadata,
                occurred_at=datetime.now(UTC),
            )
        except sqlite3.Error:
            # 质量旁路不能让已经归档的 L0 或日常回答一起失败。
            return None
        self._pending_audits[event.event_id] = (attempt_id, perf_counter())
        return attempt_id

    def _finish_audit(self, event: MemoryEvent, *, phase: str, outcome_code: str,
                      candidate_count: int, added_count: int) -> None:
        pending = self._pending_audits.pop(event.event_id, None)
        if pending is None:
            return
        attempt_id, started = pending
        try:
            self._audit_store.finish(
                attempt_id=attempt_id,
                source_message_id=event.event_id,
                phase=phase,
                outcome_code=outcome_code,
                candidate_count=candidate_count,
                added_count=added_count,
                metadata=self._audit_metadata,
                occurred_at=datetime.now(UTC),
                duration_ms=(perf_counter() - started) * 1000,
            )
        except sqlite3.Error:
            # started 仍是诚实的“不完整尝试”，不能为补审计破坏主路径。
            pass

    def observe(self, event: MemoryEvent) -> ObservationResult:
        self._base._ensure_open()
        if event.session_id is not None:
            raise UnsupportedCapabilityError("当前日常 L1 尚不支持持久化会话元数据。")
        message = ConversationMessage(
            MessageId(event.event_id),
            MessageRole(event.role),
            event.content,
            event.occurred_at,
        )
        if message.role != MessageRole.USER:
            return self._base.observe(event)

        # 先归档不可替代的原始证据。后续模型或 L1 写入故障都不能回滚 L0。
        self._base.turn_service.archive(message)
        extracted = self.extract_archived(event)
        if isinstance(extracted, ObservationResult):
            return extracted
        return self.persist_archived(event, extracted)

    def extract_archived(
        self, event: MemoryEvent, *, start_audit: bool = True,
    ) -> tuple[AtomicMemory, ...] | ObservationResult:
        """只调用候选模型，不接触数据库，供受管延后队列使用。"""

        self._base._ensure_open()
        if event.session_id is not None:
            raise UnsupportedCapabilityError("当前日常 L1 尚不支持持久化会话元数据。")
        message = ConversationMessage(
            MessageId(event.event_id), MessageRole(event.role),
            event.content, event.occurred_at,
        )
        if message.role != MessageRole.USER:
            return ()
        if start_audit:
            self._start_audit(event)
        try:
            proposal = self._extractor.extract(message)
        except CandidateExtractionError:
            self._base.turn_service.report_extraction_failure(
                message, code="l1_extraction_failed"
            )
            self._finish_audit(
                event, phase="failed", outcome_code="extraction_failed",
                candidate_count=0, added_count=0,
            )
            return ObservationResult(
                event.event_id,
                (),
                processing_status="source_only",
                warning_code="l1_extraction_failed",
            )

        recorded_at = datetime.now(UTC)
        memories: list[AtomicMemory] = []
        for candidate in proposal.candidates:
            window = explicit_temporary_window(
                message.content, candidate.content,
                occurred_at=message.created_at,
            )
            memories.append(AtomicMemory(
                MemoryId(str(uuid4())), CURRENT_USER_SUBJECT_ID,
                candidate.content, recorded_at,
                valid_from=(window[0] if window else None),
                valid_to=(window[1] if window else None),
            ))
        return tuple(memories)

    def prepare_failed_observation_recovery(
        self, source_message_id: str, *, expected_attempt_id: str,
    ) -> tuple[MemoryEvent, str]:
        """核对旧 L0 与最新失败状态，并先登记一次新的恢复尝试。"""

        self._base._ensure_open()
        self._audit_store.require_retryable(
            source_message_id=source_message_id,
            expected_attempt_id=expected_attempt_id,
        )
        if source_message_id in self._pending_audits:
            raise ValueError("l1_retry_busy")
        message = self._base.conversation_store.get(MessageId(source_message_id))
        if message is None:
            raise ValueError("l1_retry_source_not_found")
        if message.role != MessageRole.USER:
            raise ValueError("l1_retry_source_not_user")
        event = MemoryEvent(
            str(message.id), "user", message.content, message.created_at,
        )
        attempt_id = self._start_audit(event)
        if attempt_id is None:
            raise ValueError("l1_retry_audit_unavailable")
        return event, attempt_id

    def persist_archived(
        self, event: MemoryEvent, memories: tuple[AtomicMemory, ...],
    ) -> ObservationResult:
        """在 Runtime 互斥区内补写 L1，并绑定已经存在的 L0 来源。"""

        self._base._ensure_open()
        message = ConversationMessage(
            MessageId(event.event_id), MessageRole(event.role),
            event.content, event.occurred_at,
        )
        try:
            operations = self._base.turn_service.persist_extracted(message, memories)
        except sqlite3.Error:
            self._base.turn_service.report_extraction_failure(
                message, code="l1_persistence_failed"
            )
            self._finish_audit(
                event, phase="failed", outcome_code="persistence_failed",
                candidate_count=len(memories), added_count=0,
            )
            return ObservationResult(
                event.event_id,
                (),
                processing_status="source_only",
                warning_code="l1_persistence_failed",
            )
        added_count = sum(
            operation.operation == MemoryOperationType.ADD for operation in operations
        )
        outcome = (
            "noop" if not memories else "added" if added_count else "reused"
        )
        self._finish_audit(
            event, phase="completed", outcome_code=outcome,
            candidate_count=len(memories), added_count=added_count,
        )
        return ObservationResult(
            event.event_id,
            tuple(
                WriteTrace(operation.operation.value, str(operation.memory.id), (event.event_id,))
                for operation in operations
            ),
        )

    def recall(self, query: str):
        return self._base.recall(query)

    def archive(self, event: MemoryEvent) -> ObservationResult:
        """复用基础方法的 L0-only 语义，不调用候选提取模型。"""

        return self._base.archive(event)

    def wait_until_ready(self) -> None:
        self._base.wait_until_ready()

    def close(self) -> None:
        self._base.close()
