"""从明确的自然语言请求中提取可审计的未来跟进草案。"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re


_NUMBER = r"(?:[0-9]{1,2}|[零〇一二两三四五六七八九十两]{1,3})"
_DATE = r"(?P<date>今天|明天|后天|20[0-9]{2}[-/年][0-9]{1,2}[-/月][0-9]{1,2}日?)"
_PATTERN = re.compile(
    rf"{_DATE}\s*(?P<period>上午|中午|下午|晚上|夜里)?\s*"
    rf"(?P<hour>{_NUMBER})\s*(?:点|时)"
    rf"(?:(?P<minute>{_NUMBER})\s*分?)?[^。！？!?]{{0,80}}?"
    rf"(?:到时候|届时)\s*(?:再)?问我(?:一下)?[：:，,\s]*(?P<prompt>[^。！？!?]{{2,120}})"
)


@dataclass(frozen=True, slots=True)
class FollowUpSuggestionDraft:
    """已解析但尚未写库的草案；它不代表允许主动投递。"""

    prompt_text: str
    follow_up_at: datetime


@dataclass(frozen=True, slots=True)
class FollowUpSuggestionResult:
    """旁路创建结果，供网页和圆屏诊断而不泄露完整 L1。"""

    status: str
    candidate_id: str | None = None
    source_memory_id: str | None = None
    prompt_text: str | None = None
    follow_up_at: str | None = None
    warning_code: str | None = None
    outreach_id: str | None = None


def _number(value: str) -> int:
    if value.isdigit():
        return int(value)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
              "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if "十" in value:
        left, right = value.split("十", 1)
        return (digits[left] if left else 1) * 10 + (digits[right] if right else 0)
    if len(value) == 1 and value in digits:
        return digits[value]
    raise ValueError("follow_up_number_invalid")


def parse_explicit_follow_up(
    text: str, *, occurred_at: datetime, utc_offset_minutes: int,
) -> FollowUpSuggestionDraft | None:
    """只接受明确日期、时刻和“问我”的请求；不推断模糊未来时间。"""

    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("follow_up_time_timezone_required")
    match = _PATTERN.search(text.strip())
    if match is None:
        return None
    local_zone = timezone(timedelta(minutes=utc_offset_minutes))
    local_now = occurred_at.astimezone(local_zone)
    date_text = match.group("date")
    if date_text in {"今天", "明天", "后天"}:
        days = {"今天": 0, "明天": 1, "后天": 2}[date_text]
        target_date = (local_now + timedelta(days=days)).date()
    else:
        year, month, day = (
            int(value) for value in re.findall(r"[0-9]+", date_text)
        )
        target_date = datetime(year, month, day).date()
    hour = _number(match.group("hour"))
    minute = _number(match.group("minute")) if match.group("minute") else 0
    period = match.group("period")
    # 12 小时表达必须带时段；未带时段时仅接受无歧义的 13–23 点。
    if period is None and hour < 13:
        return None
    if period is not None and not 1 <= hour <= 12:
        return None
    if period in {"下午", "晚上", "夜里"} and hour < 12:
        hour += 12
    elif period == "中午" and hour < 11:
        hour += 12
    if hour > 23 or minute > 59:
        return None
    follow_up_at = datetime.combine(
        target_date, datetime.min.time(), local_zone,
    ).replace(hour=hour, minute=minute)
    if follow_up_at <= local_now or follow_up_at - local_now > timedelta(days=90):
        return None
    prompt = match.group("prompt").strip(" ，,：:；;")
    if not prompt:
        return None
    if not prompt.endswith(("？", "?")):
        prompt += "？"
    return FollowUpSuggestionDraft(prompt[:160], follow_up_at)
