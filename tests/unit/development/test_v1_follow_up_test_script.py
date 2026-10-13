"""验收台词生成器只验证时间边界和可被正式解析器接受的文本。"""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

import pytest

from longmemory.application.follow_up_suggestions import (
    parse_explicit_follow_up,
    parse_follow_up_time_change,
)


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "v1_follow_up_test_script",
    ROOT / "scripts/development/v1_follow_up_test_script.py",
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


LOCAL_ZONE = timezone(timedelta(minutes=480))


@pytest.mark.parametrize("hour", [19, 1])
@pytest.mark.parametrize("event_zone", [LOCAL_ZONE, timezone.utc])
def test_generated_lines_are_future_and_match_follow_up_parsers(hour, event_zone):
    # 台词采用用户配置的 UTC+8 本地时钟；事件时间也可以用 UTC 记录同一
    # 时刻。凌晨一时的 UTC 日期属于前一天，必须仍按用户本地“今天”解析。
    # 不从 CI 机器时区推断本地时钟，否则解析器 offset=480 与台词会错位。
    now = datetime(2026, 9, 16, hour, 2, 20, tzinfo=LOCAL_ZONE)
    original, changed, create, change = module.acceptance_lines(now)

    draft = parse_explicit_follow_up(
        create, occurred_at=now.astimezone(event_zone), utc_offset_minutes=480,
    )
    assert draft is not None and draft.follow_up_at == original
    assert draft.prompt_text == "检查结果？"
    assert parse_follow_up_time_change(change) == (changed.hour, changed.minute)
    assert changed > original > now


def test_generated_lines_reject_crossing_midnight_instead_of_printing_ambiguous_time():
    now = datetime(2026, 9, 16, 23, 55, 30, tzinfo=LOCAL_ZONE)
    with pytest.raises(ValueError, match="午夜"):
        module.acceptance_lines(now)
