"""日常模型辅助提取：L0 优先持久化，L1 失败显式降级。"""

from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from uuid import uuid4

from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.core.memory.extraction.candidates import (
    CandidateExtractionError,
    CandidateExtractionService,
)
from longmemory.core.memory.models import AtomicMemory, CURRENT_USER_SUBJECT_ID
from longmemory.methods.contracts import (
    MemoryEvent,
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
    capabilities = LongMemoryV1.capabilities

    def __init__(
        self,
        database_path: Path,
        *,
        producer,
        existing_only: bool = True,
        allow_cross_thread: bool = False,
        retriever_factory=None,
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
        self.retrieval_name = self._base.retrieval_name

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
        try:
            proposal = self._extractor.extract(message)
        except CandidateExtractionError:
            self._base.turn_service.report_extraction_failure(
                message, code="l1_extraction_failed"
            )
            return ObservationResult(
                event.event_id,
                (),
                processing_status="source_only",
                warning_code="l1_extraction_failed",
            )

        recorded_at = datetime.now(UTC)
        memories = tuple(
            AtomicMemory(
                MemoryId(str(uuid4())),
                CURRENT_USER_SUBJECT_ID,
                candidate.content,
                recorded_at,
            )
            for candidate in proposal.candidates
        )
        try:
            operations = self._base.turn_service.persist_extracted(message, memories)
        except sqlite3.Error:
            self._base.turn_service.report_extraction_failure(
                message, code="l1_persistence_failed"
            )
            return ObservationResult(
                event.event_id,
                (),
                processing_status="source_only",
                warning_code="l1_persistence_failed",
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

    def wait_until_ready(self) -> None:
        self._base.wait_until_ready()

    def close(self) -> None:
        self._base.close()
