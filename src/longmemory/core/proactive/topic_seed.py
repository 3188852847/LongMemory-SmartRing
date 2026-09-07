"""允许用于主动播报的话题素材。

它不是 L4 记忆，也不修改用户画像；只是把一条所有者核对过的播报短句
绑定到可追溯的 L2 场景。第一版不做模型生成，避免把任意私人记忆直接念出。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class TopicSeedStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class ProactiveTopicSeed:
    id: str
    subject_id: str
    scenario_id: str
    prompt_text: str
    status: TopicSeedStatus
    created_at: datetime
    updated_at: datetime
    revision: int = 1

    def __post_init__(self) -> None:
        for value, name, maximum in (
            (self.id, "topic_seed_id", 120),
            (self.subject_id, "topic_seed_subject", 120),
            (self.scenario_id, "topic_seed_scenario", 128),
            (self.prompt_text, "topic_seed_prompt", 120),
        ):
            if value != value.strip() or not value or len(value) > maximum:
                raise ValueError(f"{name}_invalid")
        if any(ord(character) < 32 for character in self.prompt_text):
            raise ValueError("topic_seed_prompt_invalid")
        for value, name in (
            (self.created_at, "topic_seed_created_at"),
            (self.updated_at, "topic_seed_updated_at"),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name}_timezone_required")
        if self.updated_at < self.created_at or self.revision < 1:
            raise ValueError("topic_seed_revision_invalid")
