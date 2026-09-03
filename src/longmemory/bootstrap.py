"""装配 V0.1 长程记忆应用所需的具体实现。"""

from pathlib import Path
from contextlib import contextmanager
from sqlite3 import Connection

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.application.chat.contracts import AnswerGenerator
from longmemory.application.chat.dto import ChatResult
from longmemory.application.chat.service import ChatService
from longmemory.application.memory_management.dto import MemoryDetails
from longmemory.application.memory_management.service import (
    MemoryManagementService,
)
from longmemory.core.common.identifiers import MemoryId
from longmemory.infrastructure.logging.setup import log_event
from longmemory.methods.factory import create_method
from longmemory.methods.longmemory_v1.method import LongMemoryV1


def _legacy_method(database_path: Path, method_name: str) -> LongMemoryV1:
    """旧聊天/管理返回值仍使用 L1 DTO，本阶段仅兼容 longmemory_v1。

    通用实验调用直接使用 methods.factory；未来方法不能被强制转换成 L1。
    """
    if method_name != "longmemory_v1":
        raise ValueError("当前聊天兼容入口仅支持 longmemory_v1。")
    method = create_method(name=method_name, state_path=database_path)
    if not isinstance(method, LongMemoryV1):
        method.close()
        raise TypeError("旧入口的方法适配类型不匹配。")
    return method


@contextmanager
def open_memory_service(database_path: Path, *, method_name: str = "longmemory_v1"):
    """仅装配记忆能力；退出时关闭 SQLite，不创建/调用回答器。"""
    method = _legacy_method(database_path, method_name)
    try:
        yield method.turn_service
    finally:
        method.close()


class LongMemoryApplication:
    """对外暴露聊天和记忆管理能力，并管理资源生命周期。"""

    def __init__(
        self,
        *,
        chat_service: ChatService,
        memory_management_service: MemoryManagementService,
        connection: Connection,
        method: LongMemoryV1 | None = None,
    ) -> None:
        self._chat_service = chat_service
        self._memory_management_service = memory_management_service
        self._connection = connection
        self._method = method
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

        if self._method is not None:
            self._method.close()
        else:
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
    method_name: str = "longmemory_v1",
) -> LongMemoryApplication:
    """使用指定 SQLite 文件创建一个完整应用实例。

    默认使用确定性的 FakeAnswerGenerator，保证 V0.1 闭环
    在没有网络和 API Key 的环境中也能运行和测试。
    """

    method = _legacy_method(database_path, method_name)

    try:
        conversation_store = method.conversation_store
        memory_store = method.memory_store

        selected_answer_generator = (
            answer_generator
            if answer_generator is not None
            else FakeAnswerGenerator()
        )

        chat_service = ChatService(
            conversation_store=conversation_store,
            memory_store=memory_store,
            memory_extractor=method.extractor,
            memory_retriever=method.retriever,
            answer_generator=selected_answer_generator,
            audit_sink=log_event,
            memory_turn_service=method.turn_service,
        )

        memory_management_service = MemoryManagementService(
            memory_store=memory_store,
            conversation_store=conversation_store,
        )

        return LongMemoryApplication(
            chat_service=chat_service,
            memory_management_service=memory_management_service,
            connection=method.connection,
            method=method,
        )

    except BaseException:
        # 如果初始化过程中发生异常，确保已经打开的连接不会泄漏。
        method.close()
        raise
