"""圆屏可直接表达的高精度陪伴控制命令。"""

from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from longmemory.core.companion import CompanionFeedbackEvent, CompanionFeedbackStore
from longmemory.core.common.identifiers import MessageId
from longmemory.core.conversation.contracts import ConversationStore
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.methods.contracts import MemoryEvent, WriteTrace


_REJECT_TOPIC = frozenset({
    "以后不要主动聊这个话题",
    "不要再主动聊这个话题",
    "别再主动聊这个话题",
})


@dataclass(frozen=True, slots=True)
class NaturalCompanionCommandResult:
    kind: str
    status: str
    notice: str
    writes: tuple[WriteTrace, ...] = ()
    target_memory_ids: tuple[str, ...] = ()


class NaturalCompanionCommandService:
    """只执行明确拒绝，并把“这个话题”限制在最近 30 分钟。"""

    def __init__(self, *, conversation_store: ConversationStore,
                 feedback_store: CompanionFeedbackStore) -> None:
        self._conversation_store = conversation_store
        self._feedback_store = feedback_store

    @staticmethod
    def recognizes(event: MemoryEvent) -> bool:
        return event.role == "user" and event.content.strip().rstrip("。！？!? ") in _REJECT_TOPIC

    def handle(self, event: MemoryEvent) -> NaturalCompanionCommandResult:
        message = ConversationMessage(
            MessageId(event.event_id), MessageRole.USER,
            event.content, event.occurred_at,
        )
        self._conversation_store.save(message)
        target = self._feedback_store.find_recent_topic(
            "user:self", before=event.occurred_at,
            not_before=event.occurred_at - timedelta(minutes=30),
        )
        if target is None:
            return NaturalCompanionCommandResult(
                "reject_proactive_topic", "target_not_found",
                "最近没有可以唯一对应的已投递记忆话题，因此没有停用任何内容。",
            )
        feedback = CompanionFeedbackEvent(
            id=uuid4().hex,
            subject_id="user:self",
            outreach_id=target.outreach_id,
            topic_seed_id=target.topic_seed_id,
            source_message_id=str(message.id),
            occurred_at=event.occurred_at,
        )
        self._feedback_store.reject_topic(
            feedback, expected_topic_revision=target.topic_seed_revision,
        )
        return NaturalCompanionCommandResult(
            "reject_proactive_topic", "applied",
            "知道了，已经停用刚才对应的主动话题，以后不会再用这条素材主动找你。",
        )
