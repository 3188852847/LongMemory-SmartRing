import json

import pytest

from longmemory.application.scenario_management.proposal_service import ScenarioProposalService
from longmemory.core.common.identifiers import MemoryId, MemorySubjectId
from longmemory.core.memory.l2_scenario.proposals import (
    ScenarioProposalError,
    ScenarioProposalInput,
    parse_scenario_proposal,
)


def _sources():
    return (
        ScenarioProposalInput(MemoryId("l1-a"), MemorySubjectId("user:self"),
                              "用户周五要答辩。", ("l0-a",)),
        ScenarioProposalInput(MemoryId("l1-b"), MemorySubjectId("user:self"),
                              "用户正在修改 PPT。", ("l0-b",)),
    )


def _raw(ids=("l1-a", "l1-b")):
    return json.dumps({
        "schema_version": 1,
        "candidate": {
            "title": "准备答辩",
            "summary": "用户本周正在准备答辩，主要任务是修改 PPT。",
            "source_memory_ids": list(ids),
        },
    })


def test_preview_is_strict_and_does_not_allow_unknown_source_ids():
    proposal = parse_scenario_proposal(
        _raw(), allowed_source_ids=(MemoryId("l1-a"), MemoryId("l1-b"))
    )
    assert proposal.title == "准备答辩"
    with pytest.raises(ScenarioProposalError, match="scenario_proposal_schema_invalid"):
        parse_scenario_proposal(
            _raw(("l1-a", "not-sent")),
            allowed_source_ids=(MemoryId("l1-a"), MemoryId("l1-b")),
        )


def test_v2_can_abstain_instead_of_forcing_unrelated_memories_together():
    raw = json.dumps({"schema_version": 2, "candidate": None})
    assert parse_scenario_proposal(
        raw, allowed_source_ids=(MemoryId("l1-a"), MemoryId("l1-b"))
    ) is None

    class Producer:
        def propose(self, *, sources):
            return raw

    with pytest.raises(ScenarioProposalError, match="scenario_proposal_no_coherent_group"):
        ScenarioProposalService(Producer()).preview(_sources())


def test_source_threshold_is_checked_before_model_call():
    class Producer:
        called = False

        def propose(self, *, sources):
            self.called = True
            return _raw()

    producer = Producer()
    service = ScenarioProposalService(producer)
    invalid = (
        ScenarioProposalInput(MemoryId("l1-a"), MemorySubjectId("user:self"),
                              "事实一", ("same-l0",)),
        ScenarioProposalInput(MemoryId("l1-b"), MemorySubjectId("user:self"),
                              "事实二", ("same-l0",)),
    )
    with pytest.raises(ScenarioProposalError, match="scenario_requires_distinct_user_l0_sources"):
        service.preview(invalid)
    assert producer.called is False


def test_valid_preview_calls_model_once_and_returns_selected_subset():
    class Producer:
        calls = 0

        def propose(self, *, sources):
            self.calls += 1
            return _raw()

    producer = Producer()
    proposal = ScenarioProposalService(producer).preview(_sources())
    assert producer.calls == 1
    assert proposal.source_memory_ids == (MemoryId("l1-a"), MemoryId("l1-b"))


def test_model_selected_subset_must_itself_cover_two_l0_messages():
    sources = (
        ScenarioProposalInput(MemoryId("l1-a"), MemorySubjectId("user:self"),
                              "事实一", ("same-l0",)),
        ScenarioProposalInput(MemoryId("l1-b"), MemorySubjectId("user:self"),
                              "事实二", ("same-l0",)),
        ScenarioProposalInput(MemoryId("l1-c"), MemorySubjectId("user:self"),
                              "事实三", ("different-l0",)),
    )

    class Producer:
        def propose(self, *, sources):
            return _raw(("l1-a", "l1-b"))

    with pytest.raises(ScenarioProposalError, match="scenario_requires_distinct_user_l0_sources"):
        ScenarioProposalService(Producer()).preview(sources)
