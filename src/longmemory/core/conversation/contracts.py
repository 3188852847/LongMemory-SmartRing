"""L0 原始对话存储所需的抽象契约。"""

from typing import Protocol

from longmemory.core.common.identifiers import MessageId
from longmemory.core.conversation.models import ConversationMessage


class ConversationStore(Protocol):
    """核心层要求原始对话存储提供的最小能力。

    核心逻辑只依赖这个契约，不依赖 SQLite。
    以后即使更换数据库，也不需要修改对话业务逻辑。
    """

    def save(self, message: ConversationMessage) -> None:
        """持久化一条原始对话消息。"""
        ...

    def get(self, message_id: MessageId) -> ConversationMessage | None:
        """根据稳定标识符读取原始消息；不存在时返回 None。"""
        ...