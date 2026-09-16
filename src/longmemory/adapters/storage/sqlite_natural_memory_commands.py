"""自然语言记忆操作的 SQLite 原子事务适配器。"""

from pathlib import Path
from datetime import datetime, timedelta, timezone
from math import ceil
import hashlib
import sqlite3
from uuid import uuid4

from longmemory.adapters.storage.sqlite_conversation_store import SQLiteConversationStore
from longmemory.adapters.storage.sqlite_interaction_outcome_store import (
    SQLiteInteractionOutcomeStore,
)
from longmemory.adapters.storage.sqlite_user_initiated_interaction_store import (
    SQLiteUserInitiatedInteractionStore,
)
from longmemory.adapters.storage.sqlite_companion_feedback_store import (
    SQLiteCompanionFeedbackStore,
)
from longmemory.application.natural_companion_commands import (
    NaturalCompanionCommandService,
)
from longmemory.application.follow_up_suggestions import (
    FollowUpSuggestionResult,
    parse_explicit_follow_up,
)
from longmemory.adapters.storage.sqlite_follow_up_store import (
    SQLiteFollowUpCandidateStore,
)
from longmemory.adapters.storage.sqlite_proactive_policy_store import (
    SQLiteProactivePolicyStore,
)
from longmemory.adapters.storage.sqlite_proactive_outreach_store import (
    SQLiteProactiveOutreachStore,
)
from longmemory.application.proactive import ProactiveOutreachLedger
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.application.natural_memory_commands import NaturalMemoryCommandService
from longmemory.core.common.identifiers import MessageId
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.core.proactive import (
    FollowUpCandidate,
    FollowUpCandidateStatus,
    OutreachEvidence,
    OutreachState,
    OutreachTrigger,
    OutreachPolicyConfig,
    ProactivePolicySettings,
)
from longmemory.infrastructure.database.schema import SCHEMA_VERSION


