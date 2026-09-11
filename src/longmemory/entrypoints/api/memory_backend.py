"""网页记忆管理的装配边界：只打开显式指定的已有数据库，不运行建库/迁移。"""

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from longmemory.adapters.storage.sqlite_conversation_store import SQLiteConversationStore
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.adapters.storage.sqlite_consolidation_run_store import (
    SQLiteConsolidationRunStore,
)
from longmemory.adapters.storage.sqlite_proactive_policy_store import SQLiteProactivePolicyStore
from longmemory.adapters.storage.sqlite_proactive_outreach_store import SQLiteProactiveOutreachStore
from longmemory.adapters.storage.sqlite_companion_absence_strategy_store import (
    SQLiteCompanionAbsenceStrategyVersionStore,
)
from longmemory.adapters.storage.sqlite_user_initiated_interaction_store import (
    SQLiteUserInitiatedInteractionStore,
)
from longmemory.adapters.storage.sqlite_proactive_runtime_state import SQLiteProactiveHistoryReader
from longmemory.adapters.storage.sqlite_proactive_topic_store import SQLiteProactiveTopicStore
from longmemory.adapters.storage.sqlite_proactive_schedule_override_store import (
    SQLiteProactiveScheduleOverrideStore,
)
from longmemory.adapters.device_control import (
    XiaozhiProactiveDelivery,
    XiaozhiRuntimeStateProbe,
)
from longmemory.application.proactive import (
    ProactiveOutreachDispatcher,
    ProactiveOutreachLedger,
)
from longmemory.core.companion import (
    AbsenceRoutineDraft,
    AbsenceRoutineState,
    AbsenceTriggerAction,
    decide_routine_absence,
)
from longmemory.core.proactive import (
    OutreachEvidence,
    OutreachPolicyState,
    OutreachState,
    OutreachTrigger,
    ScheduledTriggerAction,
    decide_scheduled_trigger,
)
from longmemory.adapters.storage.sqlite_l1_consolidation_source_reader import (
    SQLiteL1ConsolidationSourceReader,
)
from longmemory.adapters.storage.sqlite_l2_consolidation_source_reader import (
    SQLiteL2ConsolidationSourceReader,
)
from longmemory.application.consolidation.l2_to_l3_service import L3_TRIGGER_CONFIG
from longmemory.application.consolidation.status_service import ConsolidationStatusService
from longmemory.application.memory_management.service import MemoryManagementService
from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.memory.l1_atomic.models import CURRENT_USER_SUBJECT_ID
from longmemory.core.memory.consolidation.trigger_policy import ConsolidationTriggerConfig
from longmemory.infrastructure.database.schema import SCHEMA_VERSION
from .memory_presenters import (
    details_json,
    memory_json,
    revision,
)
from .proactive_presenters import outreach_result_json
from .errors import MemoryAccessError
from .scenario_backend import ScenarioBackend
from .persona_backend import PersonaBackend
from .proactive_backend import ProactiveBackend
from .companion_learning_backend import CompanionLearningBackend


