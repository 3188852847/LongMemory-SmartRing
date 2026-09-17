"""主动交流的运行期执行边界。

本模块只负责把已保存策略、设备实时状态和不可变外联账本组合成一次执行结果。
配置编辑与候选学习分别属于其他协作者，避免诊断投递反向依赖记忆 CRUD。
"""

import hashlib
from datetime import datetime, timedelta, timezone

from longmemory.adapters.device_control import (
    XiaozhiProactiveDelivery,
    XiaozhiRuntimeStateProbe,
)
from longmemory.adapters.storage.sqlite_proactive_outreach_store import (
    SQLiteProactiveOutreachStore,
)
from longmemory.adapters.storage.sqlite_companion_absence_strategy_store import (
    SQLiteCompanionAbsenceStrategyVersionStore,
)
from longmemory.adapters.storage.sqlite_user_initiated_interaction_store import (
    SQLiteUserInitiatedInteractionStore,
)
from longmemory.adapters.storage.sqlite_proactive_policy_store import (
    SQLiteProactivePolicyStore,
)
from longmemory.adapters.storage.sqlite_proactive_schedule_override_store import (
    SQLiteProactiveScheduleOverrideStore,
)
from longmemory.adapters.storage.sqlite_proactive_topic_store import (
    SQLiteProactiveTopicStore,
)
from longmemory.adapters.storage.sqlite_proactive_runtime_state import (
    SQLiteProactiveHistoryReader,
)
from longmemory.application.proactive import (
    ProactiveOutreachDispatcher,
    ProactiveOutreachLedger,
)
from longmemory.core.proactive import (
    OutreachEvidence,
    OutreachPolicyState,
    OutreachState,
    OutreachTrigger,
    ScheduledTriggerAction,
    decide_scheduled_trigger,
    scheduled_trigger_slot,
)
from longmemory.core.companion import (
    AbsenceRoutineDraft,
    AbsenceRoutineState,
    AbsenceTriggerAction,
    decide_routine_absence,
)

from .errors import MemoryAccessError
from .proactive_presenters import outreach_result_json


