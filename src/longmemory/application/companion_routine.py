"""从跨日用户主动出现时间提出弱习惯候选；不触发主动联系。"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
import hashlib
from statistics import median
from uuid import uuid4

from longmemory.core.companion import (
    CompanionRoutineCandidate,
    CompanionRoutineCandidateStore,
    CompanionStrategyCandidateStatus,
    UserInitiatedInteractionEvent,
)


GENERATOR_VERSION = "user-initiated-routine-candidate-v1"
RATIONALE_CODE = "repeated_user_initiated_activity_near_time"
MINIMUM_DISTINCT_DATES = 3
BUCKET_MINUTES = 30


@dataclass(frozen=True, slots=True)
class CompanionRoutineGenerationResult:
    outcome: str
    candidate: CompanionRoutineCandidate | None
    eligible_observation_count: int
    distinct_local_dates: int


class CompanionRoutineCandidateService:
    """只识别跨日时间重复；不从“缺席”推断情绪、需求或异常。"""

    def __init__(self, store: CompanionRoutineCandidateStore, *, clock=None,
                 id_factory=None) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: uuid4().hex)

    def generate(
        self, subject_id: str, *, utc_offset_minutes: int,
    ) -> CompanionRoutineGenerationResult:
        observations = self._store.list_observations(subject_id)
        current = self._store.get_current(subject_id)
        if current is not None:
            return CompanionRoutineGenerationResult(
                "current_candidate_exists", current, len(observations),
                current.distinct_local_dates,
            )
        selected, date_count = self._select_cluster(
            observations, utc_offset_minutes=utc_offset_minutes,
        )
        if len(selected) < MINIMUM_DISTINCT_DATES:
            return CompanionRoutineGenerationResult(
                "insufficient_cross_date_evidence", None,
                len(observations), date_count,
            )

        local_zone = timezone(timedelta(minutes=utc_offset_minutes))
        minutes = [
            item.occurred_at.astimezone(local_zone).hour * 60
            + item.occurred_at.astimezone(local_zone).minute
            for item in selected
        ]
        expected_minute = int(median(minutes))
        source_ids = sorted(item.id for item in selected)
        fingerprint = hashlib.sha256(
            (f"{GENERATOR_VERSION}\n{utc_offset_minutes}\n{expected_minute}\n"
             + "\n".join(source_ids)).encode()
        ).hexdigest()
        existing = self._store.get_by_fingerprint(subject_id, fingerprint)
        if existing is not None:
            return CompanionRoutineGenerationResult(
                "evidence_already_analyzed", existing,
                len(observations), len(selected),
            )

        now = self._clock()
        candidate = CompanionRoutineCandidate(
            id=self._id_factory(), subject_id=subject_id,
            status=CompanionStrategyCandidateStatus.CANDIDATE,
            expected_minute=expected_minute,
            utc_offset_minutes=utc_offset_minutes,
            observation_window_minutes=BUCKET_MINUTES,
            evidence_count=len(selected), distinct_local_dates=len(selected),
            evidence_fingerprint=fingerprint,
            rationale_code=RATIONALE_CODE,
            generator_version=GENERATOR_VERSION,
            created_at=now, updated_at=now,
        )
        return CompanionRoutineGenerationResult(
            "candidate_created", self._store.create(candidate, selected),
            len(observations), len(selected),
        )

    @staticmethod
    def _select_cluster(
        observations: tuple[UserInitiatedInteractionEvent, ...],
        *, utc_offset_minutes: int,
    ) -> tuple[tuple[UserInitiatedInteractionEvent, ...], int]:
        local_zone = timezone(timedelta(minutes=utc_offset_minutes))
        groups: dict[int, dict[str, UserInitiatedInteractionEvent]] = defaultdict(dict)
        for item in observations:
            local = item.occurred_at.astimezone(local_zone)
            bucket = (local.hour * 60 + local.minute) // BUCKET_MINUTES
            day = local.date().isoformat()
            previous = groups[bucket].get(day)
            if previous is None or item.occurred_at < previous.occurred_at:
                groups[bucket][day] = item
        if not groups:
            return (), 0
        best = max(groups.values(), key=lambda items: (len(items), sorted(items)[-1]))
        selected = tuple(sorted(best.values(), key=lambda item: item.occurred_at))
        return selected, len(selected)
