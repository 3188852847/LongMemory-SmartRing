"""装配 V0.1 长程记忆应用所需的具体实现。"""

from pathlib import Path
from sqlite3 import Connection

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.adapters.storage.sqlite_conversation_store import (
    SQLiteConversationStore,
)
from longmemory.adapters.storage.sqlite_memory_store import (
    SQLiteMemoryStore,
)
from longmemory.application.chat.contracts import AnswerGenerator
from longmemory.application.chat.dto import ChatResult
from longmemory.application.chat.service import ChatService
from longmemory.application.memory_management.dto import MemoryDetails
from longmemory.application.memory_management.service import (
    MemoryManagementService,
)
from longmemory.core.common.identifiers import MemoryId
from longmemory.core.memory.extraction.service import (
    MemoryExtractionService,
)
from longmemory.core.memory.retrieval.service import (
    KeywordMemoryRetriever,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


class LongMemoryApplication:
    """对外暴露聊天和记忆管理能力，并管理资源生命周期。"""

    def __init__(
        self,
        *,
        chat_service: ChatService,
        memory_management_service: MemoryManagementService,
        connection: Connection,
    ) -> None:
        self._chat_service = chat_service
        self._memory_management_service = memory_management_service
        self._connection = connection
        self._closed = False

    def chat(self, text: str) -> ChatResult:
        """处理一条用户输入。"""

        self._ensure_open()
        return self._chat_service.chat(text)

    def list_memories(self) -> tuple[MemoryDetails, ...]:
        """列出全部 L1 记忆及其 L0 来源。"""

        self._ensure_open()
        return self._memory_management_service.list_memories()

    def get_memory(
        self,
        memory_id: MemoryId,
    ) -> MemoryDetails | None:
        """查看指定 L1 记忆及其 L0 来源。"""

        self._ensure_open()
        return self._memory_management_service.get_memory(memory_id)

    def delete_memory(self, memory_id: MemoryId) -> bool:
        """删除指定 L1 记忆，但保留 L0 原始来源。"""

        self._ensure_open()
        return self._memory_management_service.delete_memory(memory_id)

    def close(self) -> None:
        """关闭数据库连接。

        close() 可以安全地重复调用，避免清理阶段因为重复关闭
        掩盖真正的测试或业务错误。
        """

        if self._closed:
            return

        self._connection.close()
        self._closed = True

    def _ensure_open(self) -> None:
        """阻止关闭后的应用继续访问数据库。"""

        if self._closed:
            raise RuntimeError("应用已经关闭，不能继续执行操作。")


def build_application(
    *,
    database_path: Path,
    answer_generator: AnswerGenerator | None = None,
) -> LongMemoryApplication:
    """使用指定 SQLite 文件创建一个完整应用实例。

    默认使用确定性的 FakeAnswerGenerator，保证 V0.1 闭环
    在没有网络和 API Key 的环境中也能运行和测试。
    """

    connection = open_database(database_path)

    try:
        initialize_schema(connection)

        conversation_store = SQLiteConversationStore(connection)
        memory_store = SQLiteMemoryStore(connection)

        memory_extractor = MemoryExtractionService()
        memory_retriever = KeywordMemoryRetriever(memory_store)

        selected_answer_generator = (
            answer_generator
            if answer_generator is not None
            else FakeAnswerGenerator()
        )

        chat_service = ChatService(
            conversation_store=conversation_store,
            memory_store=memory_store,
            memory_extractor=memory_extractor,
            memory_retriever=memory_retriever,
            answer_generator=selected_answer_generator,
        )

        memory_management_service = MemoryManagementService(
            memory_store=memory_store,
            conversation_store=conversation_store,
        )

        return LongMemoryApplication(
            chat_service=chat_service,
            memory_management_service=memory_management_service,
            connection=connection,
        )

    except BaseException:
        # 如果初始化过程中发生异常，确保已经打开的连接不会泄漏。
        connection.close()
        raise