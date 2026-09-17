"""主动交流策略的控制台管理协作者。

该对象只处理所有者可见的策略、开发期定时授权和 L2 话题种子管理。
数据库路径、结构校验和写权限仍由 MemoryBackend 注入的打开函数统一守卫，
因此拆分不会建立第二套安全边界，也不会改变后台投递行为。
"""

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from longmemory.adapters.storage.sqlite_proactive_outreach_store import (
    SQLiteProactiveOutreachStore,
)
from longmemory.adapters.storage.sqlite_proactive_policy_store import (
    SQLiteProactivePolicyStore,
)
from longmemory.adapters.storage.sqlite_proactive_runtime_state import (
    SQLiteProactiveHistoryReader,
)
from longmemory.adapters.storage.sqlite_proactive_schedule_override_store import (
    SQLiteProactiveScheduleOverrideStore,
)
from longmemory.adapters.storage.sqlite_proactive_topic_store import (
    SQLiteProactiveTopicStore,
)
from longmemory.adapters.storage.sqlite_follow_up_store import SQLiteFollowUpCandidateStore
from longmemory.adapters.storage.sqlite_interaction_outcome_store import SQLiteInteractionOutcomeStore
from longmemory.adapters.storage.sqlite_companion_feedback_store import SQLiteCompanionFeedbackStore
from longmemory.adapters.storage.sqlite_companion_absence_strategy_store import SQLiteCompanionAbsenceStrategyVersionStore
from longmemory.application.proactive import ProactiveOutreachLedger
from longmemory.core.common.identifiers import MemoryId
from longmemory.core.proactive import (
    FollowUpCandidate,
    FollowUpCandidateStatus,
    OutreachEvidence,
    OutreachPolicyConfig,
    OutreachState,
    OutreachTrigger,
    ProactivePolicySettings,
    ProactiveTopicSeed,
    TopicSeedStatus,
    decide_scheduled_trigger,
    next_interval_anchor_minute,
    scheduled_trigger_slot,
)

from .errors import MemoryAccessError
from .memory_presenters import details_json, revision
from .proactive_presenters import (
    follow_up_json,
    outreach_result_json,
    proactive_policy_json,
    topic_seed_json,
)


