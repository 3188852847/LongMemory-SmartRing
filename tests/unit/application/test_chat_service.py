"""验证聊天应用服务对各个记忆模块的编排。"""

from datetime import UTC, datetime

import pytest

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.application.chat.service import ChatService
from longmemory.core.common.exceptions import EmptyMessageError
from longmemory.core.common.identifiers import (
    MemoryId,
    MemorySubjectId,
    MessageId,
)
from longmemory.core.conversation.models import (
    ConversationMessage,
    MessageRole,
)
from longmemory.core.memory.extraction.service import (
    MemoryExtractionService,
)
from longmemory.core.memory.models import AtomicMemory, MemoryEvidence
from longmemory.core.memory.retrieval.service import (
    KeywordMemoryRetriever,
)


FIXED_TIME = datetime(2026, 9, 3, 14, 0, tzinfo=UTC)


class FakeConversationStore:
    """用于应用层单元测试的 L0 内存存储。"""

    def __init__(self) -> None:
        self.messages: list[ConversationMessage] = []

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
    """用于应用层单元测试的 L1 内存存储。"""

    def __init__(self) -> None:
        self.memories: list[AtomicMemory] = []
        self.evidence: list[MemoryEvidence] = []

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

    def find_by_content(
        self,
        content: str,
        *,
        subject_id: MemorySubjectId,
    ) -> AtomicMemory | None:
        return next(
            (
                memory
                for memory in self.memories
                if memory.content == content
                and memory.subject_id == subject_id
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

        return len(self.memories) < original_count


def build_test_chat_service(
    conversation_store: FakeConversationStore,
    memory_store: FakeMemoryStore,
) -> ChatService:
    """装配一个完全确定、无需网络的聊天服务。"""

    message_ids = iter(
        [
            MessageId("message-001"),
            MessageId("message-002"),
            MessageId("message-003"),
            MessageId("message-004"),
        ]
    )

    memory_extractor = MemoryExtractionService(
        id_factory=lambda: MemoryId("memory-001"),
        clock=lambda: FIXED_TIME,
    )

    memory_retriever = KeywordMemoryRetriever(memory_store)

    return ChatService(
        conversation_store=conversation_store,
        memory_store=memory_store,
        memory_extractor=memory_extractor,
        memory_retriever=memory_retriever,
        answer_generator=FakeAnswerGenerator(),
        message_id_factory=lambda: next(message_ids),
        clock=lambda: FIXED_TIME,
    )


def test_chat_saves_then_recalls_memory() -> None:
    """第二轮问题应召回第一轮保存的长期记忆。"""

    conversation_store = FakeConversationStore()
    memory_store = FakeMemoryStore()
    chat_service = build_test_chat_service(
        conversation_store,
        memory_store,
    )

    first_result = chat_service.chat(
        "我养了一只叫豆包的猫。"
    )
    recall_result = chat_service.chat(
        "我的猫叫什么？"
    )

    assert len(conversation_store.messages) == 4
    assert tuple(
        message.role for message in conversation_store.messages
    ) == (
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
        MessageRole.ASSISTANT,
    )
    assert first_result.assistant_message.content == (
        first_result.answer
    )
    assert recall_result.assistant_message.content == (
        "你的猫叫豆包。"
    )

    assert len(first_result.saved_memories) == 1
    assert first_result.saved_memories[0].content == (
        "用户养了一只叫豆包的猫。"
    )
    assert first_result.memory_operations[0].evidence.source_message_id == (
        first_result.user_message.id
    )

    assert recall_result.saved_memories == ()
    assert recall_result.retrieved_memories == (
        first_result.saved_memories[0],
    )
    assert recall_result.answer == "你的猫叫豆包。"


def test_chat_rejects_blank_message_without_writing_data() -> None:
    """空白输入不应产生 L0、L1 或回答。"""

    conversation_store = FakeConversationStore()
    memory_store = FakeMemoryStore()
    chat_service = build_test_chat_service(
        conversation_store,
        memory_store,
    )

    with pytest.raises(
        EmptyMessageError,
        match="聊天消息不能为空",
    ):
        chat_service.chat("   ")

    assert conversation_store.messages == []
    assert memory_store.memories == []


def test_chat_reuses_exact_duplicate_memory() -> None:
    """重复陈述应保留新 L0，但不新增重复 L1。"""

    conversation_store = FakeConversationStore()
    memory_store = FakeMemoryStore()
    chat_service = build_test_chat_service(
        conversation_store,
        memory_store,
    )

    first_result = chat_service.chat(
        "我养了一只叫豆包的猫。"
    )
    duplicate_result = chat_service.chat(
        "我养了一只叫豆包的猫！"
    )

    assert len(conversation_store.messages) == 4
    assert len(memory_store.memories) == 1
    assert len(memory_store.evidence) == 2
    assert tuple(
        evidence.source_message_id
        for evidence in memory_store.evidence
    ) == (
        first_result.user_message.id,
        duplicate_result.user_message.id,
    )

    assert len(first_result.saved_memories) == 1
    assert first_result.reused_memories == ()

    assert duplicate_result.saved_memories == ()
    assert duplicate_result.reused_memories == (
        first_result.saved_memories[0],
    )
