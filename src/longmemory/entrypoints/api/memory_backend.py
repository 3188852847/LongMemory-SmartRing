"""网页记忆管理的装配边界：只打开显式指定的已有数据库，不运行建库/迁移。"""

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from longmemory.adapters.storage.sqlite_conversation_store import SQLiteConversationStore
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.adapters.storage.sqlite_scenario_store import SQLiteScenarioStore
from longmemory.adapters.storage.sqlite_persona_store import SQLitePersonaStore
from longmemory.adapters.storage.sqlite_consolidation_run_store import (
    SQLiteConsolidationRunStore,
)
from longmemory.adapters.storage.sqlite_proactive_policy_store import SQLiteProactivePolicyStore
from longmemory.adapters.storage.sqlite_proactive_outreach_store import SQLiteProactiveOutreachStore
from longmemory.adapters.storage.sqlite_interaction_outcome_store import (
    SQLiteInteractionOutcomeStore,
)
from longmemory.adapters.storage.sqlite_companion_feedback_store import (
    SQLiteCompanionFeedbackStore,
)
from longmemory.adapters.storage.sqlite_companion_strategy_store import (
    SQLiteCompanionStrategyCandidateStore,
)
from longmemory.adapters.storage.sqlite_companion_routine_store import (
    SQLiteCompanionRoutineCandidateStore,
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
from longmemory.application.companion_strategy import (
    CompanionStrategyCandidateService,
)
from longmemory.application.companion_routine import (
    CompanionRoutineCandidateService,
)
from longmemory.core.proactive import (
    OutreachEvidence,
    OutreachPolicyConfig,
    OutreachPolicyState,
    OutreachState,
    OutreachTrigger,
    ProactivePolicySettings,
    ProactiveTopicSeed,
    ScheduledTriggerAction,
    TopicSeedStatus,
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
from longmemory.application.scenario_management.service import ScenarioManagementService
from longmemory.application.scenario_management.proposal_service import ScenarioProposalService
from longmemory.application.persona_management.service import PersonaManagementService
from longmemory.application.persona_management.proposal_service import PersonaProposalService
from longmemory.application.persona_management.consolidation_service import PersonaConsolidationService
from longmemory.application.persona_management.profile import build_persona_profile
from longmemory.core.common.identifiers import MemoryId, PersonaId, ScenarioId
from longmemory.core.memory.l1_atomic.models import CURRENT_USER_SUBJECT_ID
from longmemory.core.memory.l2_scenario.models import ScenarioReviewDecision
from longmemory.core.memory.l2_scenario.proposals import (
    ScenarioProposalError,
    ScenarioProposalInput,
)
from longmemory.adapters.llm.scenario_candidate import SCENARIO_PROMPT_VERSION
from longmemory.adapters.llm.persona_candidate import (
    PERSONA_CONSOLIDATION_PROMPT_VERSION,
    PERSONA_PROMPT_VERSION,
)
from longmemory.core.memory.l3_persona.models import (
    PersonaBasis,
    PersonaKind,
    PersonaReviewDecision,
    PersonaSourceLayer,
)
from longmemory.core.memory.l3_persona.proposals import (
    PersonaProposalError,
    PersonaProposalEvidence,
    PersonaProposalInput,
)
from longmemory.core.memory.consolidation.trigger_policy import ConsolidationTriggerConfig
from longmemory.infrastructure.database.schema import SCHEMA_VERSION


class MemoryAccessError(Exception):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


def memory_json(memory):
    return {
        "id": str(memory.id), "subject_id": str(memory.subject_id), "content": memory.content,
        **{key: getattr(memory, key).isoformat() if getattr(memory, key) else None
           for key in ("recorded_at", "valid_from", "valid_to", "retired_at")},
        "superseded_by_id": str(memory.superseded_by_id) if memory.superseded_by_id else None,
        "state": "retired" if memory.retired_at else "active",
    }


def details_json(details):
    result = memory_json(details.memory)
    result["sources"] = [{
        "source_message_id": str(source.evidence.source_message_id),
        "source_type": source.evidence.source_type.value,
        "linked_at": source.evidence.linked_at.isoformat(),
        "message": None if source.source_message is None else {
            "role": source.source_message.role.value,
            "content": source.source_message.content,
            "created_at": source.source_message.created_at.isoformat(),
        },
    } for source in details.sources]
    return result


def revision(data):
    """用于删除前再次核对内容及来源，不是鉴权令牌，不替代 CSRF 校验。"""
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


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

    def info(self):
        return {"configured": self.database is not None,
                "database": str(self.database) if self.database else None,
                "allow_delete": self.allow_delete and self.database is not None,
                "allow_correction": self.allow_correction and self.database is not None,
                # 当前两个操作共用同一个显式启动权限，但对前端公开独立能力名，
                # 以后拆分权限时不需要再改变页面语义。
                "allow_change": self.allow_correction and self.database is not None,
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

    @staticmethod
    def _proactive_json(settings):
        config = settings.config
        return {
            "subject_id": settings.subject_id,
            "enabled": config.enabled,
            "utc_offset_minutes": config.utc_offset_minutes,
            "allowed_weekdays": list(config.allowed_weekdays),
            "allowed_start_minute": config.allowed_start_minute,
            "allowed_end_minute": config.allowed_end_minute,
            "daily_limit": config.daily_limit,
            "minimum_interval_seconds": int(config.minimum_interval.total_seconds()),
            "maximum_lifetime_seconds": int(config.maximum_lifetime.total_seconds()),
            "quiet_until": settings.quiet_until.isoformat() if settings.quiet_until else None,
            "policy_version": config.policy_version,
            "revision": settings.revision,
            "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
            "automatic_enabled": settings.automatic_enabled,
            "scheduled_minute": settings.scheduled_minute,
            "greeting_text": settings.greeting_text,
            "topic_enabled": settings.topic_enabled,
        }

    def proactive_policy(self):
        with self._open() as connection:
            return self._proactive_json(
                SQLiteProactivePolicyStore(connection).get("user:self")
            )

    def proactive_schedule_status(self):
        """解释今天的定时触发条件；只读时间与状态，不读取对话正文。"""

        subject_id = "user:self"
        now = self.clock()
        with self._open() as connection:
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            history = SQLiteProactiveHistoryReader(connection)
            runtime = history.read(subject_id, now=now)
            offset = timezone(timedelta(minutes=settings.config.utc_offset_minutes))
            local_day = now.astimezone(offset).date()
            idempotency_key = f"explicit-schedule:{local_day.isoformat()}"
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection, commit_changes=False),
                clock=lambda: now,
            )
            user_chatted_today = history.user_chatted_on_local_date(
                now=now,
                utc_offset_minutes=settings.config.utc_offset_minutes,
            )
            already_evaluated_today = (
                ledger.get_by_idempotency(subject_id, idempotency_key) is not None
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

    def arm_proactive_schedule_override(self, request):
        """仅授权今天当前设置中的未来时刻；不立即投递。"""

        subject_id = "user:self"
        now = self.clock()
        with self._open(write_capability="proactive") as connection:
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            if settings.revision != request.expected_policy_revision:
                raise MemoryAccessError("proactive_settings_conflict", 409)
            if not settings.config.enabled or not settings.automatic_enabled:
                raise MemoryAccessError("proactive_schedule_override_requires_enabled", 400)
            local_zone = timezone(
                timedelta(minutes=settings.config.utc_offset_minutes)
            )
            local_now = now.astimezone(local_zone)
            if local_now.weekday() not in settings.config.allowed_weekdays:
                raise MemoryAccessError("proactive_schedule_override_weekday_blocked", 400)
            current_minute = local_now.hour * 60 + local_now.minute
            if current_minute >= settings.scheduled_minute:
                raise MemoryAccessError("proactive_schedule_override_time_not_future", 400)
            try:
                row = SQLiteProactiveScheduleOverrideStore(connection).arm(
                    override_id=secrets.token_hex(16),
                    subject_id=subject_id,
                    local_date=local_now.date().isoformat(),
                    scheduled_minute=settings.scheduled_minute,
                    policy_revision=settings.revision,
                    now=now,
                )
            except ValueError:
                raise MemoryAccessError("proactive_schedule_override_already_armed", 409) from None
            return row

    def cancel_proactive_schedule_override(
        self, override_id, *, expected_revision,
    ):
        now = self.clock()
        with self._open(write_capability="proactive") as connection:
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
                raise MemoryAccessError("proactive_schedule_override_conflict", 409) from None

    @staticmethod
    def _topic_seed_json(row, *, now):
        valid_from = (
            datetime.fromisoformat(row["scenario_valid_from"])
            if row["scenario_valid_from"] else None
        )
        valid_to = (
            datetime.fromisoformat(row["scenario_valid_to"])
            if row["scenario_valid_to"] else None
        )
        return {
            "id": row["id"], "subject_id": row["subject_id"],
            "scenario_id": row["scenario_id"], "prompt_text": row["prompt_text"],
            "status": row["status"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "revision": row["revision"],
            "source": {
                "layer": "l2", "title": row["scenario_title"],
                "summary": row["scenario_summary"],
                "status": row["scenario_status"],
            },
            "usable": (
                row["status"] == "active" and row["scenario_status"] == "active"
                and (valid_from is None or valid_from <= now)
                and (valid_to is None or valid_to > now)
            ),
        }

    def list_proactive_topic_seeds(self):
        now = self.clock()
        with self._open() as connection:
            rows = SQLiteProactiveTopicStore(connection).list("user:self")
            return {"items": [self._topic_seed_json(row, now=now) for row in rows]}

    def create_proactive_topic_seed(self, request):
        now = self.clock()
        seed = ProactiveTopicSeed(
            id=request.request_id.replace("-", ""), subject_id="user:self",
            scenario_id=request.scenario_id, prompt_text=request.prompt_text,
            status=TopicSeedStatus.ACTIVE, created_at=now, updated_at=now,
        )
        with self._open(write_capability="proactive") as connection:
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
                code = "topic_seed_request_replayed" if existing else "topic_seed_conflict"
                raise MemoryAccessError(code, 409) from None
            except ValueError as error:
                code = str(error)
                status = 404 if code == "topic_seed_scenario_not_found" else 409
                raise MemoryAccessError(code, status) from None
            row = next(item for item in store.list("user:self") if item["id"] == seed.id)
            return self._topic_seed_json(row, now=now)

    def disable_proactive_topic_seed(self, seed_id, *, expected_revision):
        now = self.clock()
        with self._open(write_capability="proactive") as connection:
            row = connection.execute(
                "SELECT subject_id,status,revision FROM proactive_topic_seeds WHERE id=?",
                (seed_id,),
            ).fetchone()
            if row is None or row["subject_id"] != "user:self":
                raise MemoryAccessError("topic_seed_not_found", 404)
            if row["status"] == "disabled":
                if row["revision"] == expected_revision + 1:
                    return {"id": seed_id, "status": "disabled",
                            "revision": row["revision"], "replayed": True}
                raise MemoryAccessError("topic_seed_conflict", 409)
            if not SQLiteProactiveTopicStore(connection).disable(
                seed_id, expected_revision=expected_revision, now=now,
            ):
                raise MemoryAccessError("topic_seed_conflict", 409)
            return {"id": seed_id, "status": "disabled",
                    "revision": expected_revision + 1, "replayed": False}

    def update_proactive_policy(self, request):
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
            # 自动开关与定时点的组合约束也必须在打开写事务前验证，
            # 否则非法网页输入会被数据库边界误报成“数据库不可用”。
            ProactivePolicySettings(
                "user:self",
                config,
                request.quiet_until,
                automatic_enabled=request.automatic_enabled,
                scheduled_minute=request.scheduled_minute,
                greeting_text=request.greeting_text,
                topic_enabled=request.topic_enabled,
            )
        except ValueError:
            raise MemoryAccessError("invalid_proactive_policy", 400) from None
        with self._open(write_capability="proactive") as connection:
            store = SQLiteProactivePolicyStore(connection)
            current = store.get("user:self")
            if current.revision != request.expected_revision:
                raise MemoryAccessError("proactive_settings_conflict", 409)
            updated = ProactivePolicySettings(
                "user:self", config, request.quiet_until,
                current.revision + 1, datetime.now(UTC),
                request.automatic_enabled, request.scheduled_minute,
                request.greeting_text, request.topic_enabled,
            )
            return self._proactive_json(
                store.save(updated, expected_revision=current.revision)
            )

    @staticmethod
    def _outreach_result(outreach, *, replayed, decision=None, delivery=None, device=None):
        return {
            "outreach_id": outreach.id,
            "state": outreach.state.value,
            "revision": outreach.revision,
            "replayed": replayed,
            "policy_action": decision.action.value if decision else None,
            "policy_reason": decision.reason.value if decision else None,
            "delivery_reason": delivery.reason_code if delivery else None,
            "device": None if device is None else {
                "ready": device.ready,
                "user_session_active": device.user_session_active,
                "reason": device.reason_code,
            },
        }

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
                return self._outreach_result(existing, replayed=True)
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
                return self._outreach_result(existing, replayed=True, device=device)
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
            return self._outreach_result(
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
                return self._outreach_result(blocked, replayed=False, device=device)
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
            return self._outreach_result(
                result.outreach,
                replayed=False,
                decision=result.decision,
                delivery=result.delivery,
                device=device,
            )

    def proactive_history(self, *, limit=20):
        """只读最近投影和最后事件原因，不暴露幂等键或内部连接数据。"""

        subject_id = "user:self"
        if type(limit) is not int or not 1 <= limit <= 100:
            raise MemoryAccessError("invalid_proactive_history_limit", 400)
        with self._open() as connection:
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection, commit_changes=False),
                clock=self.clock,
            )
            outcomes = SQLiteInteractionOutcomeStore(
                connection, commit_changes=False,
            )
            feedbacks = SQLiteCompanionFeedbackStore(connection)
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
                delivery_levels = {
                    "queued": "server_queued",
                    "transport_sent": "transport_sent",
                    "device_acknowledged": "device_acknowledged",
                    "played": "played",
                }
                delivery_evidence = delivery_levels.get(outreach.state.value)
                if not formal_trigger:
                    observation_state = "not_applicable"
                elif outcome is not None:
                    observation_state = "subsequent_user_message_observed"
                elif delivery_evidence is not None:
                    observation_state = "awaiting_subsequent_user_message"
                else:
                    observation_state = "delivery_not_established"
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

    @staticmethod
    def _strategy_candidate_json(candidate, store):
        local_zone = timezone(
            timedelta(minutes=candidate.utc_offset_minutes)
        )
        sources = []
        for source in store.list_sources(candidate.id):
            local = datetime.fromisoformat(source["queued_at"]).astimezone(local_zone)
            sources.append({
                **source,
                "local_date": local.date().isoformat(),
                "local_minute": local.hour * 60 + local.minute,
            })
        return {
            "id": candidate.id,
            "subject_id": candidate.subject_id,
            "status": candidate.status.value,
            "suggested_minute": candidate.suggested_minute,
            "utc_offset_minutes": candidate.utc_offset_minutes,
            "evidence_count": candidate.evidence_count,
            "distinct_local_dates": candidate.distinct_local_dates,
            "rationale_code": candidate.rationale_code,
            "generator_version": candidate.generator_version,
            "created_at": candidate.created_at.isoformat(),
            "updated_at": candidate.updated_at.isoformat(),
            "revision": candidate.revision,
            "active": False,
            "sources": sources,
        }

    def list_companion_strategy_candidates(self):
        with self._open() as connection:
            store = SQLiteCompanionStrategyCandidateStore(connection)
            return {"items": [
                self._strategy_candidate_json(candidate, store)
                for candidate in store.list("user:self")
            ]}

    def list_user_initiated_interactions(self, *, limit=30):
        """只返回时间与来源 ID，不把私人消息正文复制到观察视图。"""

        if not 1 <= limit <= 100:
            raise ValueError("user_initiated_interaction_limit_invalid")
        with self._open() as connection:
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

    @staticmethod
    def _routine_candidate_json(candidate, store):
        local_zone = timezone(timedelta(minutes=candidate.utc_offset_minutes))
        sources = []
        for source in store.list_sources(candidate.id):
            local = datetime.fromisoformat(source["occurred_at"]).astimezone(
                local_zone
            )
            sources.append({
                **source,
                "local_date": local.date().isoformat(),
                "local_minute": local.hour * 60 + local.minute,
            })
        return {
            "id": candidate.id,
            "subject_id": candidate.subject_id,
            "status": candidate.status.value,
            "expected_minute": candidate.expected_minute,
            "utc_offset_minutes": candidate.utc_offset_minutes,
            "observation_window_minutes": candidate.observation_window_minutes,
            "evidence_count": candidate.evidence_count,
            "distinct_local_dates": candidate.distinct_local_dates,
            "rationale_code": candidate.rationale_code,
            "generator_version": candidate.generator_version,
            "created_at": candidate.created_at.isoformat(),
            "updated_at": candidate.updated_at.isoformat(),
            "revision": candidate.revision,
            "active": False,
            "sources": sources,
        }

    def list_companion_routine_candidates(self):
        with self._open() as connection:
            store = SQLiteCompanionRoutineCandidateStore(connection)
            return {"items": [
                self._routine_candidate_json(candidate, store)
                for candidate in store.list("user:self")
            ]}

    def generate_companion_routine_candidate(self):
        """分析用户主动出现时间；不把候选变成联系规则。"""

        with self._open(write_capability="proactive") as connection:
            policy = SQLiteProactivePolicyStore(connection).get("user:self")
            store = SQLiteCompanionRoutineCandidateStore(connection)
            result = CompanionRoutineCandidateService(
                store, clock=self.clock,
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
                    else self._routine_candidate_json(result.candidate, store)
                ),
            }

    def dismiss_companion_routine_candidate(
        self, candidate_id, *, expected_revision,
    ):
        with self._open(write_capability="proactive") as connection:
            store = SQLiteCompanionRoutineCandidateStore(connection)
            candidate = store.dismiss(
                candidate_id, subject_id="user:self",
                expected_revision=expected_revision, now=self.clock(),
            )
            if candidate is None:
                raise MemoryAccessError("companion_routine_candidate_conflict", 409)
            return self._routine_candidate_json(candidate, store)

    def generate_companion_strategy_candidate(self):
        """只生成未生效候选；不读取消息正文、不修改 P4 设置。"""

        with self._open(write_capability="proactive") as connection:
            policy = SQLiteProactivePolicyStore(connection).get("user:self")
            store = SQLiteCompanionStrategyCandidateStore(connection)
            result = CompanionStrategyCandidateService(
                store, clock=self.clock,
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
                    else self._strategy_candidate_json(result.candidate, store)
                ),
            }

    def dismiss_companion_strategy_candidate(
        self, candidate_id, *, expected_revision,
    ):
        with self._open(write_capability="proactive") as connection:
            store = SQLiteCompanionStrategyCandidateStore(connection)
            candidate = store.dismiss(
                candidate_id, subject_id="user:self",
                expected_revision=expected_revision, now=self.clock(),
            )
            if candidate is None:
                raise MemoryAccessError("companion_strategy_candidate_conflict", 409)
            return self._strategy_candidate_json(candidate, store)

    def confirm_proactive_played(self, outreach_id, *, expected_revision):
        """把所有者亲耳观察追加为证据；不从设备状态反推播放成功。"""

        subject_id = "user:self"
        with self._open(write_capability="proactive") as connection:
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection), clock=self.clock,
            )
            outreach = ledger.get(outreach_id)
            if outreach is None or outreach.subject_id != subject_id:
                raise MemoryAccessError("proactive_outreach_not_found", 404)
            if outreach.state == OutreachState.PLAYED:
                return self._outreach_result(outreach, replayed=True)
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
            return self._outreach_result(played, replayed=False)

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

    def list_sources(self, *, query="", role="all", link_state="all", limit=25, offset=0):
        """分页读取 L0，并明确它是否已经成为任意 L1 的证据。"""

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
            return {
                "id": source["id"], "role": source["role"], "content": source["content"],
                "created_at": source["created_at"], "derived_memories": derived,
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
        if state not in {"all", "candidate", "active", "rejected", "stale"}:
            raise MemoryAccessError("scenario_filter_invalid", 400)
        with self._open() as connection:
            where, parameters = ("", []) if state == "all" else (" WHERE status=?", [state])
            total = connection.execute(
                "SELECT count(*) FROM scenario_memories" + where, parameters
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM scenario_memories" + where
                + " ORDER BY generated_at DESC, id DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
            return {"items": [self._scenario_json(row) for row in rows],
                    "total": total, "limit": limit, "offset": offset}

    def list_scenario_source_inbox(self):
        """列出尚未进入当前候选/已接受 L2 的活跃 L1；只读且不判断主题。"""

        with self._open() as connection:
            rows = connection.execute(
                "SELECT a.id, a.subject_id, a.content, a.recorded_at, "
                "count(DISTINCT e.source_message_id) AS source_message_count "
                "FROM atomic_memories a "
                "JOIN memory_evidence e ON e.memory_id=a.id "
                "JOIN conversation_messages m ON m.id=e.source_message_id AND m.role='user' "
                "WHERE a.retired_at IS NULL AND NOT EXISTS ("
                "SELECT 1 FROM scenario_memory_sources s "
                "JOIN scenario_memories l2 ON l2.id=s.scenario_id "
                "WHERE s.memory_id=a.id AND l2.status IN ('candidate','active')) "
                "GROUP BY a.id ORDER BY a.recorded_at DESC, a.id DESC LIMIT 100"
            ).fetchall()
            return {
                "items": [dict(row) for row in rows],
                "total": len(rows),
                "limited": len(rows) == 100,
                "selection_is_semantic": False,
            }

    def get_scenario(self, scenario_id):
        with self._open() as connection:
            row = connection.execute(
                "SELECT * FROM scenario_memories WHERE id=?", (scenario_id,)
            ).fetchone()
            if row is None:
                raise MemoryAccessError("scenario_not_found", 404)
            data = self._scenario_json(row)
            sources = [dict(source) for source in connection.execute(
                "SELECT s.*, a.content AS current_content, a.retired_at "
                "FROM scenario_memory_sources s LEFT JOIN atomic_memories a ON a.id=s.memory_id "
                "WHERE s.scenario_id=? ORDER BY s.linked_at, s.memory_id",
                (scenario_id,),
            ).fetchall()]
            # L2 详情必须能沿 L1 继续回到 L0 原话；否则“来源快照”仍只是
            # 另一个派生结论，用户无法判断场景总结有没有超出原始证据。
            for source in sources:
                source["l0_sources"] = [dict(item) for item in connection.execute(
                    "SELECT e.source_message_id, e.source_type, e.linked_at, "
                    "m.role, m.content, m.created_at FROM memory_evidence e "
                    "LEFT JOIN conversation_messages m ON m.id=e.source_message_id "
                    "WHERE e.memory_id=? ORDER BY e.linked_at, e.source_message_id",
                    (source["memory_id"],),
                ).fetchall()]
            data["sources"] = sources
            data["lifecycle_events"] = [dict(event) for event in connection.execute(
                "SELECT id, action, actor_type, occurred_at, previous_status, "
                "new_status, scenario_revision FROM scenario_lifecycle_events "
                "WHERE scenario_id=? ORDER BY occurred_at, id",
                (scenario_id,),
            ).fetchall()]
            review = connection.execute(
                "SELECT decision,reviewer_type,reviewed_at,scenario_revision,"
                "policy_version,decision_reason FROM scenario_reviews WHERE scenario_id=?",
                (scenario_id,),
            ).fetchone()
            data["review"] = dict(review) if review is not None else None
            return data

    def preview_scenario(self, *, source_memory_ids):
        """读取所选来源后释放数据库，再调用模型生成不落库草稿。"""

        if not self.allow_scenario_management:
            raise MemoryAccessError("scenario_management_disabled", 403)
        if self.scenario_producer is None:
            raise MemoryAccessError("scenario_model_preview_unavailable", 503)
        with self._open() as connection:
            store = SQLiteMemoryStore(connection)
            sources = []
            for value in source_memory_ids:
                memory = store.get(MemoryId(value))
                if memory is None:
                    raise MemoryAccessError("scenario_source_l1_missing", 400)
                if memory.retired_at is not None:
                    raise MemoryAccessError("scenario_source_l1_retired", 400)
                sources.append(ScenarioProposalInput(
                    memory.id,
                    memory.subject_id,
                    memory.content,
                    tuple(str(item.source_message_id) for item in store.list_evidence(memory.id)),
                ))
        try:
            proposal = ScenarioProposalService(self.scenario_producer).preview(tuple(sources))
        except ScenarioProposalError as error:
            raise MemoryAccessError(str(error), 400) from None
        return {
            "title": proposal.title,
            "summary": proposal.summary,
            "source_memory_ids": [str(value) for value in proposal.source_memory_ids],
            "generator_name": "model_assisted_console",
            "generator_version": SCENARIO_PROMPT_VERSION,
            "model": self.scenario_model,
            "persisted": False,
        }

    def create_scenario(self, *, title, summary, source_memory_ids, creation_kind="manual",
                        valid_from=None, valid_to=None):
        with self._open(write_capability="scenario") as connection:
            service = ScenarioManagementService(
                memory_store=SQLiteMemoryStore(connection, commit_changes=False),
                scenario_store=SQLiteScenarioStore(connection, commit_changes=False),
            )
            try:
                try:
                    parsed_valid_from = datetime.fromisoformat(valid_from) if valid_from else None
                    parsed_valid_to = datetime.fromisoformat(valid_to) if valid_to else None
                except ValueError:
                    raise MemoryAccessError("scenario_valid_time_invalid", 400) from None
                if creation_kind == "model_assisted" and self.scenario_producer is None:
                    raise MemoryAccessError("scenario_model_preview_unavailable", 503)
                generator_name = (
                    "model_assisted_console" if creation_kind == "model_assisted"
                    else "manual_console"
                )
                generator_version = (
                    SCENARIO_PROMPT_VERSION if creation_kind == "model_assisted" else "1"
                )
                scenario = service.create_candidate(
                    title=title,
                    summary=summary,
                    source_memory_ids=tuple(MemoryId(value) for value in source_memory_ids),
                    generator_name=generator_name,
                    generator_version=generator_version,
                    valid_from=parsed_valid_from,
                    valid_to=parsed_valid_to,
                )
            except (ValueError, LookupError) as error:
                raise MemoryAccessError(str(error), 400) from None
            connection.commit()
            return {"created": True, "id": str(scenario.id), "status": scenario.status.value}

    def review_scenario(self, scenario_id, *, decision, expected_revision):
        with self._open(write_capability="scenario") as connection:
            service = ScenarioManagementService(
                memory_store=SQLiteMemoryStore(connection, commit_changes=False),
                scenario_store=SQLiteScenarioStore(connection, commit_changes=False),
            )
            try:
                scenario = service.review(
                    ScenarioId(scenario_id), ScenarioReviewDecision(decision),
                    expected_revision=expected_revision,
                )
            except ValueError as error:
                raise MemoryAccessError(str(error), 409) from None
            connection.commit()
            return {"reviewed": True, "id": scenario_id,
                    "status": scenario.status.value, "revision": scenario.revision}

    def end_scenario(self, scenario_id, *, expected_revision):
        """显式结束 active L2；内容与来源不变，新增生命周期事件。"""

        with self._open(write_capability="scenario") as connection:
            service = ScenarioManagementService(
                memory_store=SQLiteMemoryStore(connection, commit_changes=False),
                scenario_store=SQLiteScenarioStore(connection, commit_changes=False),
            )
            try:
                scenario = service.end(
                    ScenarioId(scenario_id), expected_revision=expected_revision,
                )
            except ValueError as error:
                raise MemoryAccessError(str(error), 409) from None
            connection.commit()
            return {"ended": True, "id": scenario_id,
                    "status": scenario.status.value, "revision": scenario.revision}

    def list_personas(self, *, state="all", limit=25, offset=0):
        if state not in {"all", "candidate", "active", "rejected", "stale"}:
            raise MemoryAccessError("persona_filter_invalid", 400)
        with self._open() as connection:
            where, parameters = ("", []) if state == "all" else (" WHERE status=?", [state])
            total = connection.execute(
                "SELECT count(*) FROM persona_memories" + where, parameters,
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM persona_memories" + where
                + " ORDER BY generated_at DESC, id DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
            return {"items": [self._persona_json(row) for row in rows],
                    "total": total, "limit": limit, "offset": offset}

    def get_persona_profile(self):
        """构造一份用户可见画像；底层原子断言和来源链保持不变。"""

        with self._open() as connection:
            store = SQLitePersonaStore(connection)
            profile = build_persona_profile(
                CURRENT_USER_SUBJECT_ID,
                store.list_active(CURRENT_USER_SUBJECT_ID),
            )
            counts = {status: 0 for status in ("candidate", "active", "rejected", "stale")}
            for row in connection.execute(
                "SELECT status, count(*) AS amount FROM persona_memories "
                "WHERE subject_id=? GROUP BY status",
                (str(CURRENT_USER_SUBJECT_ID),),
            ).fetchall():
                counts[row["status"]] = row["amount"]
            return {
                "subject_id": str(profile.subject_id),
                "representation": "aggregated_active_assertions_v1",
                "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
                "active_assertion_count": profile.assertion_count,
                "status_counts": counts,
                "sections": [{
                    "kind": section.kind.value,
                    "items": [self._persona_model_json(item) for item in section.assertions],
                } for section in profile.sections],
            }

    def list_persona_source_options(self):
        """只返回当前有效的 L1 和已接受 L2；不自动判断适合哪个画像。"""

        with self._open() as connection:
            l1_rows = connection.execute(
                "SELECT id, subject_id, content, recorded_at FROM atomic_memories "
                "WHERE retired_at IS NULL ORDER BY recorded_at DESC, id DESC LIMIT 100"
            ).fetchall()
            l2_rows = connection.execute(
                "SELECT id, subject_id, title, summary, generated_at FROM scenario_memories "
                "WHERE status='active' ORDER BY generated_at DESC, id DESC LIMIT 100"
            ).fetchall()
            return {
                "l1": [{"layer": "l1", "id": row["id"], "subject_id": row["subject_id"],
                        "content": row["content"], "recorded_at": row["recorded_at"]}
                       for row in l1_rows],
                "l2": [{"layer": "l2", "id": row["id"], "subject_id": row["subject_id"],
                        "content": f'{row["title"]}：{row["summary"]}',
                        "recorded_at": row["generated_at"]} for row in l2_rows],
                "selection_is_semantic": False,
            }

    def get_persona(self, persona_id):
        with self._open() as connection:
            store = SQLitePersonaStore(connection)
            persona = store.get(PersonaId(persona_id))
            if persona is None:
                raise MemoryAccessError("persona_not_found", 404)
            data = self._persona_model_json(persona)
            audit = connection.execute(
                "SELECT source_count, source_message_count, observation_day_count "
                "FROM persona_generation_audits WHERE persona_id=?", (persona_id,),
            ).fetchone()
            data["audit"] = dict(audit) if audit is not None else None
            sources = []
            for source in store.list_sources(PersonaId(persona_id)):
                resolved = store.resolve_source(source.source_layer, source.source_id)
                messages = []
                if source.source_layer == PersonaSourceLayer.L1:
                    messages = [dict(row) for row in connection.execute(
                        "SELECT m.id, m.content, m.created_at, e.source_type FROM memory_evidence e "
                        "JOIN conversation_messages m ON m.id=e.source_message_id "
                        "WHERE e.memory_id=? AND m.role='user' ORDER BY m.created_at, m.id",
                        (source.source_id,),
                    ).fetchall()]
                else:
                    messages = [dict(row) for row in connection.execute(
                        "SELECT DISTINCT m.id, m.content, m.created_at, e.source_type "
                        "FROM scenario_memory_sources s JOIN memory_evidence e ON e.memory_id=s.memory_id "
                        "JOIN conversation_messages m ON m.id=e.source_message_id "
                        "WHERE s.scenario_id=? AND m.role='user' ORDER BY m.created_at, m.id",
                        (source.source_id,),
                    ).fetchall()]
                sources.append({
                    "source_layer": source.source_layer.value,
                    "source_id": source.source_id,
                    "source_content_snapshot": source.source_content_snapshot,
                    "linked_at": source.linked_at.isoformat(),
                    "current_content": resolved.content_snapshot if resolved else None,
                    "active": resolved is not None,
                    "l0_sources": messages,
                })
            data["sources"] = sources
            data["replaces"] = [self._persona_replacement_json(
                replacement, store.get(replacement.replaced_persona_id),
            ) for replacement in store.list_replacements(PersonaId(persona_id))]
            data["replaced_by"] = [self._persona_replacement_json(
                replacement, store.get(replacement.candidate_persona_id),
            ) for replacement in store.list_replaced_by(PersonaId(persona_id))]
            review = store.get_review(PersonaId(persona_id))
            data["review"] = None if review is None else {
                "decision": review.decision.value,
                "reviewer_type": review.reviewer_type.value,
                "reviewed_at": review.reviewed_at.isoformat(),
                "persona_revision": review.persona_revision,
                "policy_version": review.policy_version,
                "decision_reason": review.decision_reason,
            }
            data["lifecycle_events"] = [{
                "id": str(event.id), "action": event.action.value,
                "source_layer": event.source_layer.value, "source_id": event.source_id,
                "occurred_at": event.occurred_at.isoformat(),
                "previous_status": event.previous_status.value,
                "new_status": event.new_status.value,
                "persona_revision": event.persona_revision,
            } for event in store.list_lifecycle_events(PersonaId(persona_id))]
            return data

    def create_persona(self, *, kind, basis, label, statement, sources,
                       valid_from=None, valid_to=None, creation_kind="manual",
                       replaces=()):
        with self._open(write_capability="persona") as connection:
            store = SQLitePersonaStore(connection, commit_changes=False)
            service = PersonaManagementService(persona_store=store)
            try:
                try:
                    parsed_valid_from = datetime.fromisoformat(valid_from) if valid_from else None
                    parsed_valid_to = datetime.fromisoformat(valid_to) if valid_to else None
                except ValueError:
                    raise MemoryAccessError("persona_valid_time_invalid", 400) from None
                if creation_kind in {"model_assisted", "model_consolidation"} and self.persona_producer is None:
                    raise MemoryAccessError("persona_model_preview_unavailable", 503)
                model_generated = creation_kind in {"model_assisted", "model_consolidation"}
                persona = service.create_candidate(
                    kind=PersonaKind(kind), basis=PersonaBasis(basis), label=label,
                    statement=statement,
                    source_refs=tuple((PersonaSourceLayer(item["layer"]), item["id"])
                                      for item in sources),
                    generator_name=(
                        "model_assisted_console" if model_generated
                        else "manual_console"
                    ),
                    generator_version=(
                        PERSONA_CONSOLIDATION_PROMPT_VERSION
                        if creation_kind == "model_consolidation"
                        else PERSONA_PROMPT_VERSION if creation_kind == "model_assisted"
                        else "1"
                    ),
                    valid_from=parsed_valid_from, valid_to=parsed_valid_to,
                    replaces=tuple(PersonaId(item) for item in replaces),
                )
            except (ValueError, LookupError) as error:
                raise MemoryAccessError(str(error), 400) from None
            connection.commit()
            return {"created": True, "id": str(persona.id), "status": persona.status.value}

    def preview_persona(self, *, basis, sources):
        """读取白名单来源和用户 L0 后关闭数据库，再发起一次模型预览。"""

        if not self.allow_persona_management:
            raise MemoryAccessError("persona_management_disabled", 403)
        if self.persona_producer is None:
            raise MemoryAccessError("persona_model_preview_unavailable", 503)
        try:
            parsed_basis = PersonaBasis(basis)
        except ValueError:
            raise MemoryAccessError("persona_basis_invalid", 400) from None
        inputs = []
        with self._open() as connection:
            store = SQLitePersonaStore(connection)
            for item in sources:
                layer = PersonaSourceLayer(item["layer"])
                resolved = store.resolve_source(layer, item["id"])
                if resolved is None:
                    raise MemoryAccessError("persona_source_missing_or_inactive", 400)
                if layer == PersonaSourceLayer.L1:
                    rows = connection.execute(
                        "SELECT m.id, m.content, m.created_at FROM memory_evidence e "
                        "JOIN conversation_messages m ON m.id=e.source_message_id "
                        "WHERE e.memory_id=? AND m.role='user' ORDER BY m.created_at,m.id",
                        (item["id"],),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        "SELECT DISTINCT m.id,m.content,m.created_at FROM scenario_memory_sources s "
                        "JOIN memory_evidence e ON e.memory_id=s.memory_id "
                        "JOIN conversation_messages m ON m.id=e.source_message_id "
                        "WHERE s.scenario_id=? AND m.role='user' ORDER BY m.created_at,m.id",
                        (item["id"],),
                    ).fetchall()
                evidence = tuple(PersonaProposalEvidence(
                    row["id"], row["content"],
                    datetime.fromisoformat(row["created_at"]).astimezone(UTC).date().isoformat(),
                ) for row in rows)
                inputs.append(PersonaProposalInput(
                    layer, item["id"], resolved.subject_id,
                    resolved.content_snapshot, evidence,
                ))
        try:
            proposal = PersonaProposalService(self.persona_producer).preview(
                basis=parsed_basis, sources=tuple(inputs),
            )
        except PersonaProposalError as error:
            raise MemoryAccessError(str(error), 400) from None
        return {
            "kind": proposal.kind.value,
            "basis": proposal.basis.value,
            "label": proposal.label,
            "statement": proposal.statement,
            "sources": [{"layer": layer.value, "id": source_id}
                        for layer, source_id in proposal.source_refs],
            "generator_name": "model_assisted_console",
            "generator_version": PERSONA_PROMPT_VERSION,
            "model": self.persona_model,
            "persisted": False,
        }

    def preview_persona_consolidation(self, *, basis, sources):
        """读取显式来源与当前有效画像后关闭数据库，再生成整理建议。"""

        if not self.allow_persona_management:
            raise MemoryAccessError("persona_management_disabled", 403)
        if self.persona_producer is None:
            raise MemoryAccessError("persona_model_preview_unavailable", 503)
        try:
            parsed_basis = PersonaBasis(basis)
        except ValueError:
            raise MemoryAccessError("persona_basis_invalid", 400) from None
        inputs = []
        with self._open() as connection:
            store = SQLitePersonaStore(connection)
            active_personas = store.list_active(CURRENT_USER_SUBJECT_ID)
            for item in sources:
                layer = PersonaSourceLayer(item["layer"])
                resolved = store.resolve_source(layer, item["id"])
                if resolved is None:
                    raise MemoryAccessError("persona_source_missing_or_inactive", 400)
                if layer == PersonaSourceLayer.L1:
                    rows = connection.execute(
                        "SELECT m.id,m.content,m.created_at FROM memory_evidence e "
                        "JOIN conversation_messages m ON m.id=e.source_message_id "
                        "WHERE e.memory_id=? AND m.role='user' ORDER BY m.created_at,m.id",
                        (item["id"],),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        "SELECT DISTINCT m.id,m.content,m.created_at FROM scenario_memory_sources s "
                        "JOIN memory_evidence e ON e.memory_id=s.memory_id "
                        "JOIN conversation_messages m ON m.id=e.source_message_id "
                        "WHERE s.scenario_id=? AND m.role='user' ORDER BY m.created_at,m.id",
                        (item["id"],),
                    ).fetchall()
                inputs.append(PersonaProposalInput(
                    layer, item["id"], resolved.subject_id, resolved.content_snapshot,
                    tuple(PersonaProposalEvidence(
                        row["id"], row["content"],
                        datetime.fromisoformat(row["created_at"]).astimezone(UTC).date().isoformat(),
                    ) for row in rows),
                ))
        try:
            suggestion = PersonaConsolidationService(self.persona_producer).preview(
                basis=parsed_basis,
                sources=tuple(inputs),
                active_personas=active_personas,
            )
        except PersonaProposalError as error:
            raise MemoryAccessError(str(error), 400) from None
        candidate = suggestion.candidate
        return {
            "operation": suggestion.operation.value,
            "candidate": None if candidate is None else {
                "kind": candidate.kind.value,
                "basis": candidate.basis.value,
                "label": candidate.label,
                "statement": candidate.statement,
                "sources": [{"layer": layer.value, "id": source_id}
                            for layer, source_id in candidate.source_refs],
            },
            "replaces": [str(item) for item in suggestion.replaces],
            "generator_name": "model_assisted_console",
            "generator_version": PERSONA_CONSOLIDATION_PROMPT_VERSION,
            "model": self.persona_model,
            "persisted": False,
        }

    def review_persona(self, persona_id, *, decision, expected_revision):
        with self._open(write_capability="persona") as connection:
            service = PersonaManagementService(
                persona_store=SQLitePersonaStore(connection, commit_changes=False),
            )
            try:
                persona = service.review(
                    PersonaId(persona_id), PersonaReviewDecision(decision),
                    expected_revision=expected_revision,
                )
            except ValueError as error:
                raise MemoryAccessError(str(error), 409) from None
            connection.commit()
            return {"reviewed": True, "id": persona_id,
                    "status": persona.status.value, "revision": persona.revision}

    @staticmethod
    def _scenario_json(row):
        return {key: row[key] for key in (
            "id", "subject_id", "title", "summary", "generated_at", "valid_from",
            "valid_to", "status", "generator_name", "generator_version", "revision",
        )}

    @staticmethod
    def _persona_json(row):
        return {key: row[key] for key in (
            "id", "subject_id", "kind", "basis", "label", "statement",
            "generated_at", "valid_from", "valid_to", "status",
            "generator_name", "generator_version", "revision",
        )}

    @staticmethod
    def _persona_model_json(persona):
        return {
            "id": str(persona.id), "subject_id": str(persona.subject_id),
            "kind": persona.kind.value, "basis": persona.basis.value,
            "label": persona.label, "statement": persona.statement,
            "generated_at": persona.generated_at.isoformat(),
            "valid_from": persona.valid_from.isoformat() if persona.valid_from else None,
            "valid_to": persona.valid_to.isoformat() if persona.valid_to else None,
            "status": persona.status.value, "generator_name": persona.generator_name,
            "generator_version": persona.generator_version, "revision": persona.revision,
        }

    @staticmethod
    def _persona_replacement_json(replacement, related):
        return {
            "candidate_persona_id": str(replacement.candidate_persona_id),
            "replaced_persona_id": str(replacement.replaced_persona_id),
            "target_revision": replacement.target_revision,
            "linked_at": replacement.linked_at.isoformat(),
            "applied_at": replacement.applied_at.isoformat() if replacement.applied_at else None,
            "related": None if related is None else MemoryBackend._persona_model_json(related),
        }
