"""验证记忆查看、来源追踪和删除用例。"""

from datetime import UTC, datetime

from longmemory.application.memory_management.dto import (
    MemoryDetails,
    MemoryEvidenceDetails,
)
from longmemory.application.memory_management.service import (
    MemoryManagementService,
)
from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.conversation.models import (
    ConversationMessage,
    MessageRole,
)
from longmemory.core.memory.models import (
    CURRENT_USER_SUBJECT_ID,
    AtomicMemory,
    MemoryEvidence,
    MemorySourceType,
)


FIXED_TIME = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)


class FakeConversationStore:
    """记忆管理测试使用的 L0 内存存储。"""

    def __init__(
        self,
        messages: tuple[ConversationMessage, ...] = (),
    ) -> None:
        self.messages = list(messages)

    def save(self, message: ConversationMessage) -> None:
        self.messages.append(message)

    def get(
        self,
        message_id: MessageId,
    ) -> ConversationMessage | None:
        return next(
            (
                message
                for message in self.messages
                if message.id == message_id
            ),
            None,
        )


class FakeMemoryStore:
    """记忆管理测试使用的 L1 内存存储。"""

    def __init__(
        self,
        memories: tuple[AtomicMemory, ...] = (),
        evidence: tuple[MemoryEvidence, ...] = (),
    ) -> None:
        self.memories = list(memories)
        self.evidence = list(evidence)

    def save(
        self,
        memory: AtomicMemory,
        evidence: MemoryEvidence,
    ) -> None:
        self.memories.append(memory)
        self.evidence.append(evidence)

    def add_evidence(self, evidence: MemoryEvidence) -> bool:
        if evidence in self.evidence:
            return False

        self.evidence.append(evidence)
        return True

    def list_evidence(
        self,
        memory_id: MemoryId,
    ) -> tuple[MemoryEvidence, ...]:
        return tuple(
            evidence
            for evidence in self.evidence
            if evidence.memory_id == memory_id
        )

    def get(
        self,
        memory_id: MemoryId,
    ) -> AtomicMemory | None:
        return next(
            (
                memory
                for memory in self.memories
                if memory.id == memory_id
            ),
            None,
        )

    def list_all(self) -> tuple[AtomicMemory, ...]:
        return tuple(self.memories)

    def list_active(self) -> tuple[AtomicMemory, ...]:
        return tuple(
            memory
            for memory in self.memories
            if memory.retired_at is None
        )

    def delete(self, memory_id: MemoryId) -> bool:
        original_count = len(self.memories)

        self.memories = [
            memory
            for memory in self.memories
            if memory.id != memory_id
        ]
        self.evidence = [
            evidence
            for evidence in self.evidence
            if evidence.memory_id != memory_id
        ]

        return len(self.memories) < original_count


def make_source_message() -> ConversationMessage:
    """创建固定的 L0 来源消息。"""

    return ConversationMessage(
        id=MessageId("message-001"),
        role=MessageRole.USER,
        content="我养了一只叫豆包的猫。",
        created_at=FIXED_TIME,
    )


def make_memory(
    source_message: ConversationMessage,
) -> AtomicMemory:
    """创建指向指定来源的 L1 记忆。"""

    return AtomicMemory(
        id=MemoryId("memory-001"),
        subject_id=CURRENT_USER_SUBJECT_ID,
        content="用户养了一只叫豆包的猫。",
        recorded_at=FIXED_TIME,
    )


def make_evidence(
    memory: AtomicMemory,
    source_message: ConversationMessage,
) -> MemoryEvidence:
    """创建一条用户陈述来源证据。"""

    return MemoryEvidence(
        memory_id=memory.id,
        source_message_id=source_message.id,
        source_type=MemorySourceType.USER_STATED,
        linked_at=FIXED_TIME,
    )


def test_lists_and_gets_memory_with_original_source() -> None:
    """查看记忆时应同时返回规范化内容和原始输入。"""

    source_message = make_source_message()
    memory = make_memory(source_message)
    evidence = make_evidence(memory, source_message)

    service = MemoryManagementService(
        memory_store=FakeMemoryStore((memory,), (evidence,)),
        conversation_store=FakeConversationStore(
            (source_message,)
        ),
    )

    expected_details = MemoryDetails(
        memory=memory,
        sources=(
            MemoryEvidenceDetails(
                evidence=evidence,
                source_message=source_message,
            ),
        ),
    )

    assert service.list_memories() == (expected_details,)
    assert service.get_memory(memory.id) == expected_details


def test_returns_none_when_memory_does_not_exist() -> None:
    """查询不存在的记忆时应明确返回 None。"""

    service = MemoryManagementService(
        memory_store=FakeMemoryStore(),
        conversation_store=FakeConversationStore(),
    )

    result = service.get_memory(
        MemoryId("missing-memory")
    )

    assert result is None


def test_deletes_l1_memory_but_preserves_l0_source() -> None:
    """删除错误记忆时不应连带删除原始消息。"""

    source_message = make_source_message()
    memory = make_memory(source_message)
    evidence = make_evidence(memory, source_message)

    memory_store = FakeMemoryStore((memory,), (evidence,))
    conversation_store = FakeConversationStore(
        (source_message,)
    )

    service = MemoryManagementService(
        memory_store=memory_store,
        conversation_store=conversation_store,
    )

    assert service.delete_memory(memory.id) is True
    assert service.get_memory(memory.id) is None
    assert conversation_store.get(source_message.id) == source_message

    # 再次删除同一个 ID，应明确表示没有删除任何记录。
    assert service.delete_memory(memory.id) is False
