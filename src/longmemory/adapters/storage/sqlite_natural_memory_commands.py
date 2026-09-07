"""自然语言记忆操作的 SQLite 原子事务适配器。"""

from pathlib import Path
import sqlite3

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
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.application.natural_memory_commands import NaturalMemoryCommandService
from longmemory.core.common.identifiers import MessageId
from longmemory.core.conversation.models import ConversationMessage, MessageRole
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
