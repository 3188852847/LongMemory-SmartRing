"""历史问题的保守识别与时间线补充契约。"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
import re
from typing import Protocol

from longmemory.core.common.text import looks_like_question


class TemporalQueryIntent(StrEnum):
    HISTORY = "history"
    CHANGE_TIME = "change_time"
    DATE = "date"


_HISTORY_MARKERS = ("以前", "过去", "曾经", "原来", "之前", "从前", "当时")
_TIME_QUESTION_MARKERS = ("什么时候", "何时", "哪天")
_CHANGE_MARKERS = (
    "搬", "迁", "变", "换", "改", "开始", "不再", "后来", "从", "到",
)
_LOCAL_TIMEZONE = timezone(timedelta(hours=8))
_CHINESE_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_NUMBER = r"[0-9零〇一二三四五六七八九十]{1,3}"
_ABSOLUTE_DATE = re.compile(
    rf"(?<!\d)(?P<year>\d{{4}})年"
    rf"(?:(?P<month>{_NUMBER})月(?:(?P<day>{_NUMBER})[日号])?)?"
    r"(?![0-9零〇一二三四五六七八九十])"
)
_RELATIVE_DATE = re.compile(
    rf"(?P<relative>去年|今年)"
    rf"(?:(?P<month>{_NUMBER})月(?:(?P<day>{_NUMBER})[日号])?)?"
    r"(?![0-9零〇一二三四五六七八九十])"
)
_ISO_DATE = re.compile(
    r"(?<!\d)(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?!\d)"
)


@dataclass(frozen=True, slots=True)
class TemporalDateTarget:
    """用户明确指定的左闭右开当地日期区间。"""

    start: datetime
    end: datetime
    label: str


@dataclass(frozen=True, slots=True)
class TemporalQuery:
    intent: TemporalQueryIntent
    date_target: TemporalDateTarget | None = None


def _parse_small_number(raw: str) -> int | None:
    if raw.isascii() and raw.isdigit():
        return int(raw)
    if "十" not in raw:
        digits = [_CHINESE_DIGITS.get(char) for char in raw]
        if not digits or any(value is None for value in digits):
            return None
        value = 0
        for digit in digits:
            value = value * 10 + digit
        return value
    if raw.count("十") != 1:
        return None
    tens, ones = raw.split("十")
    tens_value = 1 if not tens else _CHINESE_DIGITS.get(tens)
    ones_value = 0 if not ones else _CHINESE_DIGITS.get(ones)
    if tens_value is None or ones_value is None:
        return None
    return tens_value * 10 + ones_value


def _target_from_parts(
    year: int, month_raw: str | None, day_raw: str | None,
) -> TemporalDateTarget | None:
    if not 1900 <= year <= 2100:
        return None
    month = _parse_small_number(month_raw) if month_raw is not None else None
    day = _parse_small_number(day_raw) if day_raw is not None else None
    if month_raw is not None and month is None:
        return None
    if day_raw is not None and day is None:
        return None
    try:
        if month is None:
            start = datetime(year, 1, 1, tzinfo=_LOCAL_TIMEZONE)
            end = datetime(year + 1, 1, 1, tzinfo=_LOCAL_TIMEZONE)
            label = f"{year}年"
        elif day is None:
            start = datetime(year, month, 1, tzinfo=_LOCAL_TIMEZONE)
            end = (
                datetime(year + 1, 1, 1, tzinfo=_LOCAL_TIMEZONE)
                if month == 12 else
                datetime(year, month + 1, 1, tzinfo=_LOCAL_TIMEZONE)
            )
            label = f"{year}年{month}月"
        else:
            # 显式检查当月天数，使 2 月 30 日不能退化成整月查询。
            if day > monthrange(year, month)[1]:
                return None
            start = datetime(year, month, day, tzinfo=_LOCAL_TIMEZONE)
            end = start + timedelta(days=1)
            label = f"{year}年{month}月{day}日"
    except ValueError:
        return None
    return TemporalDateTarget(start, end, label)


def _extract_date_target(text: str, *, now: datetime) -> TemporalDateTarget | None:
    """只接受一个完整日期表达；两个日期涉及范围语义，当前不猜。"""

    iso_matches = list(_ISO_DATE.finditer(text))
    absolute_matches = list(_ABSOLUTE_DATE.finditer(text))
    relative_matches = list(_RELATIVE_DATE.finditer(text))
    if len(iso_matches) + len(absolute_matches) + len(relative_matches) != 1:
        return None
    if iso_matches:
        match = iso_matches[0]
        return _target_from_parts(
            int(match["year"]), match["month"], match["day"],
        )
    if absolute_matches:
        match = absolute_matches[0]
        return _target_from_parts(
            int(match["year"]), match["month"], match["day"],
        )
    match = relative_matches[0]
    local_year = now.astimezone(_LOCAL_TIMEZONE).year
    year = local_year - 1 if match["relative"] == "去年" else local_year
    return _target_from_parts(year, match["month"], match["day"])


def analyze_temporal_query(
    query: str, *, now: datetime | None = None,
) -> TemporalQuery | None:
    """识别同一问句中的历史意图和唯一明确日期，不跨分句借词。"""

    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("temporal_query_clock_must_be_aware")
    intent = None
    for clause in re.findall(r"[^，,。.!！;；\r\n?？]+[?？]?", query):
        text = "".join(clause.split())
        if text.rstrip("?？") in {"原来如此", "原来是这样", "以前也是"}:
            continue
        if not looks_like_question(text.replace("哪天", "何时")):
            continue
        date_target = _extract_date_target(text, now=moment)
        if date_target is not None:
            return TemporalQuery(TemporalQueryIntent.DATE, date_target)
        # 含日期语法但日期无效、缺少日/号或出现多个日期时，本句整体保持
        # 关闭；不能再借“以前”等词退化为宽泛历史召回。
        if re.search(r"\d{4}年|\d{4}-\d{1,2}-\d{1,2}|去年|今年", text):
            continue
        if any(marker in text for marker in _TIME_QUESTION_MARKERS) and any(
            marker in text for marker in _CHANGE_MARKERS
        ):
            return TemporalQuery(TemporalQueryIntent.CHANGE_TIME)
        if any(marker in text for marker in _HISTORY_MARKERS):
            intent = TemporalQuery(TemporalQueryIntent.HISTORY)
    return intent


def classify_temporal_query(query: str) -> TemporalQueryIntent | None:
    """只识别明确历史表达；普通“现在是什么”不会开启退役记忆读取。"""

    result = analyze_temporal_query(query)
    return result.intent if result is not None else None


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
    strategy: str = "explicit_temporal_history_v2"
    date_target: TemporalDateTarget | None = None
    # 只有这些当前 L1 的可证区间与明确日期相交。None 表示并非日期问题；
    # 日期问题使用空元组表示当前候选都不能作为目标时段证据。
    current_target_ids: tuple[str, ...] | None = None


class TemporalRecallProvider(Protocol):
    def recall(
        self, query: str, *, current_memory_ids: tuple[str, ...], limit: int = 10,
    ) -> TemporalRecallResult: ...

    def close(self) -> None: ...
