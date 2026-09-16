import pytest

from longmemory.application.proactive_frequency import (
    frequency_text,
    parse_proactive_frequency,
)


@pytest.mark.parametrize(("text", "seconds"), [
    ("把主动交流频率改成每1分钟一次", 60),
    ("主动联系频率设为每十分钟一次。", 600),
    ("请把定时问候调整为每二十四小时一次", 86400),
])
def test_parses_explicit_frequency_commands(text, seconds):
    assert parse_proactive_frequency(text) == seconds


@pytest.mark.parametrize("text", [
    "主动一点", "每分钟找我", "主动交流每半小时一次", "主动交流每25小时一次",
])
def test_rejects_ambiguous_or_out_of_range_frequency(text):
    assert parse_proactive_frequency(text) is None


def test_frequency_text_uses_readable_units():
    assert frequency_text(60) == "1分钟"
    assert frequency_text(7200) == "2小时"