class ProactiveRuntimeBackend:
    """执行主动交流动作；所有持久化仍经过显式能力受限的数据库入口。"""

    def __init__(self, *, open_database, clock, greeting_composer=None):
        self._open_database = open_database
        self._clock = clock
        self._greeting_composer = greeting_composer

    async def _compose_topic(self, settings, topic_seed):
        """模型只看到获批短句；无能力、未开启或异常时原样返回。"""

        if (
            topic_seed is None
            or not settings.dynamic_greeting_enabled
            or self._greeting_composer is None
        ):
            return (
                topic_seed["prompt_text"] if topic_seed is not None else settings.greeting_text,
                "approved_memory_topic" if topic_seed is not None else "fixed_greeting",
            )
        result = await self._greeting_composer.compose(topic_seed["prompt_text"])
        return result.text, (
            "model_generated_approved_topic"
            if result.outcome == "model_generated"
            else "model_fallback_approved_topic"
        )

    async def manual_test(self, request, client):
        """执行一次用户明确发起的短文本测试；同 request_id 绝不重播。"""

        subject_id = "user:self"
        idempotency_key = "manual-console:" + request.request_id
        with self._open_database() as connection:
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection, commit_changes=False),
                clock=self._clock,
            )
            existing = ledger.get_by_idempotency(subject_id, idempotency_key)
            if existing is not None:
                return outreach_result_json(existing, replayed=True)
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            if settings.revision != request.expected_policy_revision:
                raise MemoryAccessError("proactive_settings_conflict", 409)

        device = await XiaozhiRuntimeStateProbe(client).probe()
        now = self._clock()
        with self._open_database(write_capability="proactive") as connection:
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection), clock=lambda: now,
            )
            existing = ledger.get_by_idempotency(subject_id, idempotency_key)
            if existing is not None:
                return outreach_result_json(
                    existing, replayed=True, device=device,
                )
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            if settings.revision != request.expected_policy_revision:
                raise MemoryAccessError("proactive_settings_conflict", 409)
            runtime = SQLiteProactiveHistoryReader(connection).read(
                subject_id, now=now,
            )
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
                raise MemoryAccessError(
                    "proactive_dispatch_conflict", 409,
                ) from None
            return outreach_result_json(
                result.outreach,
                replayed=False,
                decision=result.decision,
                delivery=result.delivery,
                device=device,
            )


    async def follow_up_tick(self, client):
        """执行最早一条已到时间的已启用事项；终止后绝不补发。"""

        subject_id = "user:self"
        now = self._clock()
        with self._open_database() as connection:
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
            with self._open_database(write_capability="proactive") as connection:
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
        now = self._clock()
        with self._open_database(write_capability="proactive") as connection:
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

    async def background_tick(self, client):
        """按明确事项、固定定时、习惯缺席的优先级组合三类来源。"""

        follow_up = await self.follow_up_tick(client)
        if "outreach_id" in follow_up or follow_up.get("suppress_lower_priority"):
            return {"source": "follow_up", "result": follow_up}

        explicit = await self.scheduled_tick(client)
        if "outreach_id" in explicit:
            return {"source": "explicit_schedule", "result": explicit}
        absence = await self.absence_tick(client)
        return {"source": "routine_absence", "result": absence}


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

    async def absence_tick(self, client):
        """评估当前激活的缺席策略一次；不补发、不调用模型。"""

        subject_id = "user:self"
        now = self._clock()
        with self._open_database() as connection:
            current = self._current_absence_decision(
                connection, subject_id=subject_id, now=now,
            )
            prepared_settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            prepared_topic = (
                SQLiteProactiveTopicStore(connection).choose_for_schedule(
                    subject_id, now=now,
                ) if prepared_settings.topic_enabled else None
            )
        if current is None:
            return {"action": "skip", "reason": "absence_strategy_inactive"}
        _, _, decision = current
        if decision.action != AbsenceTriggerAction.CREATE:
            return {"action": decision.action.value, "reason": decision.reason.value}

        device = await XiaozhiRuntimeStateProbe(client).probe()
        prepared_content, prepared_reason = await self._compose_topic(
            prepared_settings, prepared_topic,
        ) if device.ready else (None, None)
        now = self._clock()
        with self._open_database(write_capability="proactive") as connection:
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
            topic_matches = (
                prepared_topic is not None and topic_seed is not None
                and prepared_topic["id"] == topic_seed["id"]
                and prepared_topic["revision"] == topic_seed["revision"]
                and prepared_settings.revision == settings.revision
            )
            content = (
                prepared_content if topic_matches and prepared_content is not None
                else topic_seed["prompt_text"] if topic_seed is not None
                else settings.greeting_text
            )
            content_reason = (
                prepared_reason if topic_matches and prepared_reason is not None
                else "approved_memory_topic" if topic_seed is not None
                else "fixed_greeting"
            )
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection), clock=lambda: now,
            )
            outreach = ledger.create_candidate(
                subject_id=subject_id,
                trigger=OutreachTrigger.HABIT_CANDIDATE,
                trigger_reason_code=(
                    "routine_absence_" + content_reason
                ),
                content=content,
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

    async def scheduled_tick(self, client):
        """评估当前当地分钟一次；动态文案失败即回退且不自动重试。"""

        subject_id = "user:self"
        now = self._clock()
        development_override = None
        invalid_override = None
        prepared_topic = None
        prepared_settings = None
        with self._open_database() as connection:
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            prepared_settings = settings
            history = SQLiteProactiveHistoryReader(connection)
            offset = timezone(timedelta(minutes=settings.config.utc_offset_minutes))
            local_now = now.astimezone(offset)
            local_day = local_now.date()
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
                elif settings.automatic_interval_seconds != 24 * 60 * 60:
                    invalid_reason = "interval_mode_does_not_use_override"
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
            slot = scheduled_trigger_slot(settings, now=now)
            decision = decide_scheduled_trigger(
                settings,
                now=now,
                user_chatted_today=(
                    False if development_override is not None
                    else history.user_chatted_on_local_date(
                        now=now,
                        utc_offset_minutes=settings.config.utc_offset_minutes,
                    )
                ),
                already_evaluated_today=(
                    False if development_override is not None
                    else bool(
                        slot and ledger.get_by_idempotency(
                            subject_id, slot[1],
                        ) is not None
                    )
                ),
            )
            prepared_topic = (
                SQLiteProactiveTopicStore(connection).choose_for_schedule(
                    subject_id, now=now,
                ) if settings.topic_enabled else None
            )
        if invalid_override is not None:
            override_id, override_revision, invalid_reason = invalid_override
            with self._open_database(
                write_capability="proactive",
            ) as write_connection:
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
            return {
                "action": decision.action.value,
                "reason": decision.reason.value,
            }

        device = await XiaozhiRuntimeStateProbe(client).probe()
        prepared_content, prepared_reason = await self._compose_topic(
            prepared_settings, prepared_topic,
        ) if device.ready else (None, None)
        # 网络探测可能跨过配置分钟；重新读钟后再次决策，不能用旧时刻补发。
        now = self._clock()
        with self._open_database(write_capability="proactive") as connection:
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
                return {
                    "action": "skip",
                    "reason": "development_override_unavailable",
                }
            slot = scheduled_trigger_slot(settings, now=now)
            decision = decide_scheduled_trigger(
                settings,
                now=now,
                user_chatted_today=(
                    False if current_override is not None
                    else history.user_chatted_on_local_date(
                        now=now,
                        utc_offset_minutes=settings.config.utc_offset_minutes,
                    )
                ),
                already_evaluated_today=(
                    False if current_override is not None
                    else bool(
                        slot and ledger.get_by_idempotency(
                            subject_id, slot[1],
                        ) is not None
                    )
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
                return {
                    "action": decision.action.value,
                    "reason": decision.reason.value,
                }
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
            topic_matches = (
                prepared_topic is not None and topic_seed is not None
                and prepared_topic["id"] == topic_seed["id"]
                and prepared_topic["revision"] == topic_seed["revision"]
                and prepared_settings.revision == settings.revision
            )
            content = (
                prepared_content if topic_matches and prepared_content is not None
                else topic_seed["prompt_text"] if topic_seed is not None
                else settings.greeting_text
            )
            content_reason = (
                prepared_reason if topic_matches and prepared_reason is not None
                else "approved_memory_topic" if topic_seed is not None
                else "fixed_greeting"
            )
            outreach = ledger.create_candidate(
                subject_id=subject_id,
                trigger=OutreachTrigger.EXPLICIT_SCHEDULE,
                trigger_reason_code=(
                    "development_" + content_reason
                    if current_override is not None
                    else content_reason
                    if topic_seed is not None
                    else "explicit_daily_schedule"
                ),
                content=content,
                scheduled_for=now,
                expires_at=(
                    decision.scheduled_for + settings.config.maximum_lifetime
                ),
                idempotency_key=(
                    f"development-schedule:{current_override['id']}"
                    if current_override is not None else decision.idempotency_key
                ),
                policy_version=settings.config.policy_version,
                topic_seed_id=(
                    topic_seed["id"] if topic_seed is not None else None
                ),
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
                return outreach_result_json(
                    blocked, replayed=False, device=device,
                )
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
