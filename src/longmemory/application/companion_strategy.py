"""从跨日互动时间证据提出陪伴策略候选；本模块不激活策略。"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
import hashlib
from statistics import median
from uuid import uuid4

from longmemory.core.companion import (
    CompanionStrategyCandidate,
    CompanionStrategyCandidateStatus,
    CompanionStrategyCandidateStore,
    CompanionStrategyObservation,
)


GENERATOR_VERSION = "contact-time-candidate-v1"
RATIONALE_CODE = "repeated_temporal_followup_near_contact_time"
MAXIMUM_LATENCY_SECONDS = 30 * 60
MINIMUM_DISTINCT_DATES = 3
BUCKET_MINUTES = 30


@dataclass(frozen=True, slots=True)
class CompanionStrategyGenerationResult:
    outcome: str
    candidate: CompanionStrategyCandidate | None
    eligible_observation_count: int
    distinct_local_dates: int


class CompanionStrategyCandidateService:
    """确定性地产生可审计假设，避免把短期巧合直接写成用户偏好。"""

    def __init__(self, store: CompanionStrategyCandidateStore, *, clock=None,
                 id_factory=None) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: uuid4().hex)

    def generate(
        self, subject_id: str, *, utc_offset_minutes: int,
    ) -> CompanionStrategyGenerationResult:
        current = self._store.get_current(subject_id)
        observations = self._store.list_observations(
            subject_id, maximum_latency_seconds=MAXIMUM_LATENCY_SECONDS,
        )
        if current is not None:
            return CompanionStrategyGenerationResult(
                "current_candidate_exists", current, len(observations),
                current.distinct_local_dates,
            )

        selected, date_count = self._select_cluster(
            observations, utc_offset_minutes=utc_offset_minutes,
        )
        if len(selected) < MINIMUM_DISTINCT_DATES:
            return CompanionStrategyGenerationResult(
                "insufficient_cross_date_evidence", None,
                len(observations), date_count,
            )

        local_zone = timezone(timedelta(minutes=utc_offset_minutes))
        minutes = [
            item.queued_at.astimezone(local_zone).hour * 60
            + item.queued_at.astimezone(local_zone).minute
            for item in selected
        ]
        suggested_minute = int(median(minutes))
        source_ids = sorted(item.interaction_event_id for item in selected)
        fingerprint = hashlib.sha256(
            (f"{GENERATOR_VERSION}\n{utc_offset_minutes}\n{suggested_minute}\n"
             + "\n".join(source_ids)).encode()
        ).hexdigest()
        existing = self._store.get_by_fingerprint(subject_id, fingerprint)
        if existing is not None:
            return CompanionStrategyGenerationResult(
                "evidence_already_analyzed", existing,
                len(observations), len(selected),
            )

        now = self._clock()
        candidate = CompanionStrategyCandidate(
            id=self._id_factory(), subject_id=subject_id,
            status=CompanionStrategyCandidateStatus.CANDIDATE,
            suggested_minute=suggested_minute,
            utc_offset_minutes=utc_offset_minutes,
            evidence_count=len(selected), distinct_local_dates=len(selected),
            evidence_fingerprint=fingerprint,
            rationale_code=RATIONALE_CODE,
            generator_version=GENERATOR_VERSION,
            created_at=now, updated_at=now,
        )
        return CompanionStrategyGenerationResult(
            "candidate_created", self._store.create(candidate, selected),
            len(observations), len(selected),
        )

    @staticmethod
    def _select_cluster(
        observations: tuple[CompanionStrategyObservation, ...],
        *, utc_offset_minutes: int,
    ) -> tuple[tuple[CompanionStrategyObservation, ...], int]:
        local_zone = timezone(timedelta(minutes=utc_offset_minutes))
        groups: dict[int, dict[str, CompanionStrategyObservation]] = defaultdict(dict)
        for item in observations:
            local = item.queued_at.astimezone(local_zone)
            bucket = (local.hour * 60 + local.minute) // BUCKET_MINUTES
            day = local.date().isoformat()
            # 同一天最多保留一条，避免密集测试或重复联系放大证据。
            previous = groups[bucket].get(day)
            if previous is None or item.latency_seconds < previous.latency_seconds:
                groups[bucket][day] = item
        if not groups:
            return (), 0
        best = max(groups.values(), key=lambda items: (len(items), sorted(items)[-1]))
        selected = tuple(sorted(best.values(), key=lambda item: item.queued_at))
        return selected, len(selected)
