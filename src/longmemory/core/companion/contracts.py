"""陪伴结果观察契约；应用层不依赖 SQLite。"""

from datetime import datetime
from typing import Protocol

from longmemory.core.conversation.models import ConversationMessage

from .models import (
    CompanionAbsenceStrategyVersion,
    CompanionFeedbackEvent,
    CompanionRoutineCandidate,
    CompanionStrategyCandidate,
    CompanionStrategyObservation,
    InteractionOutcomeEvent,
    ProactiveTopicFeedbackTarget,
    UserInitiatedInteractionEvent,
)


class CompanionAbsenceStrategyVersionStore(Protocol):
    """不可变策略版本的存储边界；本协议不提供激活操作。"""

    def get_source_candidate(
        self, candidate_id: str, *, subject_id: str,
    ) -> CompanionRoutineCandidate | None: ...

    def get_by_parameter_fingerprint(
        self, subject_id: str, parameter_fingerprint: str,
    ) -> CompanionAbsenceStrategyVersion | None: ...

    def create(
        self, version: CompanionAbsenceStrategyVersion,
    ) -> CompanionAbsenceStrategyVersion: ...

    def list(self, subject_id: str) -> tuple[CompanionAbsenceStrategyVersion, ...]: ...


class InteractionOutcomeObserver(Protocol):
    def record_user_message(
        self, message: ConversationMessage,
    ) -> InteractionOutcomeEvent | None:
        """若该消息是正式主动问候后的首条用户消息，记录时间关系。"""
        ...


class UserInitiatedInteractionObserver(Protocol):
    def record_user_message(
        self, message: ConversationMessage,
    ) -> UserInitiatedInteractionEvent | None:
        """若消息满足长静默且近期无主动问候，记录启动时间证据。"""
        ...


class CompanionFeedbackStore(Protocol):
    def find_recent_topic(
        self, subject_id: str, *, before: datetime, not_before: datetime,
    ) -> ProactiveTopicFeedbackTarget | None: ...

    def reject_topic(
        self, event: CompanionFeedbackEvent,
        *, expected_topic_revision: int,
    ) -> None: ...


class CompanionStrategyCandidateStore(Protocol):
    """陪伴策略候选存储边界；实现不得返回消息正文。"""

    def list_observations(
        self, subject_id: str, *, maximum_latency_seconds: int,
    ) -> tuple[CompanionStrategyObservation, ...]: ...

    def get_current(self, subject_id: str) -> CompanionStrategyCandidate | None: ...

    def get_by_fingerprint(
        self, subject_id: str, fingerprint: str,
    ) -> CompanionStrategyCandidate | None: ...

    def create(
        self,
        candidate: CompanionStrategyCandidate,
        observations: tuple[CompanionStrategyObservation, ...],
    ) -> CompanionStrategyCandidate: ...

    def dismiss(
        self, candidate_id: str, *, subject_id: str,
        expected_revision: int, now: datetime,
    ) -> CompanionStrategyCandidate | None: ...


class CompanionRoutineCandidateStore(Protocol):
    """用户主动出现时段候选边界；来源只包含时间证据。"""

    def list_observations(
        self, subject_id: str,
    ) -> tuple[UserInitiatedInteractionEvent, ...]: ...

    def get_current(self, subject_id: str) -> CompanionRoutineCandidate | None: ...

    def get_by_fingerprint(
        self, subject_id: str, fingerprint: str,
    ) -> CompanionRoutineCandidate | None: ...

    def create(
        self,
        candidate: CompanionRoutineCandidate,
        observations: tuple[UserInitiatedInteractionEvent, ...],
    ) -> CompanionRoutineCandidate: ...

    def dismiss(
        self, candidate_id: str, *, subject_id: str,
        expected_revision: int, now: datetime,
    ) -> CompanionRoutineCandidate | None: ...
