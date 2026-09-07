"""把日常时段候选和固定回放结果固化为不可变策略版本草案。"""

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from uuid import uuid4

from longmemory.core.companion import (
    AbsenceRoutineDraft,
    CompanionAbsenceStrategyVersion,
    CompanionAbsenceStrategyVersionStore,
    CompanionAbsenceStrategySelection,
    CompanionAbsenceStrategySwitchAction,
    CompanionStrategyReplayEvidence,
    CompanionStrategyCandidateStatus,
)


@dataclass(frozen=True, slots=True)
class AbsenceStrategyVersionResult:
    outcome: str
    version: CompanionAbsenceStrategyVersion


class CompanionAbsenceStrategyVersionService:
    """保存可复算参数与回放指纹，但绝不修改后台调度。"""

    def __init__(self, store: CompanionAbsenceStrategyVersionStore, *, clock=None,
                 id_factory=None) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: uuid4().hex)

    def create_from_candidate(
        self,
        candidate_id: str,
        *,
        subject_id: str,
        expected_candidate_revision: int,
        allowed_weekdays: tuple[int, ...],
        replay: CompanionStrategyReplayEvidence,
        grace_minutes: int = 60,
    ) -> AbsenceStrategyVersionResult:
        candidate = self._store.get_source_candidate(
            candidate_id, subject_id=subject_id,
        )
        if (
            candidate is None
            or candidate.status != CompanionStrategyCandidateStatus.CANDIDATE
            or candidate.revision != expected_candidate_revision
        ):
            raise ValueError("companion_routine_candidate_conflict")

        # 在运行回放前先验证候选参数；晚间跨日策略留待明确建模。
        draft = AbsenceRoutineDraft(
            candidate_id=candidate.id,
            expected_minute=candidate.expected_minute,
            grace_minutes=grace_minutes,
            utc_offset_minutes=candidate.utc_offset_minutes,
            allowed_weekdays=allowed_weekdays,
            enabled=False,
        )
        parameter_fingerprint = hashlib.sha256(
            (f"{candidate.id}\n{candidate.revision}\n{draft.expected_minute}\n"
             f"{draft.grace_minutes}\n{draft.utc_offset_minutes}\n"
             f"{','.join(map(str, draft.allowed_weekdays))}\n"
             f"{draft.policy_version}\n{replay.dataset_sha256}").encode()
        ).hexdigest()
        existing = self._store.get_by_parameter_fingerprint(
            subject_id, parameter_fingerprint,
        )
        if existing is not None:
            return AbsenceStrategyVersionResult("version_exists", existing)

        now = self._clock()
        version = CompanionAbsenceStrategyVersion(
            id=self._id_factory(), subject_id=subject_id,
            source_candidate_id=candidate.id,
            source_candidate_revision=candidate.revision,
            expected_minute=draft.expected_minute,
            grace_minutes=draft.grace_minutes,
            utc_offset_minutes=draft.utc_offset_minutes,
            allowed_weekdays=draft.allowed_weekdays,
            trigger_policy_version=draft.policy_version,
            replay_protocol=replay.protocol,
            replay_dataset_name=replay.dataset_name,
            replay_dataset_version=replay.dataset_version,
            replay_dataset_sha256=replay.dataset_sha256,
            parameter_fingerprint=parameter_fingerprint,
            replay_case_count=replay.case_count,
            replay_matched_count=replay.matched_count,
            replay_unsafe_allow_count=replay.unsafe_allow_count,
            replay_gate_passed=replay.gate_passed,
            replayed_at=replay.replayed_at, created_at=now,
        )
        return AbsenceStrategyVersionResult(
            "version_created", self._store.create(version),
        )

    def get_selection(self, subject_id: str) -> CompanionAbsenceStrategySelection | None:
        return self._store.get_selection(subject_id)

    def list_switch_events(self, subject_id: str):
        return self._store.list_switch_events(subject_id)

    def select_version(self, version_id: str, *, subject_id: str,
                       expected_revision: int, rollback: bool = False):
        version = self._store.get_version(version_id, subject_id=subject_id)
        if version is None:
            raise ValueError("companion_absence_version_missing")
        if not version.replay_gate_passed:
            raise ValueError("companion_absence_version_gate_failed")
        action = (CompanionAbsenceStrategySwitchAction.ROLLBACK if rollback
                  else CompanionAbsenceStrategySwitchAction.ACTIVATE)
        result = self._store.switch_selection(
            subject_id=subject_id, selected_version_id=version.id,
            expected_revision=expected_revision, action=action,
            event_id=self._id_factory(), now=self._clock(),
        )
        if result is None:
            raise ValueError("companion_absence_selection_conflict")
        return result

    def deactivate(self, *, subject_id: str, expected_revision: int):
        result = self._store.switch_selection(
            subject_id=subject_id, selected_version_id=None,
            expected_revision=expected_revision,
            action=CompanionAbsenceStrategySwitchAction.DEACTIVATE,
            event_id=self._id_factory(), now=self._clock(),
        )
        if result is None:
            raise ValueError("companion_absence_selection_conflict")
        return result
