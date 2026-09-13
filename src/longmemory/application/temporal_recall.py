"""历史问题的保守识别与时间线补充契约。"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class TemporalQueryIntent(StrEnum):
    HISTORY = "history"
    CHANGE_TIME = "change_time"


_HISTORY_MARKERS = ("以前", "过去", "曾经", "原来", "之前", "从前", "当时")
_TIME_QUESTION_MARKERS = ("什么时候", "何时", "哪天")
_CHANGE_MARKERS = (
    "搬", "迁", "变", "换", "改", "开始", "不再", "后来", "从", "到",
)


def classify_temporal_query(query: str) -> TemporalQueryIntent | None:
    """只识别明确历史表达；普通“现在是什么”不会开启退役记忆读取。"""

    text = "".join(query.split())
    if not text:
        return None
    if text in {"原来如此", "原来是这样", "以前也是"}:
        return None
    if any(marker in text for marker in _TIME_QUESTION_MARKERS) and any(
        marker in text for marker in _CHANGE_MARKERS
    ):
        return TemporalQueryIntent.CHANGE_TIME
    if any(marker in text for marker in _HISTORY_MARKERS):
        return TemporalQueryIntent.HISTORY
    return None


@dataclass(frozen=True, slots=True)
class TemporalRecallItem:
    memory_id: str
    content: str
    valid_from: str | None
    valid_to: str | None
    source_message_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TemporalRecallResult:
    context: str
    items: tuple[TemporalRecallItem, ...]
    intent: TemporalQueryIntent | None
    strategy: str = "explicit_temporal_history_v1"


class TemporalRecallProvider(Protocol):
    def recall(
        self, query: str, *, current_memory_ids: tuple[str, ...], limit: int = 10,
    ) -> TemporalRecallResult: ...

    def close(self) -> None: ...
