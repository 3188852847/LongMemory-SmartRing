"""在数据库事务之外调用 L2 候选模型，并严格限制其来源。"""

from longmemory.core.memory.l2_scenario.proposals import (
    ScenarioProposal,
    ScenarioProposalError,
    ScenarioProposalInput,
    ScenarioProposalProducer,
    parse_scenario_proposal,
)


class ScenarioProposalService:
    def __init__(self, producer: ScenarioProposalProducer) -> None:
        self._producer = producer

    def preview(self, sources: tuple[ScenarioProposalInput, ...]) -> ScenarioProposal:
        """生成一次不落库预览；来源门槛失败时绝不调用模型。"""

        if not 2 <= len(sources) <= 20 or len({item.memory_id for item in sources}) != len(sources):
            raise ScenarioProposalError("scenario_requires_distinct_l1_sources")
        if len({item.subject_id for item in sources}) != 1:
            raise ScenarioProposalError("scenario_source_subject_mismatch")
        source_messages = {
            source_id for item in sources for source_id in item.source_message_ids
        }
        if len(source_messages) < 2:
            raise ScenarioProposalError("scenario_requires_distinct_user_l0_sources")
        try:
            raw = self._producer.propose(sources=sources)
        except Exception:
            raise ScenarioProposalError("scenario_proposal_generation_failed") from None
        proposal = parse_scenario_proposal(
            raw, allowed_source_ids=tuple(item.memory_id for item in sources)
        )
        # 输入池整体满足门槛还不够：模型选出的子集本身也必须覆盖两个
        # 不同 L0，否则页面会拿到一个注定无法保存的伪多证据候选。
        by_id = {item.memory_id: item for item in sources}
        selected_messages = {
            source_id
            for memory_id in proposal.source_memory_ids
            for source_id in by_id[memory_id].source_message_ids
        }
        if len(selected_messages) < 2:
            raise ScenarioProposalError("scenario_requires_distinct_user_l0_sources")
        return proposal
