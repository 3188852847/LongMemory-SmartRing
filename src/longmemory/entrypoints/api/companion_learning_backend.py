"""陪伴策略学习的控制台边界。

这里管理用户主动交互观察、时间习惯候选和缺席策略版本。它不负责后台定时执行，
因此学习/复核策略可以独立演进，而不会与圆屏投递生命周期绑死。
"""

from datetime import datetime, timedelta, timezone

from longmemory.adapters.storage.sqlite_companion_absence_strategy_store import (
    SQLiteCompanionAbsenceStrategyVersionStore,
)
from longmemory.adapters.storage.sqlite_companion_routine_store import (
    SQLiteCompanionRoutineCandidateStore,
)
from longmemory.adapters.storage.sqlite_companion_strategy_store import (
    SQLiteCompanionStrategyCandidateStore,
)
from longmemory.adapters.storage.sqlite_proactive_policy_store import (
    SQLiteProactivePolicyStore,
)
from longmemory.adapters.storage.sqlite_user_initiated_interaction_store import (
    SQLiteUserInitiatedInteractionStore,
)
from longmemory.application.companion_absence_strategy import (
    CompanionAbsenceStrategyVersionService,
)
from longmemory.application.companion_routine import CompanionRoutineCandidateService
from longmemory.application.companion_strategy import CompanionStrategyCandidateService
from longmemory.core.companion import CompanionStrategyReplayEvidence
from longmemory.evaluation.companion.absence_replay import (
    load_replay_dataset,
    run_replay,
)

from .errors import MemoryAccessError
from .proactive_presenters import (
    absence_selection_json,
    absence_strategy_version_json,
    absence_switch_event_json,
    routine_candidate_json,
    strategy_candidate_json,
)


