from datetime import UTC, datetime

from longmemory.application.follow_up_suggestions import parse_explicit_follow_up


NOW = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)


def test_parses_explicit_relative_date_and_chinese_clock():
    result = parse_explicit_follow_up(
        "我明天下午三点要提交汇报，到时候问我准备好了吗",
        occurred_at=NOW, utc_offset_minutes=480,
    )

    assert result is not None
    assert result.follow_up_at.isoformat() == "2026-09-11T15:00:00+08:00"
    assert result.prompt_text == "准备好了吗？"


def test_rejects_ambiguous_clock_and_vague_future_language():
    assert parse_explicit_follow_up(
        "我明天三点要提交汇报，到时候问我准备好了吗",
        occurred_at=NOW, utc_offset_minutes=480,
    ) is None
    assert parse_explicit_follow_up(
        "我以后要提交汇报，到时候问我准备好了吗",
        occurred_at=NOW, utc_offset_minutes=480,
    ) is None
    assert parse_explicit_follow_up(
        "我明天下午三点提交汇报，不用问我准备情况",
        occurred_at=NOW, utc_offset_minutes=480,
    ) is None


def test_rejects_past_and_more_than_ninety_days():
    assert parse_explicit_follow_up(
        "我今天上午八点要提交汇报，到时候问我准备好了吗",
        occurred_at=NOW, utc_offset_minutes=480,
    ) is None
    assert parse_explicit_follow_up(
        "我2027年1月1日下午三点提交汇报，到时候问我准备好了吗",
        occurred_at=NOW, utc_offset_minutes=480,
    ) is None
