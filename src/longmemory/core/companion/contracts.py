"""陪伴结果观察契约；应用层不依赖 SQLite。"""

from datetime import datetime
from typing import Protocol

from longmemory.core.conversation.models import ConversationMessage

from .models import InteractionOutcomeEvent
from .models import CompanionFeedbackEvent, ProactiveTopicFeedbackTarget


class InteractionOutcomeObserver(Protocol):
    def record_user_message(
        self, message: ConversationMessage,
    ) -> InteractionOutcomeEvent | None:
        """若该消息是正式主动问候后的首条用户消息，记录时间关系。"""
        ...


class CompanionFeedbackStore(Protocol):
    def find_recent_topic(
        self, subject_id: str, *, before: datetime, not_before: datetime,
    ) -> ProactiveTopicFeedbackTarget | None: ...

    def reject_topic(
        self, event: CompanionFeedbackEvent,
        *, expected_topic_revision: int,
    ) -> None: ...
