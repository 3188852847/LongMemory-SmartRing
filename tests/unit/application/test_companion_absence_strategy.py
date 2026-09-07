from datetime import UTC, datetime

import pytest

from longmemory.application.companion_absence_strategy import (
    CompanionAbsenceStrategyVersionService,
)
from longmemory.core.companion import (
    CompanionAbsenceStrategySelection,
    CompanionAbsenceStrategySwitchEvent,
    CompanionRoutineCandidate,
    CompanionStrategyReplayEvidence,
    CompanionStrategyCandidateStatus,
)


NOW = datetime(2026, 9, 7, 8, tzinfo=UTC)


def replay():
    return CompanionStrategyReplayEvidence(
        protocol="companion-absence-offline-replay-v1",
        dataset_name="companion_absence_replay", dataset_version="1.0.0",
        dataset_sha256="b" * 64, case_count=16, matched_count=16,
        unsafe_allow_count=0, gate_passed=True, replayed_at=NOW,
    )


def candidate(**changes):
    values = dict(
        id="candidate-1", subject_id="user:self",
        status=CompanionStrategyCandidateStatus.CANDIDATE,
        expected_minute=13 * 60, utc_offset_minutes=480,
        observation_window_minutes=30, evidence_count=3,
        distinct_local_dates=3, evidence_fingerprint="a" * 64,
        rationale_code="repeated_user_initiated_activity_near_time",
        generator_version="test-generator", created_at=NOW, updated_at=NOW,
    )
    values.update(changes)
    return CompanionRoutineCandidate(**values)


class Store:
    def __init__(self, source):
        self.source = source
        self.versions = []
        self.selection = None
        self.events = []

    def get_source_candidate(self, candidate_id, *, subject_id):
        if self.source.id == candidate_id and self.source.subject_id == subject_id:
            return self.source
        return None

    def get_by_parameter_fingerprint(self, subject_id, parameter_fingerprint):
        return next((item for item in self.versions
                     if item.subject_id == subject_id
                     and item.parameter_fingerprint == parameter_fingerprint), None)

    def create(self, version):
        self.versions.append(version)
        return version

    def get_version(self, version_id, *, subject_id):
        return next((item for item in self.versions
                     if item.id == version_id and item.subject_id == subject_id), None)

    def get_selection(self, subject_id):
        return self.selection if self.selection and self.selection.subject_id == subject_id else None

    def list_switch_events(self, subject_id):
        return tuple(event for event in self.events if event.subject_id == subject_id)

    def switch_selection(self, *, subject_id, selected_version_id,
                         expected_revision, action, event_id, now):
        revision = self.selection.revision if self.selection else 0
        if revision != expected_revision:
            return None
        previous = self.selection.version_id if self.selection else None
        self.selection = CompanionAbsenceStrategySelection(
            subject_id, selected_version_id, revision + 1, now,
        )
        event = CompanionAbsenceStrategySwitchEvent(
            event_id, subject_id, previous, selected_version_id,
            action, revision + 1, now,
        )
        self.events.append(event)
        return self.selection, event


def test_freezes_candidate_parameters_and_replay_identity_once():
    store = Store(candidate())
    service = CompanionAbsenceStrategyVersionService(
        store, clock=lambda: NOW, id_factory=lambda: "version-1",
    )

    created = service.create_from_candidate(
        "candidate-1", subject_id="user:self", expected_candidate_revision=1,
        allowed_weekdays=(0, 1, 2, 3, 4),
        replay=replay(),
    )
    repeated = service.create_from_candidate(
        "candidate-1", subject_id="user:self", expected_candidate_revision=1,
        allowed_weekdays=(0, 1, 2, 3, 4),
        replay=replay(),
    )

    assert created.outcome == "version_created"
    assert created.version.expected_minute == 780
    assert created.version.grace_minutes == 60
    assert created.version.allowed_weekdays == (0, 1, 2, 3, 4)
    assert created.version.replay_gate_passed is True
    assert created.version.replay_case_count == 16
    assert repeated.outcome == "version_exists"
    assert repeated.version.id == "version-1"
    assert len(store.versions) == 1

    changed = service.create_from_candidate(
        "candidate-1", subject_id="user:self", expected_candidate_revision=1,
        allowed_weekdays=(0, 1, 2, 3),
        replay=replay(),
    )
    assert changed.outcome == "version_created"
    assert changed.version.parameter_fingerprint != created.version.parameter_fingerprint
    assert len(store.versions) == 2


@pytest.mark.parametrize("source", [
    None,
    candidate(status=CompanionStrategyCandidateStatus.DISMISSED),
    candidate(revision=2),
])
def test_missing_dismissed_or_stale_candidate_cannot_create_version(source):
    store = Store(candidate())
    if source is None:
        store.source = candidate(id="other")
    else:
        store.source = source
    with pytest.raises(ValueError, match="candidate_conflict"):
        CompanionAbsenceStrategyVersionService(store).create_from_candidate(
            "candidate-1", subject_id="user:self",
            expected_candidate_revision=1, allowed_weekdays=(0,),
            replay=replay(),
        )


def test_late_candidate_that_would_cross_midnight_is_not_silently_shifted():
    store = Store(candidate(expected_minute=23 * 60 + 30))
    with pytest.raises(ValueError, match="absence_routine_draft_invalid"):
        CompanionAbsenceStrategyVersionService(store).create_from_candidate(
            "candidate-1", subject_id="user:self",
            expected_candidate_revision=1, allowed_weekdays=(0,),
            replay=replay(),
        )


def test_selection_requires_gate_and_expected_pointer_revision():
    store = Store(candidate())
    service = CompanionAbsenceStrategyVersionService(
        store, clock=lambda: NOW,
        id_factory=iter(("version-1", "event-1", "unused-stale-event")).__next__,
    )
    service.create_from_candidate(
        "candidate-1", subject_id="user:self", expected_candidate_revision=1,
        allowed_weekdays=(0,), replay=replay(),
    )
    selection, event = service.select_version(
        "version-1", subject_id="user:self", expected_revision=0,
    )
    assert selection.version_id == "version-1" and selection.revision == 1
    assert event.action.value == "activate"

    with pytest.raises(ValueError, match="selection_conflict"):
        service.deactivate(subject_id="user:self", expected_revision=0)


def test_failed_replay_version_cannot_be_selected():
    store = Store(candidate())
    failed = CompanionStrategyReplayEvidence(
        protocol="companion-absence-offline-replay-v1",
        dataset_name="companion_absence_replay", dataset_version="1.0.0",
        dataset_sha256="c" * 64, case_count=16, matched_count=15,
        unsafe_allow_count=0, gate_passed=False, replayed_at=NOW,
    )
    service = CompanionAbsenceStrategyVersionService(
        store, clock=lambda: NOW, id_factory=lambda: "version-failed",
    )
    service.create_from_candidate(
        "candidate-1", subject_id="user:self", expected_candidate_revision=1,
        allowed_weekdays=(0,), replay=failed,
    )
    with pytest.raises(ValueError, match="gate_failed"):
        service.select_version(
            "version-failed", subject_id="user:self", expected_revision=0,
        )
