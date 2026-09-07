"""陪伴策略领域边界。

这里保存的是“助手如何陪伴”所需的可观察结果，不是 L0–L3
用户事实，也不是对用户情绪或意图的推断。
"""

from .contracts import (
    CompanionFeedbackStore,
    CompanionRoutineCandidateStore,
    CompanionStrategyCandidateStore,
    InteractionOutcomeObserver,
    UserInitiatedInteractionObserver,
)
from .models import (
    CompanionFeedbackEvent,
    CompanionRoutineCandidate,
    CompanionStrategyCandidate,
    CompanionStrategyCandidateStatus,
    CompanionStrategyObservation,
    InteractionOutcomeEvent,
    InteractionOutcomeEvidence,
    InteractionOutcomeKind,
    ProactiveTopicFeedbackTarget,
    UserInitiatedInteractionEvent,
)
from .absence_policy import (
    AbsenceRoutineDraft,
    AbsenceRoutineState,
    AbsenceTriggerAction,
    AbsenceTriggerDecision,
    AbsenceTriggerReason,
    decide_routine_absence,
)

__all__ = [
    "AbsenceRoutineDraft",
    "AbsenceRoutineState",
    "AbsenceTriggerAction",
    "AbsenceTriggerDecision",
    "AbsenceTriggerReason",
    "CompanionFeedbackEvent",
    "CompanionFeedbackStore",
    "CompanionRoutineCandidate",
    "CompanionRoutineCandidateStore",
    "CompanionStrategyCandidate",
    "CompanionStrategyCandidateStatus",
    "CompanionStrategyCandidateStore",
    "CompanionStrategyObservation",
    "InteractionOutcomeEvent",
    "InteractionOutcomeEvidence",
    "InteractionOutcomeKind",
    "InteractionOutcomeObserver",
    "ProactiveTopicFeedbackTarget",
    "UserInitiatedInteractionEvent",
    "UserInitiatedInteractionObserver",
    "decide_routine_absence",
]
