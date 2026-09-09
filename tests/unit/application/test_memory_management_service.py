"""验证记忆查看、来源追踪和删除用例。"""

from datetime import UTC, datetime
from dataclasses import replace
import pytest

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

    def find_by_content(self, content, *, subject_id):
        return next((memory for memory in self.list_active()
                     if memory.subject_id == subject_id and memory.content == content), None)

    def retire_as_superseded(
        self, memory_id, *, superseded_by_id, retired_at, valid_to=None
    ):
        for index, memory in enumerate(self.memories):
            if memory.id == memory_id and memory.retired_at is None:
                self.memories[index] = replace(
                    memory,
                    retired_at=retired_at,
                    superseded_by_id=superseded_by_id,
                    valid_to=valid_to,
                )
                return True
        return False


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


def test_promotes_existing_user_l0_without_copying_source() -> None:
    source = make_source_message()
    conversations = FakeConversationStore((source,))
    memories = FakeMemoryStore()
    result = MemoryManagementService(
        memory_store=memories, conversation_store=conversations,
    ).promote_source_to_memory(
        source.id, "用户养了一只叫豆包的猫。", occurred_at=FIXED_TIME,
    )

    assert result.created_new_memory is True
    assert result.source_message is source
    assert conversations.messages == [source]
    assert result.evidence.source_message_id == source.id
    assert memories.list_evidence(result.memory.id) == (result.evidence,)


def test_promoting_l0_adds_evidence_to_same_active_fact() -> None:
    original = make_source_message()
    additional = replace(original, id=MessageId("message-002"), content="我的猫叫豆包。")
    memory = make_memory(original)
    initial_evidence = make_evidence(memory, original)
    memories = FakeMemoryStore((memory,), (initial_evidence,))
    result = MemoryManagementService(
        memory_store=memories,
        conversation_store=FakeConversationStore((original, additional)),
    ).promote_source_to_memory(
        additional.id, memory.content, occurred_at=FIXED_TIME,
    )

    assert result.created_new_memory is False
    assert result.memory == memory
    assert len(memories.list_all()) == 1
    assert {e.source_message_id for e in memories.list_evidence(memory.id)} == {
        original.id, additional.id,
    }


def test_source_promotion_rejects_non_user_and_already_linked_l0() -> None:
    source = make_source_message()
    memory = make_memory(source)
    evidence = make_evidence(memory, source)
    service = MemoryManagementService(
        memory_store=FakeMemoryStore((memory,), (evidence,)),
        conversation_store=FakeConversationStore((source,)),
    )
    with pytest.raises(ValueError, match="source_already_linked"):
        service.promote_source_to_memory(source.id, "用户养了一只叫豆包的猫。")

    assistant = replace(source, id=MessageId("assistant-001"), role=MessageRole.ASSISTANT)
    service = MemoryManagementService(
        memory_store=FakeMemoryStore(),
        conversation_store=FakeConversationStore((assistant,)),
    )
    with pytest.raises(ValueError, match="promoted_source_must_be_user"):
        service.promote_source_to_memory(assistant.id, "助手说过一句话。")


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


def test_correction_adds_user_evidence_and_retires_old_memory() -> None:
    source_message = make_source_message()
    memory = make_memory(source_message)
    memory_store = FakeMemoryStore((memory,), (make_evidence(memory, source_message),))
    conversation_store = FakeConversationStore((source_message,))
    service = MemoryManagementService(
        memory_store=memory_store, conversation_store=conversation_store
    )

    result = service.correct_memory(
        memory.id, "用户的猫叫年糕。", occurred_at=FIXED_TIME
    )

    assert result.new_memory.content == "用户的猫叫年糕。"
    assert result.evidence.source_type is MemorySourceType.USER_CORRECTED
    assert result.source_message.content == "用户的猫叫年糕。"
    assert memory_store.list_active() == (result.new_memory,)
    retired = memory_store.get(memory.id)
    assert retired.retired_at == FIXED_TIME
    assert retired.superseded_by_id == result.new_memory.id
    assert retired.valid_to is None


def test_fact_change_records_real_world_validity_without_losing_history() -> None:
    source_message = make_source_message()
    effective_at = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    memory = replace(
        make_memory(source_message),
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    memory_store = FakeMemoryStore((memory,), (make_evidence(memory, source_message),))
    conversation_store = FakeConversationStore((source_message,))
    service = MemoryManagementService(
        memory_store=memory_store, conversation_store=conversation_store
    )

    result = service.record_memory_change(
        memory.id,
        "用户现在养了一只叫年糕的猫。",
        effective_at=effective_at,
        occurred_at=FIXED_TIME,
    )

    retired = memory_store.get(memory.id)
    assert retired is not None
    assert retired.valid_to == effective_at
    assert retired.retired_at == FIXED_TIME
    assert retired.superseded_by_id == result.new_memory.id
    assert result.new_memory.valid_from == effective_at
    assert result.new_memory.recorded_at == FIXED_TIME
    assert result.evidence.source_type is MemorySourceType.USER_STATED
    assert memory_store.list_active() == (result.new_memory,)


@pytest.mark.parametrize(
    ("effective_at", "error"),
    [
        (datetime(2026, 9, 4, tzinfo=UTC), "effective_at_in_future"),
        (datetime(2025, 12, 31, tzinfo=UTC), "effective_at_before_valid_from"),
        (datetime(2026, 9, 3, 12, 0), "effective_at_timezone_required"),
    ],
)
def test_fact_change_rejects_invalid_effective_time(
    effective_at: datetime,
    error: str,
) -> None:
    source_message = make_source_message()
    memory = replace(
        make_memory(source_message),
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    memory_store = FakeMemoryStore((memory,), (make_evidence(memory, source_message),))
    conversation_store = FakeConversationStore((source_message,))
    service = MemoryManagementService(
        memory_store=memory_store, conversation_store=conversation_store
    )

    with pytest.raises(ValueError, match=error):
        service.record_memory_change(
            memory.id,
            "用户现在养了一只叫年糕的猫。",
            effective_at=effective_at,
            occurred_at=FIXED_TIME,
        )

    assert memory_store.list_all() == (memory,)
    assert conversation_store.messages == [source_message]


def test_correction_rejects_retired_unchanged_and_duplicate() -> None:
    source_message = make_source_message()
    memory = make_memory(source_message)
    duplicate = AtomicMemory(
        id=MemoryId("memory-duplicate"), subject_id=CURRENT_USER_SUBJECT_ID,
        content="用户的猫叫年糕。", recorded_at=FIXED_TIME,
    )
    service = MemoryManagementService(
        memory_store=FakeMemoryStore((memory, duplicate)),
        conversation_store=FakeConversationStore((source_message,)),
    )
    with pytest.raises(ValueError, match="memory_correction_unchanged"):
        service.correct_memory(memory.id, memory.content)
    with pytest.raises(ValueError, match="memory_correction_duplicate"):
        service.correct_memory(memory.id, duplicate.content)