class SQLiteNaturalMemoryCommandHandler:
    """持有独立连接；每条已识别指令要么整体提交，要么整体回滚。"""

    def __init__(self, database: Path) -> None:
        self._connection = sqlite3.connect(
            database.resolve().as_uri() + "?mode=rw", uri=True, timeout=2,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA trusted_schema = OFF")
        if self._connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            self._connection.close()
            raise ValueError("自然纠正只支持已有的当前版本数据库。")
        self._service = NaturalMemoryCommandService(
            memory_store=SQLiteMemoryStore(self._connection, commit_changes=False),
            conversation_store=SQLiteConversationStore(self._connection, commit_changes=False),
        )
        self._outcome_observer = SQLiteInteractionOutcomeStore(
            self._connection, commit_changes=False,
        )
        self._user_initiated_observer = SQLiteUserInitiatedInteractionStore(
            self._connection, commit_changes=False,
        )
        self._companion_service = NaturalCompanionCommandService(
            conversation_store=SQLiteConversationStore(
                self._connection, commit_changes=False,
            ),
            feedback_store=SQLiteCompanionFeedbackStore(self._connection),
            cancel_recent_follow_up=self._cancel_recent_follow_up,
            reschedule_recent_follow_up=self._reschedule_recent_follow_up,
            set_proactive_frequency=self._set_proactive_frequency,
        )

    def _set_proactive_frequency(self, *, seconds, occurred_at):
        """在同一用户消息事务中更新频率；语音回执只报告已落库结果。"""

        store = SQLiteProactivePolicyStore(
            self._connection, commit_changes=False,
        )
        current = store.get("user:self")
        if current.automatic_interval_seconds == seconds:
            return "unchanged", current.config.enabled, current.automatic_enabled
        local_zone = timezone(
            timedelta(minutes=current.config.utc_offset_minutes)
        )
        local_now = occurred_at.astimezone(local_zone)
        anchor = (local_now.hour * 60 + local_now.minute + 1) % (24 * 60)
        config = OutreachPolicyConfig(
            enabled=current.config.enabled,
            utc_offset_minutes=current.config.utc_offset_minutes,
            allowed_weekdays=current.config.allowed_weekdays,
            allowed_start_minute=current.config.allowed_start_minute,
            allowed_end_minute=current.config.allowed_end_minute,
            daily_limit=ceil(86400 / seconds),
            # 调度轮询可能比整分钟时间槽晚几十秒。若防抖也恰好等于周期，
            # “每 1 分钟”会被上一条实际入队时间误拦；预留一分钟只吸收时间槽抖动，
            # 真正的周期边界仍由 schedule 的唯一时间槽控制。
            minimum_interval=timedelta(seconds=max(0, seconds - 60)),
            maximum_lifetime=current.config.maximum_lifetime,
            policy_version="proactive-contact-policy-v3",
        )
        updated = ProactivePolicySettings(
            current.subject_id, config, current.quiet_until,
            current.revision + 1, occurred_at,
            current.automatic_enabled, anchor, current.greeting_text,
            current.topic_enabled, seconds,
        )
        store.save(updated, expected_revision=current.revision)
        return "applied", config.enabled, updated.automatic_enabled

    def handle(self, event):
        companion_command = self._companion_service.recognizes(event)
        memory_command = (
            False if companion_command else self._service.recognizes(event)
        )
        if not companion_command and not memory_command:
            return None
        return self._execute(event, companion_command=companion_command)

    def handle_companion(self, event):
        """安全控制不依赖 L1 写入开关。"""

        if not self._companion_service.recognizes(event):
            return None
        return self._execute(event, companion_command=True)

    def handle_memory(self, event, *, write_enabled=True):
        if not self._service.recognizes(event):
            return None
        return self._execute(
            event, companion_command=False, write_enabled=write_enabled,
        )

    def suggest_follow_up(self, event, writes):
        """保存明确未来追问；总开关已开时同时原子建立一次性账本。"""

        added = tuple(item for item in (writes or ()) if item.operation == "add")
        if len(added) != 1:
            return None

        try:
            settings = SQLiteProactivePolicyStore(self._connection).get("user:self")
            draft = parse_explicit_follow_up(
                event.content, occurred_at=event.occurred_at,
                utc_offset_minutes=settings.config.utc_offset_minutes,
            )
        except (ValueError, KeyError):
            return None
        if draft is None:
            return None
        memory = self._connection.execute(
            "SELECT subject_id,content,retired_at FROM atomic_memories WHERE id=?",
            (added[0].item_id,),
        ).fetchone()
        if memory is None or memory["retired_at"] is not None:
            return FollowUpSuggestionResult(
                "not_created", warning_code="follow_up_source_unavailable",
            )
        candidate = FollowUpCandidate(
            id=uuid4().hex,
            subject_id=memory["subject_id"],
            source_memory_id=added[0].item_id,
            source_content_sha256=hashlib.sha256(
                memory["content"].encode("utf-8")
            ).hexdigest(),
            prompt_text=draft.prompt_text,
            follow_up_at=draft.follow_up_at,
            status=FollowUpCandidateStatus.CANDIDATE,
            created_at=event.occurred_at,
            updated_at=event.occurred_at,
            creation_kind="explicit_conversation_request",
            source_message_id=event.event_id,
        )
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            SQLiteFollowUpCandidateStore(
                self._connection, commit_changes=False,
            ).create(candidate)
            outreach = None
            # 用户在本轮已经明确说出“到时候问我”，这是该事项的一次授权；
            # 但它不能替代主动交流总开关，也不能绕过到点时的 P4 护栏。
            if settings.config.enabled:
                outreach = ProactiveOutreachLedger(
                    SQLiteProactiveOutreachStore(
                        self._connection, commit_changes=False,
                    ),
                    clock=lambda: event.occurred_at,
                ).create_candidate(
                    subject_id=candidate.subject_id,
                    trigger=OutreachTrigger.EXPLICIT_SCHEDULE,
                    trigger_reason_code="conversation_authorized_l1_follow_up",
                    content=candidate.prompt_text,
                    scheduled_for=candidate.follow_up_at,
                    expires_at=(
                        candidate.follow_up_at + settings.config.maximum_lifetime
                    ),
                    idempotency_key=f"follow-up:{candidate.id}",
                    policy_version=settings.config.policy_version,
                    follow_up_candidate_id=candidate.id,
                    follow_up_candidate_revision=candidate.revision,
                )
            self._connection.commit()
        except (sqlite3.IntegrityError, ValueError):
            self._connection.rollback()
            existing = self._connection.execute(
                "SELECT f.id,f.source_memory_id,f.prompt_text,f.follow_up_at,o.id AS outreach_id "
                "FROM companion_follow_up_candidates f "
                "LEFT JOIN proactive_outreach o ON o.follow_up_candidate_id=f.id "
                "WHERE f.source_message_id=?",
                (event.event_id,),
            ).fetchone()
            if existing is None:
                return FollowUpSuggestionResult(
                    "not_created", warning_code="follow_up_atomic_activation_failed",
                )
            return FollowUpSuggestionResult(
                "replayed", existing["id"], existing["source_memory_id"],
                existing["prompt_text"], existing["follow_up_at"],
                outreach_id=existing["outreach_id"],
            )
        except sqlite3.Error:
            self._connection.rollback()
            return FollowUpSuggestionResult(
                "not_created", warning_code="follow_up_storage_unavailable",
            )
        status = (
            "candidate_armed"
            if outreach is not None
            else "candidate_created_requires_proactive_enabled"
        )
        return FollowUpSuggestionResult(
            status, candidate.id, candidate.source_memory_id,
            candidate.prompt_text, candidate.follow_up_at.isoformat(),
            outreach_id=(outreach.id if outreach is not None else None),
        )

    def recognizes_follow_up(self, event) -> bool:
        """判断本轮是否必须先形成 L1，避免圆屏在安排结果前否认真实能力。

        普通圆屏对话仍可延后模型提取。只有同时包含明确日期、时刻和
        “到时候问我”的严格请求进入同步路径；这里只识别，不写数据库。
        """

        try:
            settings = SQLiteProactivePolicyStore(self._connection).get(
                "user:self"
            )
            return parse_explicit_follow_up(
                event.content,
                occurred_at=event.occurred_at,
                utc_offset_minutes=settings.config.utc_offset_minutes,
            ) is not None
        except (ValueError, KeyError, sqlite3.Error):
            return False

    def _cancel_recent_follow_up(
        self, *, subject_id, before, not_before,
    ) -> str:
        """只在最近 30 分钟恰好存在一个未来候选时执行语音取消。"""

        rows = self._connection.execute(
            "SELECT f.id,f.revision,o.id AS outreach_id,o.state AS outreach_state,"
            "o.revision AS outreach_revision "
            "FROM companion_follow_up_candidates f "
            "LEFT JOIN proactive_outreach o ON o.follow_up_candidate_id=f.id "
            "WHERE f.subject_id=? AND f.creation_kind='explicit_conversation_request' "
            "AND f.status='candidate' AND julianday(f.created_at)>=julianday(?) "
            "AND julianday(f.created_at)<julianday(?) "
            "AND julianday(f.follow_up_at)>julianday(?) "
            "ORDER BY julianday(f.created_at) DESC,f.id DESC LIMIT 2",
            (
                subject_id, not_before.isoformat(), before.isoformat(),
                before.isoformat(),
            ),
        ).fetchall()
        if not rows:
            return "target_not_found"
        if len(rows) != 1:
            return "target_ambiguous"
        row = rows[0]
        if row["outreach_id"] is not None:
            if row["outreach_state"] != "candidate":
                return "already_attempted"
            ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(
                    self._connection, commit_changes=False,
                ),
                clock=lambda: before,
            ).record_transition(
                row["outreach_id"],
                expected_revision=row["outreach_revision"],
                new_state=OutreachState.CANCELLED,
                reason_code="user_cancelled_recent_follow_up",
                evidence=OutreachEvidence.POLICY_DECISION,
            )
        changed = SQLiteFollowUpCandidateStore(
            self._connection, commit_changes=False,
        ).cancel(row["id"], expected_revision=row["revision"], now=before)
        if not changed:
            raise ValueError("follow_up_cancel_conflict")
        return "applied"

    def _reschedule_recent_follow_up(
        self, *, subject_id, before, not_before, hour, minute,
        source_message_id,
    ):
        """原子取消最近唯一未执行跟进，并以同一来源建立新时刻。"""

        rows = self._connection.execute(
            "SELECT f.id,f.source_memory_id,f.source_content_sha256,"
            "f.prompt_text,f.follow_up_at,f.revision,"
            "o.id AS outreach_id,o.state AS outreach_state,"
            "o.revision AS outreach_revision "
            "FROM companion_follow_up_candidates f "
            "LEFT JOIN proactive_outreach o ON o.follow_up_candidate_id=f.id "
            "WHERE f.subject_id=? "
            "AND f.creation_kind='explicit_conversation_request' "
            "AND f.status='candidate' AND julianday(f.created_at)>=julianday(?) "
            "AND julianday(f.created_at)<julianday(?) "
            "AND julianday(f.follow_up_at)>julianday(?) "
            "ORDER BY julianday(f.created_at) DESC,f.id DESC LIMIT 2",
            (
                subject_id, not_before.isoformat(), before.isoformat(),
                before.isoformat(),
            ),
        ).fetchall()
        if not rows:
            return "target_not_found", None
        if len(rows) != 1:
            return "target_ambiguous", None
        row = rows[0]
        if (
            row["outreach_id"] is not None
            and row["outreach_state"] != "candidate"
        ):
            return "already_attempted", None
        previous_time = datetime.fromisoformat(row["follow_up_at"])
        scheduled_for = previous_time.replace(
            hour=hour, minute=minute, second=0, microsecond=0,
        )
        if scheduled_for <= before:
            return "time_not_future", None
        if scheduled_for == previous_time:
            return "unchanged", scheduled_for

        settings = SQLiteProactivePolicyStore(self._connection).get(subject_id)
        if row["outreach_id"] is not None:
            ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(
                    self._connection, commit_changes=False,
                ),
                clock=lambda: before,
            ).record_transition(
                row["outreach_id"],
                expected_revision=row["outreach_revision"],
                new_state=OutreachState.CANCELLED,
                reason_code="user_rescheduled_recent_follow_up",
                evidence=OutreachEvidence.POLICY_DECISION,
            )
        changed = SQLiteFollowUpCandidateStore(
            self._connection, commit_changes=False,
        ).cancel(row["id"], expected_revision=row["revision"], now=before)
        if not changed:
            raise ValueError("follow_up_reschedule_conflict")

        candidate = FollowUpCandidate(
            id=uuid4().hex,
            subject_id=subject_id,
            source_memory_id=row["source_memory_id"],
            source_content_sha256=row["source_content_sha256"],
            prompt_text=row["prompt_text"],
            follow_up_at=scheduled_for,
            status=FollowUpCandidateStatus.CANDIDATE,
            created_at=before,
            updated_at=before,
            creation_kind="explicit_conversation_request",
            source_message_id=source_message_id,
        )
        SQLiteFollowUpCandidateStore(
            self._connection, commit_changes=False,
        ).create(candidate)
        if row["outreach_id"] is not None:
            ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(
                    self._connection, commit_changes=False,
                ),
                clock=lambda: before,
            ).create_candidate(
                subject_id=subject_id,
                trigger=OutreachTrigger.EXPLICIT_SCHEDULE,
                trigger_reason_code="conversation_rescheduled_l1_follow_up",
                content=candidate.prompt_text,
                scheduled_for=scheduled_for,
                expires_at=(
                    scheduled_for + settings.config.maximum_lifetime
                ),
                idempotency_key=f"follow-up:{candidate.id}",
                policy_version=settings.config.policy_version,
                follow_up_candidate_id=candidate.id,
                follow_up_candidate_revision=candidate.revision,
            )
        return "applied", scheduled_for

    def _execute(self, event, *, companion_command: bool, write_enabled=True):
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            result = (
                self._companion_service.handle(event)
                if companion_command else self._service.handle(
                    event, write_enabled=write_enabled,
                )
            )
            if result is not None:
                # 自然纠错、来源询问和删除等命令会在上面的服务中保存同一条
                # 用户 L0；这里在同一事务补记陪伴结果，避免命令路径漏样本。
                message = ConversationMessage(
                    MessageId(event.event_id), MessageRole.USER,
                    event.content, event.occurred_at,
                )
                self._outcome_observer.record_user_message(message)
                self._user_initiated_observer.record_user_message(message)
            self._connection.commit()
            return result
        except BaseException:
            self._connection.rollback()
            raise

    def close(self) -> None:
        self._connection.close()
