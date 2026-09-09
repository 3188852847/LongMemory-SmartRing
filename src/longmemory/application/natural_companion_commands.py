"""圆屏可直接表达的高精度陪伴控制命令。"""

from dataclasses import dataclass
from datetime import timedelta
from collections.abc import Callable
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
_CANCEL_FOLLOW_UP = frozenset({
    "取消刚才的跟进",
    "取消刚才的提醒",
    "不用到时候问我了",
    "到时候不用问我了",
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
                 feedback_store: CompanionFeedbackStore,
                 cancel_recent_follow_up: Callable[..., str]) -> None:
        self._conversation_store = conversation_store
        self._feedback_store = feedback_store
        self._cancel_recent_follow_up = cancel_recent_follow_up

    @staticmethod
    def recognizes(event: MemoryEvent) -> bool:
        normalized = event.content.strip().rstrip("。！？!? ")
        return event.role == "user" and normalized in (
            _REJECT_TOPIC | _CANCEL_FOLLOW_UP
        )

    def handle(self, event: MemoryEvent) -> NaturalCompanionCommandResult:
        message = ConversationMessage(
            MessageId(event.event_id), MessageRole.USER,
            event.content, event.occurred_at,
        )
        self._conversation_store.save(message)
        normalized = event.content.strip().rstrip("。！？!? ")
        if normalized in _CANCEL_FOLLOW_UP:
            outcome = self._cancel_recent_follow_up(
                subject_id="user:self",
                before=event.occurred_at,
                not_before=event.occurred_at - timedelta(minutes=30),
            )
            notices = {
                "applied": "好的，刚才安排的一次性跟进已经取消，到时不会再播报。",
                "target_not_found": "最近没有仍可取消的一次性跟进，因此没有改动任何安排。",
                "target_ambiguous": (
                    "最近有多条仍未执行的跟进，无法确定你指哪一条，因此没有取消。"
                    "你可以在控制台查看具体事项。"
                ),
                "already_attempted": (
                    "刚才的跟进已经开始处理或结束，不能再把它记为未执行取消。"
                ),
            }
            return NaturalCompanionCommandResult(
                "cancel_follow_up", outcome, notices[outcome],
            )
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
