"""L0 原始对话消息领域模型。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from longmemory.core.common.identifiers import MessageId


class MessageRole(StrEnum):
    """消息在对话中的角色。"""

    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    """未经记忆提取处理的原始对话消息。

    L0 消息是后续记忆提取的审计来源。
    即使生成出的 L1 记忆有错误，也可以回到这条原始消息检查。
    """

    id: MessageId
    role: MessageRole
    content: str
    created_at: datetime