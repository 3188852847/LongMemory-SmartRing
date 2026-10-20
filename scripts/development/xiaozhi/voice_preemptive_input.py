"""在实际provider输入边界读取两份不同载荷；不重建/归一化模型对话。

memory_query 由已存在的记忆入口提供。model_user_message 是实际 dialogue 最后
user.content 的原字符串；JSON、language/emotion/speaker及未知字段均原样保留。
不取时钟、声纹、角色/工具配置，也不执行任何记忆/工具/播放操作。
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EffectiveVoiceInput:
    memory_query: str = field(repr=False)
    model_user_message: str = field(repr=False)
    messages: tuple[tuple[str, str], ...] = field(repr=False)
    tools_required: bool

    @property
    def eligible(self):
        return not self.tools_required

    def matches(self, current):
        return (type(current) is EffectiveVoiceInput and self.eligible and current.eligible
                and self.memory_query == current.memory_query
                and self.model_user_message == current.model_user_message
                and self.messages == current.messages)


def capture_effective_voice_input(memory_query, dialogue, *, tools_required):
    """接收表达/联网/声纹装配后的真实值，复制文本快照，绝不改写调用者。

    当前协议只支持文本role/content；工具/结构化/额外message元数据不静默丢弃。
    返回None时走原正式提供器，不能以简化消息、空工具列表或旧system再试。
    """
    if (not isinstance(memory_query, str) or not memory_query.strip() or len(memory_query) > 16000
            or type(tools_required) is not bool or not isinstance(dialogue, (list, tuple))
            or not 2 <= len(dialogue) <= 129):
        return None
    rows = []
    for item in dialogue:
        if (not isinstance(item, dict) or set(item) != {"role", "content"}
                or not isinstance(item["role"], str) or item["role"] not in {"system", "user", "assistant"}
                or not isinstance(item["content"], str)):
            return None
        rows.append((item["role"], item["content"]))
    if (rows[0][0] != "system" or any(role == "system" for role, _ in rows[1:])
            or rows[-1][0] != "user" or not rows[-1][1].strip()
            or len(rows[-1][1]) > 16000
            or sum(len(text) for _, text in rows) > 32000):
        return None
    return EffectiveVoiceInput(memory_query, rows[-1][1], tuple(rows[:-1]), tools_required)
