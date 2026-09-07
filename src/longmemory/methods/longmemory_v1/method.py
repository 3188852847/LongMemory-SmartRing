"""将现有 L0/L1 引擎包装为一个方法，不复制提取或检索算法。"""

from pathlib import Path
from contextlib import contextmanager
import sqlite3
from uuid import uuid4

from longmemory.adapters.storage.sqlite_conversation_store import SQLiteConversationStore
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.adapters.storage.sqlite_interaction_outcome_store import (
    SQLiteInteractionOutcomeStore,
)
from longmemory.application.memory_turn import MemoryTurnService
from longmemory.core.common.identifiers import MessageId
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.core.memory.extraction.service import MemoryExtractionService
from longmemory.core.memory.retrieval.service import KeywordMemoryRetriever
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema, SCHEMA_VERSION
from longmemory.infrastructure.logging.setup import log_event
from longmemory.methods.contracts import (
    MemoryEvent, MemorySupport, MethodCapabilities, ObservationResult,
    RetrievedTrace, UnsupportedCapabilityError, WriteTrace,
)


class LongMemoryV1:
    name = "longmemory_v1"
    implementation_version = "1"
    capabilities = MethodCapabilities(source_trace=True)

    def __init__(self, database_path: Path, *, existing_only: bool = False,
                 read_only: bool = False, allow_cross_thread: bool = False,
                 retriever_factory=None) -> None:
        # 沿用原实时装配的建库/版本检查行为；不能据此声称是只读实验入口。
        # 每个实例自己拥有连接，不缓存全局数据库，也不跨线程共享。
        if read_only and not existing_only:
            raise ValueError("只读打开必须指定已有库。")
        if existing_only:
            # 网页不能隐式建库或升级；mode=rw 在文件缺失时直接失败。
            mode = "ro" if read_only else "rw"
            self.connection = sqlite3.connect(
                database_path.resolve().as_uri() + "?mode=" + mode,
                uri=True,
                timeout=2,
                # 常驻 Runtime 会用自己的互斥锁串行化访问。普通调用方仍保留
                # SQLite 默认的线程归属检查，不能无意间跨线程共享连接。
                check_same_thread=not allow_cross_thread,
            )
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA trusted_schema = OFF")
            if read_only:
                self.connection.execute("PRAGMA query_only = ON")
        else:
            self.connection = open_database(database_path)
        self._closed = False
        try:
            if existing_only:
                if self.connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                    raise ValueError("网页聊天只支持已有的当前版本数据库，不自动迁移。")
            else:
                initialize_schema(self.connection)
            self.conversation_store = SQLiteConversationStore(self.connection)
            self.memory_store = SQLiteMemoryStore(self.connection)
            self.extractor = MemoryExtractionService()
            self.retriever = (retriever_factory(self.memory_store) if retriever_factory
                              else KeywordMemoryRetriever(self.memory_store))
            self.retrieval_name = getattr(self.retriever, "name", "keyword_v1")
            # 下列对象仅用于旧 CLI/小智 DTO 的兼容装配，不属于公共方法契约。
            self.turn_service = MemoryTurnService(
                conversation_store=SQLiteConversationStore(self.connection, commit_changes=False),
                memory_store=SQLiteMemoryStore(self.connection, commit_changes=False),
                memory_extractor=self.extractor,
                memory_retriever=self.retriever,
                audit_sink=log_event,
                write_transaction=self._write_transaction,
                interaction_outcome_observer=SQLiteInteractionOutcomeStore(
                    self.connection, commit_changes=False,
                ),
            )
        except BaseException:
            self.close()
            raise

    @contextmanager
    def _write_transaction(self):
        # 跨进程串行化写入，而非只在网页进程里加锁。模型调用不持此锁。
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def observe(self, event: MemoryEvent) -> ObservationResult:
        self._ensure_open()
        # 当前通用表不保存会话 ID。宁可拒绝，也不能悄悄丢失历史边界。
        if event.session_id is not None:
            raise UnsupportedCapabilityError("当前基线尚不支持持久化会话元数据。")
        operations = self.turn_service.observe(ConversationMessage(
            id=MessageId(event.event_id), role=MessageRole(event.role),
            content=event.content, created_at=event.occurred_at,
        ))
        return ObservationResult(event.event_id, tuple(
            WriteTrace(op.operation.value, str(op.memory.id), (event.event_id,))
            for op in operations
        ))

    def archive(self, event: MemoryEvent) -> ObservationResult:
        """暂停 L1 写入时仍保留 L0，避免制造不可解释的审计断层。"""

        self._ensure_open()
        if event.session_id is not None:
            raise UnsupportedCapabilityError("当前基线尚不支持持久化会话元数据。")
        self.turn_service.archive(ConversationMessage(
            id=MessageId(event.event_id), role=MessageRole(event.role),
            content=event.content, created_at=event.occurred_at,
        ))
        return ObservationResult(event.event_id, ())

    def wait_until_ready(self) -> None:
        """本实现同步完成写入，无后台任务；关闭后不能假装仍然就绪。"""
        self._ensure_open()

    def recall(self, query: str) -> MemorySupport:
        self._ensure_open()
        call_id = str(uuid4())
        self.connection.execute("BEGIN")
        try:
            memories, context = self.turn_service.recall(query, turn_id=call_id)
            diagnostics = (self.retriever.consume_diagnostics()
                           if hasattr(self.retriever, "consume_diagnostics")
                           else {"strategy": "keyword_v1", "warning_code": None})
            return MemorySupport(call_id, context, tuple(
                RetrievedTrace(str(memory.id), memory.content, tuple(
                    str(evidence.source_message_id)
                    for evidence in self.memory_store.list_evidence(memory.id)
                ))
                for memory in memories
            ), diagnostics["strategy"], diagnostics["warning_code"])
        finally:
            self.connection.rollback()  # 结束只读快照，不撤销先前已提交的 observe。

    def close(self) -> None:
        """只释放连接，不删除状态文件；可重复调用。"""
        if not self._closed:
            self.connection.close()
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("记忆方法已经关闭。")