class CompanionLearningBackend:
    """把陪伴学习的管理操作装配到数据库端口，保持 HTTP 层稳定。"""

    def __init__(self, *, open_database, clock):
        self._open_database = open_database
        self._clock = clock

    def list_strategy_candidates(self):
        with self._open_database() as connection:
            store = SQLiteCompanionStrategyCandidateStore(connection)
            return {"items": [
                strategy_candidate_json(candidate, store)
                for candidate in store.list("user:self")
            ]}

    def list_user_initiated_interactions(self, *, limit=30):
        """只返回时间与来源 ID，不把私人消息正文复制到观察视图。"""

        if not 1 <= limit <= 100:
            raise ValueError("user_initiated_interaction_limit_invalid")
        with self._open_database() as connection:
            policy = SQLiteProactivePolicyStore(connection).get("user:self")
            local_zone = timezone(
                timedelta(minutes=policy.config.utc_offset_minutes)
            )
            rows = SQLiteUserInitiatedInteractionStore(connection).list_recent(
                "user:self", limit=limit,
            )
            items = []
            for row in rows:
                local = datetime.fromisoformat(row["occurred_at"]).astimezone(
                    local_zone
                )
                items.append({
                    **row,
                    "local_date": local.date().isoformat(),
                    "local_minute": local.hour * 60 + local.minute,
                    "utc_offset_minutes": policy.config.utc_offset_minutes,
                })
            return {"items": items}

    def list_routine_candidates(self):
        with self._open_database() as connection:
            store = SQLiteCompanionRoutineCandidateStore(connection)
            return {"items": [
                routine_candidate_json(candidate, store)
                for candidate in store.list("user:self")
            ]}

    def generate_routine_candidate(self):
        """分析用户主动出现时间；候选不会自动变成联系规则。"""

        with self._open_database(write_capability="proactive") as connection:
            policy = SQLiteProactivePolicyStore(connection).get("user:self")
            store = SQLiteCompanionRoutineCandidateStore(connection)
            result = CompanionRoutineCandidateService(
                store, clock=self._clock,
            ).generate(
                "user:self",
                utc_offset_minutes=policy.config.utc_offset_minutes,
            )
            return {
                "outcome": result.outcome,
                "eligible_observation_count": result.eligible_observation_count,
                "distinct_local_dates": result.distinct_local_dates,
                "candidate": (
                    None if result.candidate is None
                    else routine_candidate_json(result.candidate, store)
                ),
            }

    def dismiss_routine_candidate(self, candidate_id, *, expected_revision):
        with self._open_database(write_capability="proactive") as connection:
            store = SQLiteCompanionRoutineCandidateStore(connection)
            candidate = store.dismiss(
                candidate_id, subject_id="user:self",
                expected_revision=expected_revision, now=self._clock(),
            )
            if candidate is None:
                raise MemoryAccessError("companion_routine_candidate_conflict", 409)
            return routine_candidate_json(candidate, store)

    def list_absence_strategy_versions(self):
        with self._open_database() as connection:
            store = SQLiteCompanionAbsenceStrategyVersionStore(connection)
            versions = store.list("user:self")
            selection = store.get_selection("user:self")
            return {
                "items": [
                    absence_strategy_version_json(
                        version,
                        active=(
                            selection is not None
                            and selection.version_id == version.id
                        ),
                    )
                    for version in versions
                ],
                "selection": absence_selection_json(selection),
                "events": [
                    absence_switch_event_json(event)
                    for event in store.list_switch_events("user:self")
                ],
            }

    def select_absence_strategy_version(self, request, *, rollback=False):
        with self._open_database(write_capability="proactive") as connection:
            service = CompanionAbsenceStrategyVersionService(
                SQLiteCompanionAbsenceStrategyVersionStore(connection),
                clock=self._clock,
            )
            try:
                selection, event = service.select_version(
                    request.version_id,
                    subject_id="user:self",
                    expected_revision=request.expected_revision,
                    rollback=rollback,
                )
            except ValueError as error:
                code = str(error)
                status = 404 if code == "companion_absence_version_missing" else 409
                raise MemoryAccessError(code, status) from None
            return {
                "selection": absence_selection_json(selection),
                "event": absence_switch_event_json(event),
                "runtime_connected": True,
            }

    def deactivate_absence_strategy(self, request):
        with self._open_database(write_capability="proactive") as connection:
            service = CompanionAbsenceStrategyVersionService(
                SQLiteCompanionAbsenceStrategyVersionStore(connection),
                clock=self._clock,
            )
            try:
                selection, event = service.deactivate(
                    subject_id="user:self",
                    expected_revision=request.expected_revision,
                )
            except ValueError as error:
                raise MemoryAccessError(str(error), 409) from None
            return {
                "selection": absence_selection_json(selection),
                "event": absence_switch_event_json(event),
                "runtime_connected": True,
            }

    def create_absence_strategy_version(self, request):
        """用固定回放集验证候选并保存版本；不会自动激活策略。"""

        with self._open_database(write_capability="proactive") as connection:
            policy = SQLiteProactivePolicyStore(connection).get("user:self")
            store = SQLiteCompanionAbsenceStrategyVersionStore(connection)
            try:
                replayed_at = self._clock()
                report = run_replay(load_replay_dataset())
                summary = report["summary"]
                replay = CompanionStrategyReplayEvidence(
                    protocol=report["protocol"],
                    dataset_name=report["dataset"]["name"],
                    dataset_version=report["dataset"]["version"],
                    dataset_sha256=report["dataset"]["sha256"],
                    case_count=summary["total"],
                    matched_count=summary["matched"],
                    unsafe_allow_count=summary["unsafe_allow_count"],
                    gate_passed=summary["gate_passed"],
                    replayed_at=replayed_at,
                )
                result = CompanionAbsenceStrategyVersionService(
                    store, clock=self._clock,
                ).create_from_candidate(
                    request.candidate_id,
                    subject_id="user:self",
                    expected_candidate_revision=request.expected_candidate_revision,
                    allowed_weekdays=policy.config.allowed_weekdays,
                    replay=replay,
                )
            except ValueError as error:
                if str(error) == "companion_routine_candidate_conflict":
                    raise MemoryAccessError(str(error), 409) from None
                if str(error) == "absence_routine_draft_invalid":
                    raise MemoryAccessError(
                        "companion_absence_strategy_unsupported", 409,
                    ) from None
                raise
            return {
                "outcome": result.outcome,
                "version": absence_strategy_version_json(result.version),
            }

    def generate_strategy_candidate(self):
        """只生成未生效候选；不读取消息正文、不修改 P4 设置。"""

        with self._open_database(write_capability="proactive") as connection:
            policy = SQLiteProactivePolicyStore(connection).get("user:self")
            store = SQLiteCompanionStrategyCandidateStore(connection)
            result = CompanionStrategyCandidateService(
                store, clock=self._clock,
            ).generate(
                "user:self",
                utc_offset_minutes=policy.config.utc_offset_minutes,
            )
            return {
                "outcome": result.outcome,
                "eligible_observation_count": result.eligible_observation_count,
                "distinct_local_dates": result.distinct_local_dates,
                "candidate": (
                    None if result.candidate is None
                    else strategy_candidate_json(result.candidate, store)
                ),
            }

    def dismiss_strategy_candidate(self, candidate_id, *, expected_revision):
        with self._open_database(write_capability="proactive") as connection:
            store = SQLiteCompanionStrategyCandidateStore(connection)
            candidate = store.dismiss(
                candidate_id,
                subject_id="user:self",
                expected_revision=expected_revision,
                now=self._clock(),
            )
            if candidate is None:
                raise MemoryAccessError("companion_strategy_candidate_conflict", 409)
            return strategy_candidate_json(candidate, store)
