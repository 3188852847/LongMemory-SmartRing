"""自然语言记忆操作的 SQLite 原子事务适配器。"""

from pathlib import Path
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
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.application.natural_memory_commands import NaturalMemoryCommandService
from longmemory.core.common.identifiers import MessageId
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.core.proactive import FollowUpCandidate, FollowUpCandidateStatus
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
        )

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
        """为明确未来追问请求建立候选；失败不撤销已经提交的 L0/L1。"""

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
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            existing = self._connection.execute(
                "SELECT id,source_memory_id,prompt_text,follow_up_at "
                "FROM companion_follow_up_candidates WHERE source_message_id=?",
                (event.event_id,),
            ).fetchone()
            if existing is None:
                return FollowUpSuggestionResult(
                    "not_created", warning_code="follow_up_candidate_conflict",
                )
            return FollowUpSuggestionResult(
                "replayed", existing["id"], existing["source_memory_id"],
                existing["prompt_text"], existing["follow_up_at"],
            )
        except sqlite3.Error:
            self._connection.rollback()
            return FollowUpSuggestionResult(
                "not_created", warning_code="follow_up_storage_unavailable",
            )
        return FollowUpSuggestionResult(
            "candidate_created", candidate.id, candidate.source_memory_id,
            candidate.prompt_text, candidate.follow_up_at.isoformat(),
        )

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