class MemoryBackend:
    def __init__(self, database: Path | None, *, allow_delete=False, allow_correction=False,
                 allow_scenario_management=False, allow_persona_management=False,
                 scenario_producer=None,
                 scenario_model=None, persona_producer=None, persona_model=None,
                 consolidation_background_enabled=False, clock=None):
        # 路径只来自启动参数；任何 HTTP 请求都不能选文件或切换数据库。
        self.database = database.resolve() if database is not None else None
        self.allow_delete = allow_delete
        self.allow_correction = allow_correction
        self.allow_scenario_management = allow_scenario_management
        self.allow_persona_management = allow_persona_management
        self.scenario_producer = scenario_producer
        self.scenario_model = scenario_model
        self.persona_producer = persona_producer
        self.persona_model = persona_model
        self.consolidation_background_enabled = consolidation_background_enabled
        self.clock = clock or (lambda: datetime.now(UTC))
        self.scenarios = ScenarioBackend(
            open_database=self._open,
            allow_management=self.allow_scenario_management,
            producer=self.scenario_producer,
            model=self.scenario_model,
        )
        self.personas = PersonaBackend(
            open_database=self._open,
            allow_management=self.allow_persona_management,
            producer=self.persona_producer,
            model=self.persona_model,
        )
        self.proactive = ProactiveBackend(
            open_database=self._open,
            clock=self.clock,
            memory_service_factory=self._service,
        )
        self.companion_learning = CompanionLearningBackend(
            open_database=self._open,
            clock=self.clock,
        )

    def info(self):
        return {"configured": self.database is not None,
                "database": str(self.database) if self.database else None,
                "allow_delete": self.allow_delete and self.database is not None,
                "allow_clear": self.allow_delete and self.database is not None,
                "allow_correction": self.allow_correction and self.database is not None,
                # 当前两个操作共用同一个显式启动权限，但对前端公开独立能力名，
                # 以后拆分权限时不需要再改变页面语义。
                "allow_change": self.allow_correction and self.database is not None,
                "allow_promote_source": self.allow_correction and self.database is not None,
                "allow_scenario_management": (
                    self.allow_scenario_management and self.database is not None
                ),
                "allow_persona_management": (
                    self.allow_persona_management and self.database is not None
                ),
                "scenario_model_preview_available": (
                    self.allow_scenario_management
                    and self.database is not None
                    and self.scenario_producer is not None
                ),
                "scenario_model": self.scenario_model if self.scenario_producer else None,
                "persona_model_preview_available": (
                    self.allow_persona_management
                    and self.database is not None
                    and self.persona_producer is not None
                ),
                "persona_model": self.persona_model if self.persona_producer else None}

    def proactive_policy(self):
        return self.proactive.policy()

    def proactive_schedule_status(self):
        """解释今天的定时触发条件；只读时间与状态，不读取对话正文。"""

        return self.proactive.schedule_status()

    def arm_proactive_schedule_override(self, request):
        """仅授权今天当前设置中的未来时刻；不立即投递。"""

        return self.proactive.arm_schedule_override(request)

    def cancel_proactive_schedule_override(
        self, override_id, *, expected_revision,
    ):
        return self.proactive.cancel_schedule_override(
            override_id, expected_revision=expected_revision,
        )

    def list_proactive_topic_seeds(self):
        return self.proactive.list_topic_seeds()

    def create_proactive_topic_seed(self, request):
        return self.proactive.create_topic_seed(request)

    def disable_proactive_topic_seed(self, seed_id, *, expected_revision):
        return self.proactive.disable_topic_seed(
            seed_id, expected_revision=expected_revision,
        )

    def list_follow_up_candidates(self):
        return self.proactive.list_follow_ups()

    def create_follow_up_candidate(self, request):
        return self.proactive.create_follow_up(request)

    def cancel_follow_up_candidate(self, candidate_id, *, expected_revision):
        return self.proactive.cancel_follow_up(
            candidate_id, expected_revision=expected_revision,
        )

    def arm_follow_up_candidate(
        self, candidate_id, *, expected_revision, expected_policy_revision,
    ):
        """显式建立未来账本；这里不探测设备，也不产生任何即时播报。"""

        return self.proactive.arm_follow_up(
            candidate_id,
            expected_revision=expected_revision,
            expected_policy_revision=expected_policy_revision,
        )

    def update_proactive_policy(self, request):
        return self.proactive.update_policy(request)

    async def proactive_test(self, request, client):
        """执行一次用户明确发起的短文本测试；同 request_id 绝不重播。"""

        subject_id = "user:self"
        idempotency_key = "manual-console:" + request.request_id
        with self._open() as connection:
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection, commit_changes=False),
                clock=self.clock,
            )
            existing = ledger.get_by_idempotency(subject_id, idempotency_key)
            if existing is not None:
                return outreach_result_json(existing, replayed=True)
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            if settings.revision != request.expected_policy_revision:
                raise MemoryAccessError("proactive_settings_conflict", 409)

        device = await XiaozhiRuntimeStateProbe(client).probe()
        now = self.clock()
        with self._open(write_capability="proactive") as connection:
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection), clock=lambda: now,
            )
            existing = ledger.get_by_idempotency(subject_id, idempotency_key)
            if existing is not None:
                return outreach_result_json(existing, replayed=True, device=device)
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            if settings.revision != request.expected_policy_revision:
                raise MemoryAccessError("proactive_settings_conflict", 409)
            runtime = SQLiteProactiveHistoryReader(connection).read(subject_id, now=now)
            runtime = OutreachPolicyState(
                attempted_at=runtime.attempted_at,
                # 所有者显式点击属于诊断动作，不是系统自主追问；其余许可、
                # 时段、频率、勿扰和设备会话门控仍保持。
                awaiting_user_response=False,
                user_session_active=device.user_session_active,
                quiet_until=settings.quiet_until,
            )
            try:
                outreach = ledger.create_candidate(
                    subject_id=subject_id,
                    trigger=OutreachTrigger.MANUAL_TEST,
                    trigger_reason_code="manual_console_test",
                    content=request.text,
                    scheduled_for=now,
                    expires_at=now + settings.config.maximum_lifetime,
                    idempotency_key=idempotency_key,
                    policy_version=settings.config.policy_version,
                )
                result = await ProactiveOutreachDispatcher(
                    ledger,
                    delivery_queue=XiaozhiProactiveDelivery(client).queue,
                    clock=lambda: now,
                ).dispatch(
                    outreach.id,
                    expected_revision=outreach.revision,
                    settings=settings,
                    runtime_state=runtime,
                )
            except ValueError:
                raise MemoryAccessError("proactive_dispatch_conflict", 409) from None
            return outreach_result_json(
                result.outreach,
                replayed=False,
                decision=result.decision,
                delivery=result.delivery,
                device=device,
            )

    async def proactive_scheduled_tick(self, client):
        """评估当前当地分钟一次；不补发、不调用模型、不自动重试投递。"""

        subject_id = "user:self"
        now = self.clock()
        development_override = None
        invalid_override = None
        with self._open() as connection:
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            history = SQLiteProactiveHistoryReader(connection)
            offset = timezone(timedelta(minutes=settings.config.utc_offset_minutes))
            local_now = now.astimezone(offset)
            local_day = local_now.date()
            idempotency_key = f"explicit-schedule:{local_day.isoformat()}"
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection, commit_changes=False),
                clock=lambda: now,
            )
            development_override = SQLiteProactiveScheduleOverrideStore(
                connection
            ).get_armed(subject_id)
            if development_override is not None:
                invalid_reason = None
                if (
                    development_override["local_date"] != local_day.isoformat()
                    or development_override["scheduled_minute"]
                    != settings.scheduled_minute
                    or development_override["policy_revision"] != settings.revision
                ):
                    invalid_reason = "configuration_changed_or_date_expired"
                elif not settings.config.enabled or not settings.automatic_enabled:
                    invalid_reason = "automatic_setting_disabled"
                elif local_now.weekday() not in settings.config.allowed_weekdays:
                    invalid_reason = "weekday_no_longer_allowed"
                elif (
                    local_now.hour * 60 + local_now.minute
                    > development_override["scheduled_minute"]
                ):
                    invalid_reason = "scheduled_minute_missed"
                if invalid_reason is not None:
                    invalid_override = (
                        development_override["id"],
                        development_override["revision"],
                        invalid_reason,
                    )
            decision = decide_scheduled_trigger(
                settings,
                now=now,
                user_chatted_today=(False if development_override is not None else
                    history.user_chatted_on_local_date(
                        now=now,
                        utc_offset_minutes=settings.config.utc_offset_minutes,
                    )),
                already_evaluated_today=(
                    False if development_override is not None else
                    ledger.get_by_idempotency(subject_id, idempotency_key) is not None
                ),
            )
        if invalid_override is not None:
            override_id, override_revision, invalid_reason = invalid_override
            with self._open(write_capability="proactive") as write_connection:
                SQLiteProactiveScheduleOverrideStore(write_connection).finish(
                    override_id,
                    subject_id=subject_id,
                    expected_revision=override_revision,
                    status="consumed",
                    reason=invalid_reason,
                    now=now,
                )
            return {"action": "skip", "reason": invalid_reason}
        if decision.action != ScheduledTriggerAction.CREATE:
            return {"action": decision.action.value, "reason": decision.reason.value}

        device = await XiaozhiRuntimeStateProbe(client).probe()
        # 网络探测可能跨过配置分钟；重新读钟后再次决策，不能用旧时刻补发。
        now = self.clock()
        with self._open(write_capability="proactive") as connection:
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            history = SQLiteProactiveHistoryReader(connection)
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection), clock=lambda: now,
            )
            override_store = SQLiteProactiveScheduleOverrideStore(connection)
            current_override = (
                override_store.get_armed(subject_id)
                if development_override is not None else None
            )
            if development_override is not None and (
                current_override is None
                or current_override["id"] != development_override["id"]
            ):
                return {"action": "skip", "reason": "development_override_unavailable"}
            decision = decide_scheduled_trigger(
                settings,
                now=now,
                user_chatted_today=(False if current_override is not None else
                    history.user_chatted_on_local_date(
                        now=now,
                        utc_offset_minutes=settings.config.utc_offset_minutes,
                    )),
                already_evaluated_today=(
                    False if current_override is not None else
                    ledger.get_by_idempotency(subject_id, decision.idempotency_key) is not None
                ),
            )
            if decision.action != ScheduledTriggerAction.CREATE:
                if current_override is not None:
                    override_store.finish(
                        current_override["id"],
                        subject_id=subject_id,
                        expected_revision=current_override["revision"],
                        status="consumed",
                        reason=f"second_check_{decision.reason.value}",
                        now=now,
                    )
                return {"action": decision.action.value, "reason": decision.reason.value}
            if current_override is not None:
                override_store.finish(
                    current_override["id"],
                    subject_id=subject_id,
                    expected_revision=current_override["revision"],
                    status="consumed",
                    reason="scheduled_attempt_started",
                    now=now,
                )
            topic_seed = (
                SQLiteProactiveTopicStore(connection).choose_for_schedule(
                    subject_id, now=now,
                )
                if settings.topic_enabled else None
            )
            outreach = ledger.create_candidate(
                subject_id=subject_id,
                trigger=OutreachTrigger.EXPLICIT_SCHEDULE,
                trigger_reason_code=(
                    "development_approved_memory_topic"
                    if current_override is not None and topic_seed is not None
                    else "development_fixed_schedule"
                    if current_override is not None
                    else "approved_memory_topic" if topic_seed is not None
                    else "explicit_daily_schedule"
                ),
                content=(
                    topic_seed["prompt_text"] if topic_seed is not None
                    else settings.greeting_text
                ),
                # 调度器在精确分钟内才创建；账本不允许“创建时间晚于计划时间”，
                # 因而当前评估时刻就是本候选的实际计划时刻。
                scheduled_for=now,
                expires_at=decision.scheduled_for + settings.config.maximum_lifetime,
                idempotency_key=(
                    f"development-schedule:{current_override['id']}"
                    if current_override is not None else decision.idempotency_key
                ),
                policy_version=settings.config.policy_version,
                topic_seed_id=topic_seed["id"] if topic_seed is not None else None,
                topic_seed_revision=(
                    topic_seed["revision"] if topic_seed is not None else None
                ),
            )
            if not device.ready:
                blocked = ledger.record_transition(
                    outreach.id,
                    expected_revision=outreach.revision,
                    new_state=OutreachState.BLOCKED,
                    reason_code=device.reason_code or "device_offline",
                    evidence=OutreachEvidence.POLICY_DECISION,
                )
                return outreach_result_json(blocked, replayed=False, device=device)
            runtime = history.read(subject_id, now=now)
            runtime = OutreachPolicyState(
                attempted_at=runtime.attempted_at,
                awaiting_user_response=(
                    False if current_override is not None
                    else runtime.awaiting_user_response
                ),
                user_session_active=device.user_session_active,
                quiet_until=settings.quiet_until,
            )
            result = await ProactiveOutreachDispatcher(
                ledger,
                delivery_queue=XiaozhiProactiveDelivery(client).queue,
                clock=lambda: now,
            ).dispatch(
                outreach.id,
                expected_revision=outreach.revision,
                settings=settings,
                runtime_state=runtime,
            )
            return outreach_result_json(
                result.outreach,
                replayed=False,
                decision=result.decision,
                delivery=result.delivery,
                device=device,
            )

    def _current_absence_decision(self, connection, *, subject_id, now):
        """从唯一当前版本复算缺席决策；版本行从不被运行期修改。"""

        version_store = SQLiteCompanionAbsenceStrategyVersionStore(connection)
        selection = version_store.get_selection(subject_id)
        if selection is None or selection.version_id is None:
            return None
        version = version_store.get_version(selection.version_id, subject_id=subject_id)
        if version is None or not version.replay_gate_passed:
            return None
        draft = AbsenceRoutineDraft(
            candidate_id=version.source_candidate_id,
            expected_minute=version.expected_minute,
            grace_minutes=version.grace_minutes,
            utc_offset_minutes=version.utc_offset_minutes,
            allowed_weekdays=version.allowed_weekdays,
            enabled=True,
            policy_version=version.trigger_policy_version,
        )
        history = SQLiteProactiveHistoryReader(connection)
        observations = SQLiteUserInitiatedInteractionStore(
            connection, commit_changes=False,
        )
        state = AbsenceRoutineState(
            routine_observed_today=observations.observed_on_local_date(
                subject_id, now=now,
                utc_offset_minutes=version.utc_offset_minutes,
            ),
            user_chatted_today=history.user_chatted_on_local_date(
                now=now, utc_offset_minutes=version.utc_offset_minutes,
            ),
            already_evaluated_today=False,
        )
        decision = decide_routine_absence(draft, now=now, state=state)
        if (
            decision.action == AbsenceTriggerAction.CREATE
            and ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection, commit_changes=False),
                clock=lambda: now,
            ).get_by_idempotency(subject_id, decision.idempotency_key) is not None
        ):
            decision = decide_routine_absence(
                draft, now=now,
                state=AbsenceRoutineState(
                    routine_observed_today=state.routine_observed_today,
                    user_chatted_today=state.user_chatted_today,
                    already_evaluated_today=True,
                ),
            )
        return version, selection, decision

    async def proactive_absence_tick(self, client):
        """评估当前激活的缺席策略一次；不补发、不调用模型。"""

        subject_id = "user:self"
        now = self.clock()
        with self._open() as connection:
            current = self._current_absence_decision(
                connection, subject_id=subject_id, now=now,
            )
        if current is None:
            return {"action": "skip", "reason": "absence_strategy_inactive"}
        _, _, decision = current
        if decision.action != AbsenceTriggerAction.CREATE:
            return {"action": decision.action.value, "reason": decision.reason.value}

        device = await XiaozhiRuntimeStateProbe(client).probe()
        now = self.clock()
        with self._open(write_capability="proactive") as connection:
            current = self._current_absence_decision(
                connection, subject_id=subject_id, now=now,
            )
            if current is None:
                return {"action": "skip", "reason": "absence_strategy_changed"}
            version, selection, decision = current
            if decision.action != AbsenceTriggerAction.CREATE:
                return {"action": decision.action.value, "reason": decision.reason.value}
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            topic_seed = (
                SQLiteProactiveTopicStore(connection).choose_for_schedule(
                    subject_id, now=now,
                ) if settings.topic_enabled else None
            )
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection), clock=lambda: now,
            )
            outreach = ledger.create_candidate(
                subject_id=subject_id,
                trigger=OutreachTrigger.HABIT_CANDIDATE,
                trigger_reason_code=(
                    "routine_absence_approved_memory_topic"
                    if topic_seed is not None else "routine_absence_fixed_greeting"
                ),
                content=(topic_seed["prompt_text"] if topic_seed is not None
                         else settings.greeting_text),
                scheduled_for=now,
                expires_at=decision.check_at + settings.config.maximum_lifetime,
                idempotency_key=decision.idempotency_key,
                policy_version=(
                    f"{settings.config.policy_version}+{version.trigger_policy_version}"
                    f"+selection-r{selection.revision}"
                ),
                topic_seed_id=topic_seed["id"] if topic_seed is not None else None,
                topic_seed_revision=topic_seed["revision"] if topic_seed is not None else None,
                strategy_version_id=version.id,
                strategy_selection_revision=selection.revision,
                strategy_evaluated_local_date=decision.local_date.isoformat(),
            )
            if not device.ready:
                blocked = ledger.record_transition(
                    outreach.id, expected_revision=outreach.revision,
                    new_state=OutreachState.BLOCKED,
                    reason_code=device.reason_code or "device_offline",
                    evidence=OutreachEvidence.POLICY_DECISION,
                )
                return outreach_result_json(
                    blocked, replayed=False, device=device,
                )
            history = SQLiteProactiveHistoryReader(connection).read(subject_id, now=now)
            runtime = OutreachPolicyState(
                attempted_at=history.attempted_at,
                awaiting_user_response=history.awaiting_user_response,
                user_session_active=device.user_session_active,
                quiet_until=settings.quiet_until,
            )
            result = await ProactiveOutreachDispatcher(
                ledger,
                delivery_queue=XiaozhiProactiveDelivery(client).queue,
                clock=lambda: now,
            ).dispatch(
                outreach.id, expected_revision=outreach.revision,
                settings=settings, runtime_state=runtime,
            )
            return outreach_result_json(
                result.outreach, replayed=False, decision=result.decision,
                delivery=result.delivery, device=device,
            )

    async def proactive_follow_up_tick(self, client):
        """执行最早一条已到时间的已启用事项；终止后绝不补发。"""

        subject_id = "user:self"
        now = self.clock()
        with self._open() as connection:
            due_store = SQLiteProactiveOutreachStore(
                connection, commit_changes=False,
            )
            due = due_store.next_due_follow_up(subject_id, now=now)
            handled_this_minute = due_store.follow_up_handled_in_current_minute(
                subject_id, now=now,
            )
        if due is None:
            return {
                "action": "skip",
                "reason": (
                    "follow_up_already_handled_this_minute"
                    if handled_this_minute else "no_due_follow_up"
                ),
                "suppress_lower_priority": handled_this_minute,
            }

        # 已过期无需访问设备；账本用系统恢复证据明确结束。
        if now >= due.expires_at:
            with self._open(write_capability="proactive") as connection:
                ledger = ProactiveOutreachLedger(
                    SQLiteProactiveOutreachStore(connection), clock=lambda: now,
                )
                current = ledger.get(due.id)
                if current is None or current.state != OutreachState.CANDIDATE:
                    return {"action": "skip", "reason": "follow_up_already_finished"}
                expired = ledger.record_transition(
                    current.id, expected_revision=current.revision,
                    new_state=OutreachState.EXPIRED,
                    reason_code="follow_up_delivery_window_missed",
                    evidence=OutreachEvidence.SYSTEM_RECOVERY,
                )
                return outreach_result_json(expired, replayed=False)

        device = await XiaozhiRuntimeStateProbe(client).probe()
        now = self.clock()
        with self._open(write_capability="proactive") as connection:
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection), clock=lambda: now,
            )
            current = ledger.get(due.id)
            if current is None or current.state != OutreachState.CANDIDATE:
                return {"action": "skip", "reason": "follow_up_already_finished"}
            if now < current.scheduled_for:
                return {"action": "wait", "reason": "follow_up_not_due"}
            if now >= current.expires_at:
                expired = ledger.record_transition(
                    current.id, expected_revision=current.revision,
                    new_state=OutreachState.EXPIRED,
                    reason_code="follow_up_delivery_window_missed",
                    evidence=OutreachEvidence.SYSTEM_RECOVERY,
                )
                return outreach_result_json(expired, replayed=False)
            source = connection.execute(
                "SELECT f.status,f.revision,m.content,m.valid_from,m.valid_to,"
                "m.retired_at "
                "FROM companion_follow_up_candidates f "
                "JOIN atomic_memories m ON m.id=f.source_memory_id WHERE f.id=?",
                (current.follow_up_candidate_id,),
            ).fetchone()
            source_valid = (
                source is not None
                and source["status"] == "candidate"
                and source["revision"] == current.follow_up_candidate_revision
                and source["retired_at"] is None
                and (
                    source["valid_from"] is None
                    or datetime.fromisoformat(source["valid_from"]) <= now
                )
                and (
                    source["valid_to"] is None
                    or datetime.fromisoformat(source["valid_to"]) > now
                )
            )
            if source_valid:
                expected_digest = connection.execute(
                    "SELECT source_content_sha256 FROM companion_follow_up_candidates "
                    "WHERE id=?", (current.follow_up_candidate_id,),
                ).fetchone()[0]
                source_valid = hashlib.sha256(
                    source["content"].encode("utf-8")
                ).hexdigest() == expected_digest
            if not source_valid:
                cancelled = ledger.record_transition(
                    current.id, expected_revision=current.revision,
                    new_state=OutreachState.CANCELLED,
                    reason_code="follow_up_source_no_longer_current",
                    evidence=OutreachEvidence.POLICY_DECISION,
                )
                return outreach_result_json(cancelled, replayed=False)
            if not device.ready:
                blocked = ledger.record_transition(
                    current.id, expected_revision=current.revision,
                    new_state=OutreachState.BLOCKED,
                    reason_code=device.reason_code or "device_offline",
                    evidence=OutreachEvidence.POLICY_DECISION,
                )
                return outreach_result_json(
                    blocked, replayed=False, device=device,
                )
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            history = SQLiteProactiveHistoryReader(connection).read(subject_id, now=now)
            runtime = OutreachPolicyState(
                attempted_at=history.attempted_at,
                awaiting_user_response=history.awaiting_user_response,
                user_session_active=device.user_session_active,
                quiet_until=settings.quiet_until,
            )
            result = await ProactiveOutreachDispatcher(
                ledger,
                delivery_queue=XiaozhiProactiveDelivery(client).queue,
                clock=lambda: now,
            ).dispatch(
                current.id, expected_revision=current.revision,
                settings=settings, runtime_state=runtime,
            )
            return outreach_result_json(
                result.outreach, replayed=False, decision=result.decision,
                delivery=result.delivery, device=device,
            )

    async def proactive_background_tick(self, client):
        """按明确事项、固定定时、习惯缺席的优先级组合三类来源。"""

        follow_up = await self.proactive_follow_up_tick(client)
        if "outreach_id" in follow_up or follow_up.get("suppress_lower_priority"):
            return {"source": "follow_up", "result": follow_up}

        explicit = await self.proactive_scheduled_tick(client)
        if "outreach_id" in explicit:
            return {"source": "explicit_schedule", "result": explicit}
        absence = await self.proactive_absence_tick(client)
        return {"source": "routine_absence", "result": absence}

    def proactive_history(self, *, limit=20):
        """只读最近投影和最后事件原因，不暴露幂等键或内部连接数据。"""

        return self.proactive.history(limit=limit)

    def list_companion_strategy_candidates(self):
        return self.companion_learning.list_strategy_candidates()

    def list_user_initiated_interactions(self, *, limit=30):
        """只返回时间与来源 ID，不把私人消息正文复制到观察视图。"""

        return self.companion_learning.list_user_initiated_interactions(
            limit=limit,
        )

    def list_companion_routine_candidates(self):
        return self.companion_learning.list_routine_candidates()

    def generate_companion_routine_candidate(self):
        """分析用户主动出现时间；不把候选变成联系规则。"""

        return self.companion_learning.generate_routine_candidate()

    def dismiss_companion_routine_candidate(
        self, candidate_id, *, expected_revision,
    ):
        return self.companion_learning.dismiss_routine_candidate(
            candidate_id, expected_revision=expected_revision,
        )

    def list_companion_absence_strategy_versions(self):
        return self.companion_learning.list_absence_strategy_versions()

    def select_companion_absence_strategy_version(self, request, *, rollback=False):
        return self.companion_learning.select_absence_strategy_version(
            request, rollback=rollback,
        )

    def deactivate_companion_absence_strategy(self, request):
        return self.companion_learning.deactivate_absence_strategy(request)

    def create_companion_absence_strategy_version(self, request):
        """保存回放绑定草案；当前没有激活指针或调度接线。"""

        return self.companion_learning.create_absence_strategy_version(request)

    def generate_companion_strategy_candidate(self):
        """只生成未生效候选；不读取消息正文、不修改 P4 设置。"""

        return self.companion_learning.generate_strategy_candidate()

    def dismiss_companion_strategy_candidate(
        self, candidate_id, *, expected_revision,
    ):
        return self.companion_learning.dismiss_strategy_candidate(
            candidate_id, expected_revision=expected_revision,
        )

    def confirm_proactive_played(self, outreach_id, *, expected_revision):
        """把所有者亲耳观察追加为证据；不从设备状态反推播放成功。"""

        return self.proactive.confirm_played(
            outreach_id, expected_revision=expected_revision,
        )

    @contextmanager
    def _open(self, *, write_capability=None):
        if self.database is None:
            raise MemoryAccessError("memory_not_configured", 503)
        if not self.database.is_file():
            raise MemoryAccessError("memory_database_missing", 503)
        if write_capability == "delete" and not self.allow_delete:
            raise MemoryAccessError("memory_read_only", 403)
        if write_capability == "correction" and not self.allow_correction:
            raise MemoryAccessError("memory_correction_disabled", 403)
        if write_capability == "scenario" and not self.allow_scenario_management:
            raise MemoryAccessError("scenario_management_disabled", 403)
        if write_capability == "persona" and not self.allow_persona_management:
            raise MemoryAccessError("persona_management_disabled", 403)
        connection = None
        try:
            # mode=ro/rw 都不创建文件；不用 open_database 或 build_application，
            # 因为它们会初始化/迁移。连接在请求工作线程内创建并关闭。
            write = write_capability is not None
            mode = "rw" if write else "ro"
            connection = sqlite3.connect(self.database.as_uri() + "?mode=" + mode, uri=True, timeout=2)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            if not write:
                connection.execute("PRAGMA query_only = ON")
            # 删除先持有写锁，再检查快照和删除，避免核对后又被别的进程改动。
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise MemoryAccessError("memory_schema_unsupported")
            yield connection
        except sqlite3.OperationalError as error:
            primary_code = getattr(error, "sqlite_errorcode", 0) & 0xFF
            code = "memory_busy" if primary_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} else "memory_database_unavailable"
            raise MemoryAccessError(code, 503) from None
        except (sqlite3.DatabaseError, ValueError, KeyError, TypeError):
            raise MemoryAccessError("memory_database_invalid", 503) from None
        finally:
            if connection is not None:
                # 未提交的读事务、失败写事务均在关闭时回滚；成功删除沿用原用例提交。
                connection.close()

    @staticmethod
    def _service(connection, *, commit_changes=True):
        return MemoryManagementService(
            memory_store=SQLiteMemoryStore(connection, commit_changes=commit_changes),
            conversation_store=SQLiteConversationStore(connection, commit_changes=commit_changes),
        )

    def list_page(self, *, query="", state="active", limit=25, offset=0):
        with self._open() as connection:
            total, items = SQLiteMemoryStore(connection).list_page(query=query, state=state, limit=limit, offset=offset)
            summaries = []
            for item in items:
                row = memory_json(item)
                row["content"] = item.content[:240]
                row["truncated"] = len(item.content) > 240
                summaries.append(row)
            return {"items": summaries, "total": total, "limit": limit, "offset": offset}

    @staticmethod
    def _local_day_window(local_date, utc_offset_minutes):
        """把浏览器自然日转换成半开 UTC 区间，供多个只读视图共用。"""
        try:
            day = datetime.strptime(local_date, "%Y-%m-%d").date()
            offset = timezone(timedelta(minutes=utc_offset_minutes))
            start = datetime.combine(day, datetime.min.time(), tzinfo=offset).astimezone(UTC)
        except (TypeError, ValueError, OverflowError):
            raise MemoryAccessError("invalid_daily_review_window", 400) from None
        return start, start + timedelta(days=1)

    def daily_review(self, *, local_date, utc_offset_minutes):
        """返回某个本地自然日写入的 L1；读取不触发整理、提取或迁移。"""
        start, end = self._local_day_window(local_date, utc_offset_minutes)
        with self._open() as connection:
            store = SQLiteMemoryStore(connection)
            items = store.list_recorded_between(start, end)
            summaries = []
            activity_counts = {"added": 0, "corrected": 0, "changed": 0, "deleted": 0}
            for item in items:
                row = memory_json(item)
                row["content"] = item.content[:240]
                row["truncated"] = len(item.content) > 240
                source_types = {
                    evidence.source_type.value for evidence in store.list_evidence(item.id)
                }
                # 当前数据模型只有“纠错”具备专门证据类型；事实变化则由新
                # L1 的 valid_from 表达。删除后 L1 已不存在，因此这里不伪造
                # 一条无法从现有数据库可靠还原的“删除活动”。
                if "user_corrected" in source_types:
                    activity = "corrected"
                elif item.valid_from is not None:
                    activity = "changed"
                else:
                    activity = "added"
                row["activity"] = activity
                activity_counts[activity] += 1
                summaries.append(row)
            deletion_total = connection.execute(
                "SELECT count(*) FROM l1_deletion_events "
                "WHERE deleted_at >= ? AND deleted_at < ?",
                (start.isoformat(), end.isoformat()),
            ).fetchone()[0]
            deletion_rows = connection.execute(
                "SELECT id,memory_id,subject_id,deleted_at FROM l1_deletion_events "
                "WHERE deleted_at >= ? AND deleted_at < ? "
                "ORDER BY deleted_at DESC,id DESC LIMIT 100",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
            activity_counts["deleted"] = deletion_total
            message_rows = connection.execute(
                "SELECT role,count(*) AS count FROM conversation_messages "
                "WHERE created_at >= ? AND created_at < ? GROUP BY role",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
            message_counts = {"user": 0, "assistant": 0, "total": 0, "unlinked_user": 0}
            for row in message_rows:
                message_counts[row["role"]] = row["count"]
                message_counts["total"] += row["count"]
            message_counts["unlinked_user"] = connection.execute(
                "SELECT count(*) FROM conversation_messages m "
                "WHERE m.role='user' AND m.created_at >= ? AND m.created_at < ? "
                "AND NOT EXISTS (SELECT 1 FROM memory_evidence e WHERE e.source_message_id=m.id)",
                (start.isoformat(), end.isoformat()),
            ).fetchone()[0]
            confirmed_missed = connection.execute(
                "SELECT count(*) FROM memory_quality_events "
                "WHERE event_kind='owner_confirmed_missed_extraction' "
                "AND occurred_at >= ? AND occurred_at < ?",
                (start.isoformat(), end.isoformat()),
            ).fetchone()[0]
            return {"local_date":local_date,"utc_offset_minutes":utc_offset_minutes,
                    "items":summaries,"total":len(summaries),"limited":len(summaries)==100,
                    "activity_counts":activity_counts,
                    "message_counts":message_counts,
                    "quality_counts":{"owner_confirmed_missed_extraction":confirmed_missed},
                    "deletions":[dict(row) for row in deletion_rows],
                    "deletions_limited":deletion_total > len(deletion_rows)}

    def consolidation_status(self):
        """只读呈现自动整理门槛和账本；不会借查询触发模型或迁移。"""

        with self._open() as connection:
            now = datetime.now(UTC)
            store = SQLiteConsolidationRunStore(connection, commit_changes=False)
            statuses = ConsolidationStatusService(
                run_store=store,
                l1_reader=SQLiteL1ConsolidationSourceReader(connection),
                l2_reader=SQLiteL2ConsolidationSourceReader(connection),
                l1_config=ConsolidationTriggerConfig(),
                l2_config=L3_TRIGGER_CONFIG,
            ).inspect(str(CURRENT_USER_SUBJECT_ID), now=now)
            return {
                "subject_id": str(CURRENT_USER_SUBJECT_ID),
                "observed_at": now.isoformat(),
                "background_enabled": self.consolidation_background_enabled,
                "stages": [self._consolidation_status_json(item) for item in statuses],
            }

    @staticmethod
    def _consolidation_status_json(item):
        cursor = item.cursor
        latest = item.latest_run
        return {
            "stage": item.stage.value,
            "pending_new_source_count": item.pending_new_source_count,
            "trigger_action": item.trigger_action,
            "trigger_reason": item.trigger_reason,
            "minimum_new_sources": item.minimum_new_sources,
            "maximum_sources_per_run": item.maximum_sources_per_run,
            "cooldown_seconds": item.cooldown_seconds,
            "daily_model_call_budget": item.daily_model_call_budget,
            "model_calls_today": item.model_calls_today,
            "remaining_model_calls_today": max(
                0, item.daily_model_call_budget - item.model_calls_today,
            ),
            "cursor": None if cursor is None else {
                "recorded_at": cursor.recorded_at.isoformat(),
                "source_id": cursor.source_id,
            },
            "latest_run": None if latest is None else {
                "id": latest.id,
                "trigger": latest.trigger.value,
                "status": latest.status.value,
                "started_at": latest.started_at.isoformat(),
                "finished_at": (
                    latest.finished_at.isoformat() if latest.finished_at else None
                ),
                "outcome_code": latest.outcome_code,
                "source_count": latest.source_count,
                "model_call_count": latest.model_call_count,
                "risk_reviewer_version": latest.risk_reviewer_version,
            },
        }

    def list_sources(self, *, query="", role="all", link_state="all", limit=25, offset=0,
                     local_date=None, utc_offset_minutes=None):
        """分页读取 L0，并明确它是否已经成为任意 L1 的证据。"""

        if (local_date is None) != (utc_offset_minutes is None):
            raise MemoryAccessError("invalid_daily_review_window", 400)
        day_window = (
            self._local_day_window(local_date, utc_offset_minutes)
            if local_date is not None else None
        )
        with self._open() as connection:
            clauses, parameters = [], []
            if query:
                clauses.append("instr(lower(m.content), lower(?)) > 0")
                parameters.append(query)
            if role != "all":
                clauses.append("m.role = ?")
                parameters.append(role)
            linked = "EXISTS (SELECT 1 FROM memory_evidence e WHERE e.source_message_id = m.id)"
            if link_state == "linked":
                clauses.append(linked)
            elif link_state == "unlinked":
                clauses.append("NOT " + linked)
            if day_window is not None:
                start, end = day_window
                clauses.extend(("m.created_at >= ?", "m.created_at < ?"))
                parameters.extend((start.isoformat(), end.isoformat()))
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            total = connection.execute(
                "SELECT count(*) FROM conversation_messages m" + where,
                parameters,
            ).fetchone()[0]
            rows = connection.execute(
                """
                SELECT m.id, m.role, m.content, m.created_at,
                       count(DISTINCT e.memory_id) AS linked_memory_count
                FROM conversation_messages m
                LEFT JOIN memory_evidence e ON e.source_message_id = m.id
                """ + where + """
                GROUP BY m.id, m.role, m.content, m.created_at
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            ).fetchall()
            items = [{
                "id": row["id"],
                "role": row["role"],
                "content": row["content"][:240],
                "truncated": len(row["content"]) > 240,
                "created_at": row["created_at"],
                "linked_memory_count": row["linked_memory_count"],
            } for row in rows]
            return {"items": items, "total": total, "limit": limit, "offset": offset}

    def get_source(self, source_id):
        """读取一条 L0 原文及其派生 L1；未关联也必须作为真实状态返回。"""

        with self._open() as connection:
            return self._source_json(connection, source_id)

    @staticmethod
    def _source_json(connection, source_id):
        source = connection.execute(
            "SELECT id, role, content, created_at FROM conversation_messages WHERE id = ?",
            (source_id,),
        ).fetchone()
        if source is None:
            raise MemoryAccessError("source_message_not_found", 404)
        rows = connection.execute(
            """
            SELECT a.*, e.source_type, e.linked_at
            FROM memory_evidence e
            JOIN atomic_memories a ON a.id = e.memory_id
            WHERE e.source_message_id = ?
            ORDER BY e.linked_at DESC, a.id DESC
            """,
            (source_id,),
        ).fetchall()
        derived = []
        for row in rows:
            item = {
                "id": row["id"], "subject_id": row["subject_id"], "content": row["content"],
                **{key: row[key] for key in ("recorded_at", "valid_from", "valid_to", "retired_at")},
                "superseded_by_id": row["superseded_by_id"],
                "state": "retired" if row["retired_at"] else "active",
            }
            item.update(source_type=row["source_type"], linked_at=row["linked_at"])
            derived.append(item)
        data = {
            "id": source["id"], "role": source["role"], "content": source["content"],
            "created_at": source["created_at"], "derived_memories": derived,
        }
        return {**data, "revision": revision(data)}

    def promote_source(self, source_id, content, expected_revision):
        """把已核对的用户 L0 补成 L1；同内容当前事实只增加证据。"""

        with self._open(write_capability="correction") as connection:
            current = self._source_json(connection, source_id)
            if not secrets.compare_digest(current["revision"], expected_revision):
                raise MemoryAccessError("source_message_changed")
            occurred_at = self.clock()
            try:
                result = self._service(
                    connection, commit_changes=False,
                ).promote_source_to_memory(
                    MessageId(source_id), content, occurred_at=occurred_at,
                )
            except LookupError:
                raise MemoryAccessError("source_message_not_found", 404) from None
            except ValueError as error:
                code = str(error)
                status = 400 if code.startswith("promoted_content_") else 409
                raise MemoryAccessError(code, status) from None
            except RuntimeError as error:
                if str(error) == "source_promotion_race":
                    raise MemoryAccessError("source_message_changed") from None
                raise
            # 这是所有者显式确认的“漏记”质量信号，与 L1 写入同事务。
            # 只存身份、解决方式和时间，避免再复制一份个人正文。
            connection.execute(
                "INSERT INTO memory_quality_events "
                "(id,event_kind,source_message_id,memory_id,resolution,occurred_at) "
                "VALUES (lower(hex(randomblob(16))),?,?,?,?,?)",
                (
                    "owner_confirmed_missed_extraction",
                    str(result.source_message.id),
                    str(result.memory.id),
                    "created" if result.created_new_memory else "evidence_added",
                    occurred_at.isoformat(),
                ),
            )
            connection.commit()
            return {
                "promoted": True,
                "memory_id": str(result.memory.id),
                "source_message_id": str(result.source_message.id),
                "created_new_memory": result.created_new_memory,
            }

    def get(self, memory_id):
        with self._open() as connection:
            details = self._service(connection).get_memory(MemoryId(memory_id))
            if details is None:
                raise MemoryAccessError("memory_not_found", 404)
            data = details_json(details)
            return {**data, "revision": revision(data)}

    def delete(self, memory_id, expected_revision):
        with self._open(write_capability="delete") as connection:
            service = self._service(connection, commit_changes=False)
            details = service.get_memory(MemoryId(memory_id))
            if details is None:
                raise MemoryAccessError("memory_not_found", 404)
            if not secrets.compare_digest(revision(details_json(details)), expected_revision):
                raise MemoryAccessError("memory_changed")
            # 复用已经测试过的语义：删除 L1 + 来源关联，保留 L0 原始对话。
            # 外键还会解除其他记忆指向此条的取代链接，不冒充完整隐私擦除。
            if not service.delete_memory(MemoryId(memory_id)):
                raise MemoryAccessError("memory_not_found", 404)
            connection.commit()
            return {"deleted": True, "id": memory_id, "l0_preserved": True}

    @staticmethod
    def _clear_snapshot(connection):
        """生成不含正文的清空预检快照，并用身份列表防止过期页面误删。"""

        rows = connection.execute(
            "SELECT id, retired_at FROM atomic_memories ORDER BY id"
        ).fetchall()
        l1_identities = [
            {"id": row["id"], "retired_at": row["retired_at"]}
            for row in rows
        ]
        snapshot = {
            # 清空确认期间，即使只是某条 L1 的生命周期发生变化，也必须使
            # 旧预检失效，不能让页面拿着过期影响范围继续执行批量删除。
            "l1_identities": l1_identities,
            "l2_current": connection.execute(
                "SELECT count(*) FROM scenario_memories "
                "WHERE status IN ('candidate','active')"
            ).fetchone()[0],
            "l3_current": connection.execute(
                "SELECT count(*) FROM persona_memories "
                "WHERE status IN ('candidate','active')"
            ).fetchone()[0],
            "l0_preserved": connection.execute(
                "SELECT count(*) FROM conversation_messages"
            ).fetchone()[0],
        }
        return {
            "l1_total": len(l1_identities),
            "l1_active": sum(row["retired_at"] is None for row in rows),
            "l1_retired": sum(row["retired_at"] is not None for row in rows),
            "affected_l2_current": snapshot["l2_current"],
            "affected_l3_current": snapshot["l3_current"],
            "l0_preserved": snapshot["l0_preserved"],
            "revision": revision(snapshot),
        }

    def clear_preview(self):
        with self._open() as connection:
            return self._clear_snapshot(connection)

    def clear_memories(self, expected_revision):
        """原子删除全部 L1；L0 与审计保留，关联 L2/L3 由触发器失效。"""

        with self._open(write_capability="delete") as connection:
            before = self._clear_snapshot(connection)
            if not secrets.compare_digest(before["revision"], expected_revision):
                raise MemoryAccessError("memory_clear_changed", 409)
            deleted = connection.execute("DELETE FROM atomic_memories").rowcount
            connection.commit()
            return {
                "cleared": True,
                "deleted_l1": deleted,
                "l0_preserved": before["l0_preserved"],
                "affected_l2_current": before["affected_l2_current"],
                "affected_l3_current": before["affected_l3_current"],
            }

    def correct(self, memory_id, corrected_content, expected_revision):
        """在一个 SQLite 事务中保存纠正来源、新事实和取代关系。"""

        with self._open(write_capability="correction") as connection:
            service = self._service(connection, commit_changes=False)
            old_details = service.get_memory(MemoryId(memory_id))
            if old_details is None:
                raise MemoryAccessError("memory_not_found", 404)
            if not secrets.compare_digest(
                revision(details_json(old_details)), expected_revision
            ):
                raise MemoryAccessError("memory_changed")
            try:
                result = service.correct_memory(
                    MemoryId(memory_id), corrected_content
                )
            except LookupError:
                raise MemoryAccessError("memory_not_found", 404) from None
            except ValueError as error:
                code = str(error)
                status = 400 if code.startswith("corrected_content_") else 409
                raise MemoryAccessError(code, status) from None
            except RuntimeError as error:
                if str(error) == "memory_correction_race":
                    raise MemoryAccessError("memory_changed") from None
                raise
            connection.commit()
            return {
                "corrected": True,
                "old_memory_id": str(result.old_memory.id),
                "new_memory_id": str(result.new_memory.id),
                "source_message_id": str(result.source_message.id),
                "source_type": result.evidence.source_type.value,
                "old_l0_preserved": True,
            }

    def record_change(self, memory_id, new_content, effective_at, expected_revision):
        """在同一事务中记录事实变化及其双时间语义。"""

        with self._open(write_capability="correction") as connection:
            service = self._service(connection, commit_changes=False)
            old_details = service.get_memory(MemoryId(memory_id))
            if old_details is None:
                raise MemoryAccessError("memory_not_found", 404)
            if not secrets.compare_digest(
                revision(details_json(old_details)), expected_revision
            ):
                raise MemoryAccessError("memory_changed")
            try:
                result = service.record_memory_change(
                    MemoryId(memory_id),
                    new_content,
                    effective_at=datetime.fromisoformat(effective_at),
                )
            except LookupError:
                raise MemoryAccessError("memory_not_found", 404) from None
            except ValueError as error:
                code = str(error)
                status = 400 if (
                    code.startswith("changed_content_")
                    or code.startswith("effective_at_")
                    or code == "occurred_at_timezone_required"
                ) else 409
                raise MemoryAccessError(code, status) from None
            except RuntimeError as error:
                if str(error) == "memory_change_race":
                    raise MemoryAccessError("memory_changed") from None
                raise
            connection.commit()
            return {
                "changed": True,
                "old_memory_id": str(result.old_memory.id),
                "new_memory_id": str(result.new_memory.id),
                "source_message_id": str(result.source_message.id),
                "source_type": result.evidence.source_type.value,
                "effective_at": result.effective_at.isoformat(),
                "old_l0_preserved": True,
            }

    def list_scenarios(self, *, state="all", limit=25, offset=0):
        return self.scenarios.list(state=state, limit=limit, offset=offset)

    def list_scenario_source_inbox(self):
        return self.scenarios.list_source_inbox()

    def get_scenario(self, scenario_id):
        return self.scenarios.get(scenario_id)

    def preview_scenario(self, *, source_memory_ids):
        return self.scenarios.preview(source_memory_ids=source_memory_ids)

    def create_scenario(self, *, title, summary, source_memory_ids, creation_kind="manual",
                        valid_from=None, valid_to=None):
        return self.scenarios.create(
            title=title,
            summary=summary,
            source_memory_ids=source_memory_ids,
            creation_kind=creation_kind,
            valid_from=valid_from,
            valid_to=valid_to,
        )

    def review_scenario(self, scenario_id, *, decision, expected_revision):
        return self.scenarios.review(
            scenario_id, decision=decision, expected_revision=expected_revision,
        )

    def end_scenario(self, scenario_id, *, expected_revision):
        return self.scenarios.end(scenario_id, expected_revision=expected_revision)

    def list_personas(self, *, state="all", limit=25, offset=0):
        return self.personas.list(state=state, limit=limit, offset=offset)

    def get_persona_profile(self):
        return self.personas.profile()

    def list_persona_source_options(self):
        return self.personas.list_source_options()

    def get_persona(self, persona_id):
        return self.personas.get(persona_id)

    def create_persona(self, *, kind, basis, label, statement, sources,
                       valid_from=None, valid_to=None, creation_kind="manual",
                       replaces=()):
        return self.personas.create(
            kind=kind,
            basis=basis,
            label=label,
            statement=statement,
            sources=sources,
            valid_from=valid_from,
            valid_to=valid_to,
            creation_kind=creation_kind,
            replaces=replaces,
        )

    def preview_persona(self, *, basis, sources):
        return self.personas.preview(basis=basis, sources=sources)

    def preview_persona_consolidation(self, *, basis, sources):
        return self.personas.preview_consolidation(basis=basis, sources=sources)

    def review_persona(self, persona_id, *, decision, expected_revision):
        return self.personas.review(
            persona_id, decision=decision, expected_revision=expected_revision,
        )
