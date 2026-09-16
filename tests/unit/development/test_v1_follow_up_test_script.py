"""验收台词生成器只验证时间边界和可被正式解析器接受的文本。"""

from datetime import datetime
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


def test_generated_lines_are_future_and_match_follow_up_parsers():
    now = datetime.now().astimezone().replace(year=2026, month=9, day=16, hour=19, minute=2, second=20)
    original, changed, create, change = module.acceptance_lines(now)

    draft = parse_explicit_follow_up(
        create, occurred_at=now, utc_offset_minutes=480,
    )
    assert draft is not None and draft.follow_up_at == original
    assert draft.prompt_text == "检查结果？"
    assert parse_follow_up_time_change(change) == (changed.hour, changed.minute)
    assert changed > original > now


def test_generated_lines_reject_crossing_midnight_instead_of_printing_ambiguous_time():
    now = datetime.now().astimezone().replace(year=2026, month=9, day=16, hour=23, minute=55, second=30)
    with pytest.raises(ValueError, match="午夜"):
        module.acceptance_lines(now)
