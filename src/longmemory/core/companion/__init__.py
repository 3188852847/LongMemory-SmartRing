"""陪伴策略领域边界。

这里保存的是“助手如何陪伴”所需的可观察结果，不是 L0–L3
用户事实，也不是对用户情绪或意图的推断。
"""

from .contracts import (
    CompanionFeedbackStore,
    CompanionStrategyCandidateStore,
    InteractionOutcomeObserver,
    UserInitiatedInteractionObserver,
)
from .models import (
    CompanionFeedbackEvent,
    CompanionStrategyCandidate,
    CompanionStrategyCandidateStatus,
    CompanionStrategyObservation,
    InteractionOutcomeEvent,
    InteractionOutcomeEvidence,
    InteractionOutcomeKind,
    ProactiveTopicFeedbackTarget,
    UserInitiatedInteractionEvent,
)

__all__ = [
    "CompanionFeedbackEvent",
    "CompanionFeedbackStore",
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
]
