"""编排记忆查看、删除和来源追踪。"""

from datetime import UTC, datetime
from uuid import uuid4

from longmemory.application.memory_management.dto import (
    MemoryDetails,
    MemoryEvidenceDetails,
    MemoryChangeResult,
    MemoryCorrectionResult,
)
from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.conversation.contracts import ConversationStore
from longmemory.core.memory.contracts import MemoryStore
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.core.memory.models import AtomicMemory, MemoryEvidence, MemorySourceType


class MemoryManagementService:
    """提供不依赖 CLI 和数据库实现的记忆管理用例。"""

    def __init__(
        self,
        *,
        memory_store: MemoryStore,
        conversation_store: ConversationStore,
    ) -> None:
        self._memory_store = memory_store
        self._conversation_store = conversation_store

    def list_memories(self) -> tuple[MemoryDetails, ...]:
        """列出全部记忆，并附带各自的 L0 来源。"""

        return tuple(
            self._build_details(memory)
            for memory in self._memory_store.list_all()
        )

    def get_memory(
        self,
        memory_id: MemoryId,
    ) -> MemoryDetails | None:
        """根据 ID 查看一条记忆及其来源。"""

        memory = self._memory_store.get(memory_id)

        if memory is None:
            return None

        return self._build_details(memory)

    def delete_memory(self, memory_id: MemoryId) -> bool:
        """删除一条 L1 记忆，但保留其 L0 原始来源。

        返回 True 表示确实删除了一条记忆；
        返回 False 表示该 ID 原本就不存在。
        """

        return self._memory_store.delete(memory_id)

    def correct_memory(
        self,
        memory_id: MemoryId,
        corrected_content: str,
        *,
        occurred_at: datetime | None = None,
    ) -> MemoryCorrectionResult:
        """以追加并取代的方式纠正错误事实，不改写旧记录。

        这里明确只表达“旧事实原本就错误”。事实后来发生变化需要单独
        提供 valid time，不能借用本用例而丢失时间语义。
        """

        content = corrected_content.strip()
        if not content:
            raise ValueError("corrected_content_empty")
        if len(content) > 1000:
            raise ValueError("corrected_content_too_long")

        old_memory = self._memory_store.get(memory_id)
        if old_memory is None:
            raise LookupError("memory_not_found")
        if old_memory.retired_at is not None:
            raise ValueError("memory_not_active")
        if content == old_memory.content:
            raise ValueError("memory_correction_unchanged")
        duplicate = self._memory_store.find_by_content(
            content,
            subject_id=old_memory.subject_id,
        )
        if duplicate is not None:
            raise ValueError("memory_correction_duplicate")

        now = occurred_at or datetime.now(UTC)
        message = ConversationMessage(
            id=MessageId(str(uuid4())),
            role=MessageRole.USER,
            content=content,
            created_at=now,
        )
        new_memory = AtomicMemory(
            id=MemoryId(str(uuid4())),
            subject_id=old_memory.subject_id,
            content=content,
            recorded_at=now,
        )
        evidence = MemoryEvidence(
            memory_id=new_memory.id,
            source_message_id=message.id,
            source_type=MemorySourceType.USER_CORRECTED,
            linked_at=now,
        )

        self._conversation_store.save(message)
        self._memory_store.save(new_memory, evidence)
        if not self._memory_store.retire_as_superseded(
            old_memory.id,
            superseded_by_id=new_memory.id,
            retired_at=now,
        ):
            raise RuntimeError("memory_correction_race")
        return MemoryCorrectionResult(old_memory, new_memory, message, evidence)

    def record_memory_change(
        self,
        memory_id: MemoryId,
        new_content: str,
        *,
        effective_at: datetime,
        occurred_at: datetime | None = None,
    ) -> MemoryChangeResult:
        """记录“旧事实过去成立、后来变成新事实”的时间化取代。

        effective_at 是现实世界中的变化时间；occurred_at 是用户在系统里
        记录这次变化的时间。二者不能混为一个字段，否则无法表达补录历史变化。
        """

        content = new_content.strip()
        if not content:
            raise ValueError("changed_content_empty")
        if len(content) > 1000:
            raise ValueError("changed_content_too_long")
        if effective_at.tzinfo is None or effective_at.utcoffset() is None:
            raise ValueError("effective_at_timezone_required")

        old_memory = self._memory_store.get(memory_id)
        if old_memory is None:
            raise LookupError("memory_not_found")
        if old_memory.retired_at is not None:
            raise ValueError("memory_not_active")
        if content == old_memory.content:
            raise ValueError("memory_change_unchanged")
        duplicate = self._memory_store.find_by_content(
            content,
            subject_id=old_memory.subject_id,
        )
        if duplicate is not None:
            raise ValueError("memory_change_duplicate")

        now = occurred_at or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("occurred_at_timezone_required")
        if effective_at > now:
            raise ValueError("effective_at_in_future")
        if old_memory.valid_from is not None and effective_at < old_memory.valid_from:
            raise ValueError("effective_at_before_valid_from")

        message = ConversationMessage(
            id=MessageId(str(uuid4())),
            role=MessageRole.USER,
            content=content,
            created_at=now,
        )
        new_memory = AtomicMemory(
            id=MemoryId(str(uuid4())),
            subject_id=old_memory.subject_id,
            content=content,
            recorded_at=now,
            valid_from=effective_at,
        )
        # 这里仍属于用户主动陈述；user_corrected 专门保留给“旧事实原本有误”。
        evidence = MemoryEvidence(
            memory_id=new_memory.id,
            source_message_id=message.id,
            source_type=MemorySourceType.USER_STATED,
            linked_at=now,
        )

        self._conversation_store.save(message)
        self._memory_store.save(new_memory, evidence)
        if not self._memory_store.retire_as_superseded(
            old_memory.id,
            superseded_by_id=new_memory.id,
            retired_at=now,
            valid_to=effective_at,
        ):
            raise RuntimeError("memory_change_race")
        return MemoryChangeResult(
            old_memory, new_memory, message, evidence, effective_at
        )

    def _build_details(
        self,
        memory: AtomicMemory,
    ) -> MemoryDetails:
        """组装一条记忆及其原始来源。"""

        sources = tuple(
            MemoryEvidenceDetails(
                evidence=evidence,
                source_message=self._conversation_store.get(
                    evidence.source_message_id
                ),
            )
            for evidence in self._memory_store.list_evidence(memory.id)
        )

        return MemoryDetails(
            memory=memory,
            sources=sources,
        )
