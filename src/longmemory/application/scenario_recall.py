"""L2 场景召回的应用契约；与网页、小智和具体数据库解耦。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ScenarioRecallItem:
    scenario_id: str
    title: str
    summary: str
    source_memory_ids: tuple[str, ...]
    source_message_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScenarioRecallResult:
    context: str
    items: tuple[ScenarioRecallItem, ...]
    strategy: str = "l2_keyword_v1"


class ScenarioRecallProvider(Protocol):
    def recall(self, query: str, *, limit: int = 3) -> ScenarioRecallResult: ...

    def close(self) -> None: ...
