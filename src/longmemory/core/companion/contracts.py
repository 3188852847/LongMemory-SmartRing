"""陪伴结果观察契约；应用层不依赖 SQLite。"""

from typing import Protocol

from longmemory.core.conversation.models import ConversationMessage

from .models import InteractionOutcomeEvent


class InteractionOutcomeObserver(Protocol):
    def record_user_message(
        self, message: ConversationMessage,
    ) -> InteractionOutcomeEvent | None:
        """若该消息是正式主动问候后的首条用户消息，记录时间关系。"""
        ...
