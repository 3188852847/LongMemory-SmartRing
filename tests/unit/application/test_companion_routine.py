from datetime import UTC, datetime, timedelta

from longmemory.application.companion_routine import (
    CompanionRoutineCandidateService,
)
from longmemory.core.companion import UserInitiatedInteractionEvent
from longmemory.core.companion.contracts import (
    CompanionRoutineCandidateStore,
    CompanionStrategyCandidateStore,
)


BASE = datetime(2026, 9, 1, 5, 0, tzinfo=UTC)


def test_routine_and_outreach_candidate_contracts_remain_separate():
    assert "create" in CompanionRoutineCandidateStore.__dict__
    assert "dismiss" in CompanionRoutineCandidateStore.__dict__
    assert "create" in CompanionStrategyCandidateStore.__dict__
    assert "dismiss" in CompanionStrategyCandidateStore.__dict__


class Store:
    def __init__(self, observations):
        self.observations = tuple(observations)
        self.candidates = []
        self.sources = []

    def list_observations(self, _subject_id):
        return self.observations

    def get_current(self, _subject_id):
        return next((item for item in self.candidates
                     if item.status.value == "candidate"), None)

    def get_by_fingerprint(self, _subject_id, fingerprint):
        return next((item for item in self.candidates
                     if item.evidence_fingerprint == fingerprint), None)

    def create(self, candidate, observations):
        self.candidates.append(candidate)
        self.sources = list(observations)
        return candidate


def observation(day, *, minute_shift=0, suffix=None):
    occurred = BASE + timedelta(days=day, minutes=minute_shift)
    suffix = suffix or str(day)
    return UserInitiatedInteractionEvent(
        id=f"event-{suffix}", subject_id="user:self",
        source_message_id=f"message-{suffix}", occurred_at=occurred,
        previous_user_message_at=occurred - timedelta(hours=5),
        silence_gap_seconds=5 * 3600,
    )


def test_requires_three_distinct_dates_in_one_time_bucket():
    store = Store([
        observation(0, suffix="a"), observation(0, suffix="b"), observation(1),
    ])

    result = CompanionRoutineCandidateService(store).generate(
        "user:self", utc_offset_minutes=480,
    )

    assert result.outcome == "insufficient_cross_date_evidence"
    assert result.distinct_local_dates == 2
    assert store.candidates == []


def test_creates_inactive_routine_candidate_once():
    store = Store([
        observation(0), observation(1, minute_shift=4),
        observation(2, minute_shift=8),
        observation(3, minute_shift=40, suffix="other"),
    ])
    service = CompanionRoutineCandidateService(
        store, clock=lambda: datetime(2026, 9, 7, tzinfo=UTC),
        id_factory=lambda: "routine-1",
    )

    created = service.generate("user:self", utc_offset_minutes=480)
    repeated = service.generate("user:self", utc_offset_minutes=480)

    assert created.outcome == "candidate_created"
    assert created.candidate.expected_minute == 784
    assert created.candidate.evidence_count == 3
    assert created.candidate.status.value == "candidate"
    assert len(store.sources) == 3
    assert repeated.outcome == "current_candidate_exists"
