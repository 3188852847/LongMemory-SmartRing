"""L2 场景持久化的技术中立契约。"""

from typing import Protocol

from longmemory.core.common.identifiers import ScenarioId
from longmemory.core.memory.l2_scenario.models import (
    ScenarioGenerationAudit,
    ScenarioMemory,
    ScenarioSource,
    ScenarioReview,
)


class ScenarioStore(Protocol):
    def save_candidate(
        self,
        scenario: ScenarioMemory,
        sources: tuple[ScenarioSource, ...],
        audit: ScenarioGenerationAudit,
    ) -> None: ...

    def get(self, scenario_id: ScenarioId) -> ScenarioMemory | None: ...

    def list_sources(self, scenario_id: ScenarioId) -> tuple[ScenarioSource, ...]: ...

    def review(
        self,
        review: ScenarioReview,
        *,
        expected_revision: int,
    ) -> ScenarioMemory: ...
