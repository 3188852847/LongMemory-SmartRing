"""低频整理触发器只根据显式状态决策，便于稳定回归。"""

from datetime import UTC, datetime, timedelta

import pytest

from longmemory.core.memory.consolidation.models import ConsolidationTrigger
from longmemory.core.memory.consolidation.trigger_policy import (
    ConsolidationTriggerAction,
    ConsolidationTriggerConfig,
    ConsolidationTriggerReason,
    ConsolidationTriggerState,
    decide_consolidation_trigger,
)


NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def decide(state, trigger=ConsolidationTrigger.NEW_EVIDENCE, config=None):
    return decide_consolidation_trigger(
        trigger=trigger,
        state=state,
        now=NOW,
        config=config or ConsolidationTriggerConfig(),
    )


def test_enough_new_evidence_is_ready_with_bounded_source_count():
    decision = decide(ConsolidationTriggerState(37, 0))
    assert decision.action == ConsolidationTriggerAction.RUN
    assert decision.reason == ConsolidationTriggerReason.READY
    assert decision.source_limit == 20


@pytest.mark.parametrize(
    ("state", "action", "reason"),
    [
        (
            ConsolidationTriggerState(0, 0),
            ConsolidationTriggerAction.HOLD,
            ConsolidationTriggerReason.NO_PENDING_EVIDENCE,
        ),
        (
            ConsolidationTriggerState(3, 0),
            ConsolidationTriggerAction.HOLD,
            ConsolidationTriggerReason.BELOW_SOURCE_THRESHOLD,
        ),
        (
            ConsolidationTriggerState(4, 2),
            ConsolidationTriggerAction.BLOCK,
            ConsolidationTriggerReason.DAILY_BUDGET_EXHAUSTED,
        ),
        (
            ConsolidationTriggerState(4, 0, running=True),
            ConsolidationTriggerAction.BLOCK,
            ConsolidationTriggerReason.RUN_ALREADY_ACTIVE,
        ),
        (
            ConsolidationTriggerState(4, 0, last_finished_at=NOW - timedelta(hours=1)),
            ConsolidationTriggerAction.HOLD,
            ConsolidationTriggerReason.COOLDOWN_ACTIVE,
        ),
    ],
)
def test_automatic_trigger_is_explainably_held_or_blocked(state, action, reason):
    decision = decide(state)
    assert (decision.action, decision.reason, decision.source_limit) == (action, reason, 0)


def test_manual_trigger_bypasses_threshold_and_cooldown_but_not_budget():
    ready = decide(
        ConsolidationTriggerState(1, 0, last_finished_at=NOW),
        ConsolidationTrigger.MANUAL,
    )
    blocked = decide(
        ConsolidationTriggerState(1, 2),
        ConsolidationTrigger.MANUAL,
    )
    assert (ready.action, ready.reason, ready.source_limit) == (
        ConsolidationTriggerAction.RUN,
        ConsolidationTriggerReason.MANUAL_READY,
        1,
    )
    assert blocked.reason == ConsolidationTriggerReason.DAILY_BUDGET_EXHAUSTED


def test_invalid_config_and_naive_time_are_rejected():
    with pytest.raises(ValueError, match="consolidation_trigger_config_invalid"):
        ConsolidationTriggerConfig(minimum_new_sources=0)
    with pytest.raises(ValueError, match="now_timezone_required"):
        decide_consolidation_trigger(
            trigger=ConsolidationTrigger.NEW_EVIDENCE,
            state=ConsolidationTriggerState(4, 0),
            now=datetime(2026, 9, 6, 12, 0),
        )
