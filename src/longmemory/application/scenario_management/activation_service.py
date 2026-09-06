"""把 L2 确定性门控接到既有候选与复核事务，不负责触发模型。"""

from dataclasses import dataclass
from datetime import datetime

from longmemory.core.memory.l1_atomic.contracts import MemoryStore
from longmemory.core.memory.l2_scenario.activation_policy import (
    ScenarioActivationAction,
    ScenarioActivationDecision,
    ScenarioEvidenceSummary,
    ScenarioRiskAssessment,
    decide_scenario_activation,
)
from longmemory.core.memory.l2_scenario.contracts import ScenarioStore
from longmemory.core.memory.l2_scenario.models import (
    ScenarioMemory,
    ScenarioReviewDecision,
    ScenarioReviewerType,
)
from longmemory.core.memory.l2_scenario.proposals import (
    ScenarioProposal,
    ScenarioProposalInput,
)

from .service import ScenarioManagementService


@dataclass(frozen=True, slots=True)
class ScenarioActivationResult:
    decision: ScenarioActivationDecision
    scenario: ScenarioMemory | None


class ScenarioActivationService:
    """只让证据较强且风险门控通过的场景候选自动变为 active。"""

    def __init__(self, *, memory_store: MemoryStore, scenario_store: ScenarioStore) -> None:
        self._management = ScenarioManagementService(
            memory_store=memory_store, scenario_store=scenario_store,
        )
        self._scenario_store = scenario_store

    def apply(
        self,
        proposal: ScenarioProposal,
        *,
        inputs: tuple[ScenarioProposalInput, ...],
        risk: ScenarioRiskAssessment,
        generator_name: str,
        generator_version: str,
        generated_at: datetime | None = None,
    ) -> ScenarioActivationResult:
        """从白名单输入复算证据；非自动通过结果不创建持久候选。"""

        by_id = {item.memory_id: item for item in inputs}
        if len(by_id) != len(inputs) or any(
            memory_id not in by_id for memory_id in proposal.source_memory_ids
        ):
            raise ValueError("scenario_activation_sources_invalid")
        selected = tuple(by_id[memory_id] for memory_id in proposal.source_memory_ids)
        if len({item.subject_id for item in selected}) != 1:
            raise ValueError("scenario_source_subject_mismatch")
        messages = {
            message_id for item in selected for message_id in item.source_message_ids
        }
        decision = decide_scenario_activation(
            evidence=ScenarioEvidenceSummary(len(selected), len(messages)),
            risk=risk,
        )
        if decision.action != ScenarioActivationAction.AUTO_ACTIVATE:
            return ScenarioActivationResult(decision, None)

        scenario = self._management.create_candidate(
            title=proposal.title,
            summary=proposal.summary,
            source_memory_ids=proposal.source_memory_ids,
            generator_name=generator_name,
            generator_version=generator_version,
            generated_at=generated_at,
        )
        scenario = self._management.review(
            scenario.id,
            ScenarioReviewDecision.ACCEPTED,
            expected_revision=scenario.revision,
            reviewed_at=generated_at,
            reviewer_type=ScenarioReviewerType.POLICY,
            policy_version=decision.policy_version,
            decision_reason=decision.reason.value,
        )
        return ScenarioActivationResult(decision, scenario)
