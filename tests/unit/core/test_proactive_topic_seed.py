from datetime import UTC, datetime

import pytest

from longmemory.core.proactive import ProactiveTopicSeed, TopicSeedStatus


NOW = datetime(2026, 9, 7, 6, 0, tzinfo=UTC)


def test_topic_seed_requires_an_explicit_clean_broadcast_phrase():
    seed = ProactiveTopicSeed(
        "a" * 32, "user:self", "scenario-1", "毕业设计准备得怎么样了？",
        TopicSeedStatus.ACTIVE, NOW, NOW,
    )
    assert seed.prompt_text == "毕业设计准备得怎么样了？"

    with pytest.raises(ValueError, match="topic_seed_prompt_invalid"):
        ProactiveTopicSeed(
            "b" * 32, "user:self", "scenario-1", " 含有前导空格",
            TopicSeedStatus.ACTIVE, NOW, NOW,
        )