class ProactiveBackend:
    """把主动交流的管理面与巨型记忆 CRUD 门面分离。"""

    def __init__(self, *, open_database, clock, memory_service_factory):
        self._open_database = open_database
        self._clock = clock
        self._memory_service_factory = memory_service_factory

    def policy(self):
        with self._open_database() as connection:
            return proactive_policy_json(
                SQLiteProactivePolicyStore(connection).get("user:self")
            )

    def schedule_status(self):
        """解释今天的定时触发条件；只读时间与状态，不读取对话正文。"""

        subject_id = "user:self"
        now = self._clock()
        with self._open_database() as connection:
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            history = SQLiteProactiveHistoryReader(connection)
            runtime = history.read(subject_id, now=now)
            offset = timezone(timedelta(minutes=settings.config.utc_offset_minutes))
            local_day = now.astimezone(offset).date()
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection, commit_changes=False),
                clock=lambda: now,
            )
            user_chatted_today = history.user_chatted_on_local_date(
                now=now,
                utc_offset_minutes=settings.config.utc_offset_minutes,
            )
            slot = scheduled_trigger_slot(settings, now=now)
            already_evaluated_today = bool(
                slot
                and ledger.get_by_idempotency(subject_id, slot[1]) is not None
            )
            override_store = SQLiteProactiveScheduleOverrideStore(connection)
            development_override = override_store.get_armed(subject_id)
            decision = decide_scheduled_trigger(
                settings,
                now=now,
                user_chatted_today=user_chatted_today,
                already_evaluated_today=already_evaluated_today,
            )
            return {
                "action": decision.action.value,
                "reason": decision.reason.value,
                "local_date": decision.local_date.isoformat(),
                "scheduled_for": (
                    decision.scheduled_for.isoformat()
                    if decision.scheduled_for is not None else None
                ),
                "user_chatted_today": user_chatted_today,
                "awaiting_user_response": runtime.awaiting_user_response,
                "already_evaluated_today": already_evaluated_today,
                "development_override": development_override,
                "latest_development_override": override_store.get_latest(subject_id),
            }

    def arm_schedule_override(self, request):
        """仅授权今天当前设置中的未来时刻；不立即投递。"""

        subject_id = "user:self"
        now = self._clock()
        with self._open_database(write_capability="proactive") as connection:
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            if settings.revision != request.expected_policy_revision:
                raise MemoryAccessError("proactive_settings_conflict", 409)
            if not settings.config.enabled or not settings.automatic_enabled:
                raise MemoryAccessError(
                    "proactive_schedule_override_requires_enabled", 400,
                )
            if settings.automatic_interval_seconds != 24 * 60 * 60:
                raise MemoryAccessError(
                    "proactive_schedule_override_daily_only", 400,
                )
            local_zone = timezone(
                timedelta(minutes=settings.config.utc_offset_minutes)
            )
            local_now = now.astimezone(local_zone)
            if local_now.weekday() not in settings.config.allowed_weekdays:
                raise MemoryAccessError(
                    "proactive_schedule_override_weekday_blocked", 400,
                )
            current_minute = local_now.hour * 60 + local_now.minute
            if current_minute >= settings.scheduled_minute:
                raise MemoryAccessError(
                    "proactive_schedule_override_time_not_future", 400,
                )
            try:
                return SQLiteProactiveScheduleOverrideStore(connection).arm(
                    override_id=secrets.token_hex(16),
                    subject_id=subject_id,
                    local_date=local_now.date().isoformat(),
                    scheduled_minute=settings.scheduled_minute,
                    policy_revision=settings.revision,
                    now=now,
                )
            except ValueError:
                raise MemoryAccessError(
                    "proactive_schedule_override_already_armed", 409,
                ) from None

    def cancel_schedule_override(self, override_id, *, expected_revision):
        now = self._clock()
        with self._open_database(write_capability="proactive") as connection:
            try:
                return SQLiteProactiveScheduleOverrideStore(connection).finish(
                    override_id,
                    subject_id="user:self",
                    expected_revision=expected_revision,
                    status="cancelled",
                    reason="owner_cancelled",
                    now=now,
                )
            except ValueError:
                raise MemoryAccessError(
                    "proactive_schedule_override_conflict", 409,
                ) from None

    def list_topic_seeds(self):
        now = self._clock()
        with self._open_database() as connection:
            rows = SQLiteProactiveTopicStore(connection).list("user:self")
            return {"items": [topic_seed_json(row, now=now) for row in rows]}

    def create_topic_seed(self, request):
        now = self._clock()
        seed = ProactiveTopicSeed(
            id=request.request_id.replace("-", ""),
            subject_id="user:self",
            scenario_id=request.scenario_id,
            prompt_text=request.prompt_text,
            status=TopicSeedStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        with self._open_database(write_capability="proactive") as connection:
            store = SQLiteProactiveTopicStore(connection)
            try:
                store.create(
                    seed,
                    expected_scenario_revision=request.expected_scenario_revision,
                )
            except sqlite3.IntegrityError:
                existing = connection.execute(
                    "SELECT id FROM proactive_topic_seeds WHERE id=?", (seed.id,),
                ).fetchone()
                code = (
                    "topic_seed_request_replayed" if existing else "topic_seed_conflict"
                )
                raise MemoryAccessError(code, 409) from None
            except ValueError as error:
                code = str(error)
                status = 404 if code == "topic_seed_scenario_not_found" else 409
                raise MemoryAccessError(code, status) from None
            row = next(
                item for item in store.list("user:self") if item["id"] == seed.id
            )
            return topic_seed_json(row, now=now)

    def disable_topic_seed(self, seed_id, *, expected_revision):
        now = self._clock()
        with self._open_database(write_capability="proactive") as connection:
            row = connection.execute(
                "SELECT subject_id,status,revision FROM proactive_topic_seeds WHERE id=?",
                (seed_id,),
            ).fetchone()
            if row is None or row["subject_id"] != "user:self":
                raise MemoryAccessError("topic_seed_not_found", 404)
            if row["status"] == "disabled":
                if row["revision"] == expected_revision + 1:
                    return {
                        "id": seed_id, "status": "disabled",
                        "revision": row["revision"], "replayed": True,
                    }
                raise MemoryAccessError("topic_seed_conflict", 409)
            if not SQLiteProactiveTopicStore(connection).disable(
                seed_id, expected_revision=expected_revision, now=now,
            ):
                raise MemoryAccessError("topic_seed_conflict", 409)
            return {
                "id": seed_id, "status": "disabled",
                "revision": expected_revision + 1, "replayed": False,
            }

    def update_policy(self, request):
        # 在取得写锁前完成纯配置验证；非法输入不能被误报成数据库损坏。
        try:
            config = OutreachPolicyConfig(
                enabled=request.enabled,
                utc_offset_minutes=request.utc_offset_minutes,
                allowed_weekdays=tuple(request.allowed_weekdays),
                allowed_start_minute=request.allowed_start_minute,
                allowed_end_minute=request.allowed_end_minute,
                daily_limit=request.daily_limit,
                minimum_interval=timedelta(seconds=request.minimum_interval_seconds),
                maximum_lifetime=timedelta(seconds=request.maximum_lifetime_seconds),
            )
        except ValueError:
            raise MemoryAccessError("invalid_proactive_policy", 400) from None
        with self._open_database(write_capability="proactive") as connection:
            store = SQLiteProactivePolicyStore(connection)
            current = store.get("user:self")
            if current.revision != request.expected_revision:
                raise MemoryAccessError("proactive_settings_conflict", 409)
            interval_seconds = (
                request.automatic_interval_seconds
                if request.automatic_interval_seconds is not None
                else current.automatic_interval_seconds
            )
            dynamic_greeting_enabled = (
                request.dynamic_greeting_enabled
                if request.dynamic_greeting_enabled is not None
                else current.dynamic_greeting_enabled
            )
            now = self._clock()
            scheduled_minute = request.scheduled_minute
            if request.automatic_enabled and interval_seconds < 24 * 60 * 60:
                scheduled_minute = next_interval_anchor_minute(config, now=now)
            try:
                updated = ProactivePolicySettings(
                    "user:self", config, request.quiet_until,
                    current.revision + 1, now,
                    request.automatic_enabled, scheduled_minute,
                    request.greeting_text, request.topic_enabled,
                    interval_seconds,
                    dynamic_greeting_enabled,
                )
            except ValueError:
                raise MemoryAccessError("invalid_proactive_policy", 400) from None
            return proactive_policy_json(
                store.save(updated, expected_revision=current.revision)
            )

    def list_follow_ups(self):
        now = self._clock()
        with self._open_database() as connection:
            rows = SQLiteFollowUpCandidateStore(connection).list("user:self")
            return {"items": [follow_up_json(row, now=now) for row in rows]}

    def create_follow_up(self, request):
        now = self._clock()
        if request.follow_up_at <= now:
            raise MemoryAccessError("follow_up_time_not_future", 400)
        with self._open_database(write_capability="proactive") as connection:
            details = self._memory_service_factory(connection).get_memory(
                MemoryId(request.source_memory_id)
            )
            if details is None:
                raise MemoryAccessError("follow_up_source_not_found", 404)
            if not secrets.compare_digest(
                revision(details_json(details)), request.expected_memory_revision,
            ):
                raise MemoryAccessError("follow_up_source_conflict", 409)
            if details.memory.retired_at is not None:
                raise MemoryAccessError("follow_up_source_not_current", 409)
            candidate = FollowUpCandidate(
                id=request.request_id.replace("-", ""),
                subject_id="user:self",
                source_memory_id=request.source_memory_id,
                source_content_sha256=hashlib.sha256(
                    details.memory.content.encode("utf-8")
                ).hexdigest(),
                prompt_text=request.prompt_text,
                follow_up_at=request.follow_up_at,
                status=FollowUpCandidateStatus.CANDIDATE,
                created_at=now,
                updated_at=now,
            )
            store = SQLiteFollowUpCandidateStore(connection)
            try:
                store.create(candidate)
            except sqlite3.IntegrityError:
                existing = connection.execute(
                    "SELECT id FROM companion_follow_up_candidates WHERE id=?",
                    (candidate.id,),
                ).fetchone()
                code = (
                    "follow_up_request_replayed" if existing else "follow_up_conflict"
                )
                raise MemoryAccessError(code, 409) from None
            except ValueError as error:
                code = str(error)
                status = 404 if code == "follow_up_source_not_found" else 409
                raise MemoryAccessError(code, status) from None
            row = next(
                item for item in store.list("user:self") if item["id"] == candidate.id
            )
            return follow_up_json(row, now=now)

    def cancel_follow_up(self, candidate_id, *, expected_revision):
        now = self._clock()
        with self._open_database(write_capability="proactive") as connection:
            row = connection.execute(
                "SELECT subject_id,status,revision FROM companion_follow_up_candidates "
                "WHERE id=?", (candidate_id,),
            ).fetchone()
            if row is None or row["subject_id"] != "user:self":
                raise MemoryAccessError("follow_up_not_found", 404)
            if row["status"] == "cancelled":
                if row["revision"] == expected_revision + 1:
                    return {
                        "id": candidate_id, "status": "cancelled",
                        "revision": row["revision"], "replayed": True,
                    }
                raise MemoryAccessError("follow_up_conflict", 409)
            outreach_store = SQLiteProactiveOutreachStore(
                connection, commit_changes=False,
            )
            outreach_row = connection.execute(
                "SELECT id FROM proactive_outreach WHERE follow_up_candidate_id=?",
                (candidate_id,),
            ).fetchone()
            if outreach_row is not None:
                ledger = ProactiveOutreachLedger(outreach_store, clock=lambda: now)
                outreach = ledger.get(outreach_row["id"])
                if outreach is None or outreach.state != OutreachState.CANDIDATE:
                    raise MemoryAccessError("follow_up_already_attempted", 409)
                ledger.record_transition(
                    outreach.id,
                    expected_revision=outreach.revision,
                    new_state=OutreachState.CANCELLED,
                    reason_code="owner_cancelled_follow_up",
                    evidence=OutreachEvidence.POLICY_DECISION,
                )
            if not SQLiteFollowUpCandidateStore(
                connection, commit_changes=False,
            ).cancel(
                candidate_id, expected_revision=expected_revision, now=now,
            ):
                raise MemoryAccessError("follow_up_conflict", 409)
            connection.commit()
            return {
                "id": candidate_id, "status": "cancelled",
                "revision": expected_revision + 1, "replayed": False,
            }

    def arm_follow_up(
        self, candidate_id, *, expected_revision, expected_policy_revision,
    ):
        """显式建立未来账本；这里不探测设备，也不产生任何即时播报。"""

        now = self._clock()
        with self._open_database(write_capability="proactive") as connection:
            store = SQLiteFollowUpCandidateStore(connection)
            row = next(
                (item for item in store.list("user:self") if item["id"] == candidate_id),
                None,
            )
            if row is None:
                raise MemoryAccessError("follow_up_not_found", 404)
            if row["revision"] != expected_revision:
                raise MemoryAccessError("follow_up_conflict", 409)
            current = follow_up_json(row, now=now)
            if row["outreach_id"] is not None:
                return {**current, "replayed": True}
            if not current["ready_for_activation"]:
                raise MemoryAccessError(
                    f"follow_up_{current['blocked_reason'] or 'not_ready'}", 409,
                )
            settings = SQLiteProactivePolicyStore(connection).get("user:self")
            if settings.revision != expected_policy_revision:
                raise MemoryAccessError("proactive_settings_conflict", 409)
            if not settings.config.enabled:
                raise MemoryAccessError("follow_up_requires_proactive_enabled", 409)
            scheduled_for = datetime.fromisoformat(row["follow_up_at"])
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection), clock=lambda: now,
            )
            try:
                ledger.create_candidate(
                    subject_id="user:self",
                    trigger=OutreachTrigger.EXPLICIT_SCHEDULE,
                    trigger_reason_code="owner_approved_l1_follow_up",
                    content=row["prompt_text"],
                    scheduled_for=scheduled_for,
                    expires_at=scheduled_for + settings.config.maximum_lifetime,
                    idempotency_key=f"follow-up:{candidate_id}",
                    policy_version=settings.config.policy_version,
                    follow_up_candidate_id=candidate_id,
                    follow_up_candidate_revision=row["revision"],
                )
            except ValueError:
                raise MemoryAccessError("follow_up_activation_conflict", 409) from None
            refreshed = next(
                item for item in store.list("user:self") if item["id"] == candidate_id
            )
            return {**follow_up_json(refreshed, now=now), "replayed": False}

    def confirm_played(self, outreach_id, *, expected_revision):
        """把所有者亲耳观察追加为证据；不从设备状态反推播放成功。"""

        subject_id = "user:self"
        with self._open_database(write_capability="proactive") as connection:
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection), clock=self._clock,
            )
            outreach = ledger.get(outreach_id)
            if outreach is None or outreach.subject_id != subject_id:
                raise MemoryAccessError("proactive_outreach_not_found", 404)
            if outreach.state == OutreachState.PLAYED:
                return outreach_result_json(outreach, replayed=True)
            if outreach.revision != expected_revision:
                raise MemoryAccessError("proactive_outreach_conflict", 409)
            if outreach.state not in {
                OutreachState.QUEUED,
                OutreachState.TRANSPORT_SENT,
                OutreachState.DEVICE_ACKNOWLEDGED,
            }:
                raise MemoryAccessError(
                    "proactive_playback_confirmation_invalid_state", 409,
                )
            try:
                played = ledger.record_transition(
                    outreach.id,
                    expected_revision=outreach.revision,
                    new_state=OutreachState.PLAYED,
                    reason_code="user_confirmed_playback",
                    evidence=OutreachEvidence.USER_OBSERVED,
                )
            except ValueError:
                raise MemoryAccessError("proactive_outreach_conflict", 409) from None
            return outreach_result_json(played, replayed=False)

    def history(self, *, limit=20):
        """只读最近投影和最后事件原因，不暴露幂等键或内部连接数据。"""

        subject_id = "user:self"
        if type(limit) is not int or not 1 <= limit <= 100:
            raise MemoryAccessError("invalid_proactive_history_limit", 400)
        with self._open_database() as connection:
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection, commit_changes=False),
                clock=self._clock,
            )
            outcomes = SQLiteInteractionOutcomeStore(connection, commit_changes=False)
            feedbacks = SQLiteCompanionFeedbackStore(connection)
            absence_versions = SQLiteCompanionAbsenceStrategyVersionStore(connection)
            items = []
            for outreach in ledger.list_recent(subject_id, limit=limit):
                events = ledger.list_events(outreach.id)
                latest = events[-1]
                outcome = outcomes.get_for_outreach(outreach.id)
                feedback = feedbacks.get_for_outreach(outreach.id)
                formal_trigger = (
                    outreach.trigger.value != "manual_test"
                    and not outreach.trigger_reason_code.startswith("development_")
                )
                delivery_evidence = {
                    "queued": "server_queued",
                    "transport_sent": "transport_sent",
                    "device_acknowledged": "device_acknowledged",
                    "played": "played",
                }.get(outreach.state.value)
                if not formal_trigger:
                    observation_state = "not_applicable"
                elif outcome is not None:
                    observation_state = "subsequent_user_message_observed"
                elif delivery_evidence is not None:
                    observation_state = "awaiting_subsequent_user_message"
                else:
                    observation_state = "delivery_not_established"
                strategy_version = (
                    absence_versions.get_version(
                        outreach.strategy_version_id, subject_id=subject_id,
                    ) if outreach.strategy_version_id is not None else None
                )
                strategy_source = None if strategy_version is None else {
                    "version_id": strategy_version.id,
                    "selection_revision": outreach.strategy_selection_revision,
                    "evaluated_local_date": outreach.strategy_evaluated_local_date,
                    "source_candidate_id": strategy_version.source_candidate_id,
                    "source_candidate_revision": strategy_version.source_candidate_revision,
                    "expected_minute": strategy_version.expected_minute,
                    "grace_minutes": strategy_version.grace_minutes,
                    "utc_offset_minutes": strategy_version.utc_offset_minutes,
                    "trigger_policy_version": strategy_version.trigger_policy_version,
                }
                items.append({
                    "outreach_id": outreach.id,
                    "trigger": outreach.trigger.value,
                    "content": outreach.content,
                    "created_at": outreach.created_at.isoformat(),
                    "expires_at": outreach.expires_at.isoformat(),
                    "state": outreach.state.value,
                    "revision": outreach.revision,
                    "reason": latest.reason_code,
                    "event_count": len(events),
                    "failure_reason": outreach.failure_reason,
                    "topic_seed_id": outreach.topic_seed_id,
                    "topic_seed_revision": outreach.topic_seed_revision,
                    "follow_up_source": None if outreach.follow_up_candidate_id is None else {
                        "candidate_id": outreach.follow_up_candidate_id,
                        "candidate_revision": outreach.follow_up_candidate_revision,
                        "scheduled_for": outreach.scheduled_for.isoformat(),
                    },
                    "strategy_source": strategy_source,
                    "outcome_observation_state": observation_state,
                    "delivery_evidence_level": delivery_evidence,
                    "subsequent_user_message": None if outcome is None else {
                        "occurred_at": outcome.occurred_at.isoformat(),
                        "latency_seconds": outcome.latency_seconds,
                        "evidence": outcome.evidence.value,
                    },
                    "explicit_feedback": feedback,
                })
            return {"items": items}
