"""D1 首个消融条件：只换提取，存储、精确去重和检索沿用 v1。"""

from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from longmemory.adapters.storage.sqlite_conversation_store import SQLiteConversationStore
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.application.memory_turn import MemoryTurnService
from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.core.memory.extraction.candidates import CandidateExtractionService
from longmemory.core.memory.l1_atomic.models import AtomicMemory, CURRENT_USER_SUBJECT_ID
from longmemory.methods.contracts import ObservationResult, UnsupportedCapabilityError, WriteTrace
from longmemory.methods.longmemory_v1.method import LongMemoryV1

METHOD_NAME = "longmemory_llm_extract_v2"


class _CountedProducer:
    """记录请求尝试数，包含失败；不是供应商 token 或计费统计。"""

    def __init__(self, producer):
        self.producer, self.calls = producer, 0

    def propose(self, *, source_text):
        self.calls += 1
        return self.producer.propose(source_text=source_text)


class _PreparedExtractor:
    def __init__(self, message, memories):
        self.message, self.memories = message, memories

    def extract(self, message):
        # 写事务内只能消费已校验的同一消息候选；这里绝不调用网络。
        if message != self.message:
            raise ValueError("候选与待写入消息不匹配。")
        return self.memories


class LongMemoryLLMExtract:
    name = METHOD_NAME
    implementation_version = "2"
    capabilities = LongMemoryV1.capabilities

    def __init__(self, database_path: Path, *, producer=None, read_only=False):
        self._read_only = read_only
        self._records = []
        if read_only:
            if producer is not None:
                raise ValueError("冻结实例不接受候选生成器。")
        elif producer is None or database_path.exists():
            # 初版仅用于新建实验；拒绝把个人库或旧基线库当作新方法状态。
            raise ValueError("构建新提取方法需要生成器和全新数据库路径。")
        self._base = LongMemoryV1(database_path, existing_only=read_only, read_only=read_only)
        try:
            if read_only:
                marker = self._base.connection.execute("SELECT method FROM extraction_identity").fetchall()
                if len(marker) != 1 or marker[0][0] != METHOD_NAME:
                    raise ValueError("不是已知的新提取方法状态。")
            else:
                # 只在新实验库增加审计表，不更改通用 V3 schema 或个人库。
                self._base.connection.executescript("""
                    CREATE TABLE extraction_identity (method TEXT NOT NULL);
                    CREATE TABLE extraction_batches (
                        source_message_id TEXT PRIMARY KEY REFERENCES conversation_messages(id),
                        proposal_json TEXT NOT NULL
                    );
                """)
                self._base.connection.execute("INSERT INTO extraction_identity VALUES (?)", (METHOD_NAME,))
                self._base.connection.commit()
            self._producer = _CountedProducer(producer) if producer is not None else None
            self._extractor = CandidateExtractionService(self._producer) if self._producer else None
        except BaseException:
            self._base.close()
            raise

    def observe(self, event):
        self._base._ensure_open()
        if self._read_only:
            raise RuntimeError("冻结方法禁止写入。")
        if event.session_id is not None:
            raise UnsupportedCapabilityError("实验 L1 不使用会话；会话由平台档案保留。")
        message = ConversationMessage(MessageId(event.event_id), MessageRole(event.role), event.content, event.occurred_at)
        if self._base.conversation_store.get(message.id) is not None:
            raise ValueError("同一历史事件不得重复提取或写入。")
        record = {"source_event_id": event.event_id, "status": "running", "phase": "extraction"}
        self._records.append(record)
        start, calls_before = perf_counter(), self._producer.calls
        try:
            # 关键顺序：先网络提取/整批校验，再开启 SQLite 写事务。
            proposal = self._extractor.extract(message)
            record.update(extraction_ms=round((perf_counter() - start) * 1000, 3), proposal=asdict(proposal))
            record["phase"] = "persistence"
            recorded_at = datetime.now(UTC)
            memories = tuple(AtomicMemory(MemoryId(str(uuid4())), CURRENT_USER_SUBJECT_ID,
                                          candidate.content, recorded_at) for candidate in proposal.candidates)
            turn = MemoryTurnService(
                conversation_store=SQLiteConversationStore(self._base.connection, commit_changes=False),
                memory_store=SQLiteMemoryStore(self._base.connection, commit_changes=False),
                memory_extractor=_PreparedExtractor(message, memories),
                memory_retriever=self._base.retriever,
            )
            with self._base._write_transaction():
                operations = turn.observe(message)
                self._base.connection.execute("INSERT INTO extraction_batches VALUES (?, ?)",
                                              (event.event_id, json.dumps(asdict(proposal), ensure_ascii=False)))
            record.update(status="completed", phase="completed")
            return ObservationResult(event.event_id, tuple(
                WriteTrace(op.operation.value, str(op.memory.id), (event.event_id,)) for op in operations))
        except KeyboardInterrupt:
            record.update(status="interrupted", error="user_interrupted")
            raise
        except Exception:
            record.update(status="failed", error=record["phase"] + "_failed")
            raise
        finally:
            record.update(request_attempts=self._producer.calls - calls_before,
                          duration_ms=round((perf_counter() - start) * 1000, 3))

    def build_diagnostics(self):
        # 失败响应正文不记录；只有通过结构校验的候选/摘录出现在审计中。
        return {"request_attempts": self._producer.calls if self._producer else 0,
                "token_usage": None, "events": self._records}

    def recall(self, query):
        return self._base.recall(query)

    def wait_until_ready(self):
        self._base.wait_until_ready()

    def close(self):
        self._base.close()
