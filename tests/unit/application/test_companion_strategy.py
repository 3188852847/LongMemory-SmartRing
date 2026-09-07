from datetime import UTC, datetime, timedelta

from longmemory.application.companion_strategy import (
    CompanionStrategyCandidateService,
)
from longmemory.core.companion import CompanionStrategyObservation


BASE = datetime(2026, 9, 1, 5, 2, tzinfo=UTC)  # UTC+8 为 13:02。


class CandidateStore:
    def __init__(self, observations):
        self.observations = tuple(observations)
        self.candidates = []
        self.sources = []

    def list_observations(self, _subject_id, *, maximum_latency_seconds):
        return tuple(item for item in self.observations
                     if item.latency_seconds <= maximum_latency_seconds)

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


def observation(day, *, minute_shift=0, latency=120, suffix=None):
    queued = BASE + timedelta(days=day, minutes=minute_shift)
    suffix = suffix or str(day)
    return CompanionStrategyObservation(
        interaction_event_id=f"event-{suffix}", outreach_id=f"outreach-{suffix}",
        queued_at=queued, observed_at=queued + timedelta(seconds=latency),
        latency_seconds=latency, delivery_evidence_level="server_queued",
    )


def test_requires_three_distinct_local_dates():
    store = CandidateStore([
        observation(0, suffix="a"), observation(0, suffix="b"), observation(1),
    ])

    result = CompanionStrategyCandidateService(store).generate(
        "user:self", utc_offset_minutes=480,
    )

    assert result.outcome == "insufficient_cross_date_evidence"
    assert result.distinct_local_dates == 2
    assert store.candidates == []


def test_creates_inactive_candidate_from_cross_date_cluster_only_once():
    store = CandidateStore([
        observation(0, minute_shift=0), observation(1, minute_shift=3),
        observation(2, minute_shift=5),
        observation(3, minute_shift=45, suffix="other-bucket"),
    ])
    service = CompanionStrategyCandidateService(
        store, clock=lambda: datetime(2026, 9, 7, tzinfo=UTC),
        id_factory=lambda: "candidate-1",
    )

    result = service.generate("user:self", utc_offset_minutes=480)
    repeated = service.generate("user:self", utc_offset_minutes=480)

    assert result.outcome == "candidate_created"
    assert result.candidate.suggested_minute == 785  # 13:05，中位数而非臆造整点。
    assert result.candidate.evidence_count == 3
    assert result.candidate.status.value == "candidate"
    assert len(store.sources) == 3
    assert repeated.outcome == "current_candidate_exists"
    assert len(store.candidates) == 1
