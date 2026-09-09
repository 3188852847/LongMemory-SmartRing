"""为少量明确临时状态生成可审计的双时间范围。"""

from datetime import datetime, timedelta, timezone


_TRANSIENT_MARKERS = (
    "心情", "感觉", "状态", "有点", "很累", "疲惫", "困", "没精神",
    "不舒服", "难受", "开心", "高兴", "焦虑", "紧张", "难过", "烦",
    "很忙", "生病", "感冒", "头疼", "失眠",
)
_PERSISTENT_MARKERS = ("以后", "今后", "一直", "每天", "通常", "习惯", "长期")


def explicit_temporary_window(
    source_text: str, candidate_content: str, *, occurred_at: datetime,
    utc_offset_minutes: int = 8 * 60,
) -> tuple[datetime, datetime] | None:
    """仅对“今天/这两天”的明确个人状态赋期限，不猜测普通计划。"""

    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("temporary_state_time_timezone_required")
    text = source_text.strip()
    scope = next(
        (item for item in ("今天", "这两天") if text.startswith("我" + item)),
        None,
    )
    if scope is None or any(marker in text for marker in _PERSISTENT_MARKERS):
        return None
    if not any(marker in text for marker in _TRANSIENT_MARKERS):
        return None
    if not any(marker in candidate_content for marker in _TRANSIENT_MARKERS):
        return None
    zone = timezone(timedelta(minutes=utc_offset_minutes))
    local_day = occurred_at.astimezone(zone).date()
    start_day = local_day if scope == "今天" else local_day - timedelta(days=1)
    valid_from = datetime.combine(start_day, datetime.min.time(), zone)
    valid_to = datetime.combine(local_day + timedelta(days=1), datetime.min.time(), zone)
    return valid_from, valid_to
