"""保守识别圆屏用户对上一轮记忆表现的明确反馈。"""

from typing import Literal
import re


RoundScreenMemoryFeedbackKind = Literal["recall_miss", "wrong_memory"]
INTERPRETER_VERSION = "explicit_round_screen_feedback_v1"

_TARGET_ANCHORS = (
    "刚才", "刚刚", "上一轮", "上轮", "上一个回答", "上次回答",
    "前一个回答", "前一句回答",
)
_WRONG_PATTERNS = ("记错了", "说错了", "答错了", "回答错了", "弄错了")
_MISS_PATTERNS = (
    "没想起来", "没有想起来", "没记起来", "没有记起来",
    "没记住", "没有记住", "不记得", "忘记了", "忘了",
)


def classify_explicit_round_screen_feedback(
    text: str,
) -> RoundScreenMemoryFeedbackKind | None:
    """只接受同时明确指向助手和上一轮的失败陈述。

    这里刻意牺牲召回率换取低误报：普通的“我刚才说错了”、故事中的
    “他忘了”以及没有上一轮锚点的“你错了”都不能成为研究标签。
    """

    if not isinstance(text, str):
        return None
    normalized = re.sub(r"[\s，。！？、,.!?；;：:]", "", text)
    if not normalized or "你" not in normalized:
        return None
    if not any(anchor in normalized for anchor in _TARGET_ANCHORS):
        return None
    assistant_index = normalized.find("你")
    # “我忘了你刚才说什么”虽然同时含有“你/刚才/忘了”，但失败主语是
    # 用户自己。只接受位于助手指向词之后的失败描述。
    if any(normalized.find(pattern) > assistant_index for pattern in _WRONG_PATTERNS):
        return "wrong_memory"
    if any(normalized.find(pattern) > assistant_index for pattern in _MISS_PATTERNS):
        return "recall_miss"
    return None
