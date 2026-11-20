"""把明确、短期的互动偏好收敛为固定行为指令。"""

from dataclasses import dataclass
from typing import Literal


TemporaryInteractionMode = Literal[
    "listen_only", "ask_before_advice", "direct_advice",
]
NextTurnInteractionSelection = Literal[
    "listen_only", "ask_before_advice", "direct_advice", "cancel",
]


@dataclass(frozen=True, slots=True)
class TemporaryInteractionDirective:
    """可追溯的临时互动方式；context 只能来自固定映射，不能复制任意原话。"""

    mode: TemporaryInteractionMode
    source_memory_id: str | None
    source_content: str
    source_message_id: str
    valid_to: str | None
    context: str
    scope: Literal["next_turn"] = "next_turn"


@dataclass(frozen=True, slots=True)
class TemporaryInteractionCommandResult:
    """设置或取消下一轮模式的确定性回执，不伪装成长期记忆写入。"""

    kind: str
    status: str
    notice: str
    mode: TemporaryInteractionMode | None
    writes: tuple = ()


_NEXT_TURN_PHRASES: dict[str, NextTurnInteractionSelection] = {
    "下一轮只听我说": "listen_only",
    "下一轮先问我要不要建议": "ask_before_advice",
    "下一轮直接给我建议": "direct_advice",
    "取消下一轮互动方式": "cancel",
}

_CONTEXT: dict[TemporaryInteractionMode, str] = {
    "listen_only": (
        "[当前临时互动方式]\n"
        "用户本轮选择“只倾听”。先回应和承接用户表达，不主动分析、"
        "列方案或给建议；如果用户在当前消息中明确索要建议，可以回答该请求。"
    ),
    "ask_before_advice": (
        "[当前临时互动方式]\n"
        "用户本轮选择“建议前先询问”。先倾听，再询问用户是否需要建议；"
        "如果用户在当前消息中已经明确索要建议，可以直接回答。"
    ),
    "direct_advice": (
        "[当前临时互动方式]\n"
        "用户本轮选择“直接建议”。在信息足够时给出简洁、可执行的建议；"
        "不要把证据不足的推断说成用户事实。"
    ),
}


def classify_next_turn_interaction(text: str) -> NextTurnInteractionSelection | None:
    """识别下一轮一次性模式；只接受不会吞并正文的完整控制句。"""

    normalized = text.strip().rstrip("。.!！").strip()
    return _NEXT_TURN_PHRASES.get(normalized)


def directive_context(mode: TemporaryInteractionMode) -> str:
    return _CONTEXT[mode]
