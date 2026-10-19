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
from longmemory.application.memory_runtime import MemoryRuntime
from longmemory.adapters.storage.sqlite_scenario_recall import SQLiteScenarioRecallProvider
from longmemory.adapters.storage.sqlite_natural_memory_commands import SQLiteNaturalMemoryCommandHandler
from longmemory.adapters.storage.sqlite_temporary_interaction import (
    SQLiteTemporaryInteractionProvider,
)
from longmemory.adapters.storage.sqlite_temporal_recall import (
    SQLiteTemporalRecallProvider,
)
from longmemory.core.common.identifiers import MemoryId
from longmemory.infrastructure.logging.setup import log_event
from longmemory.methods.factory import create_method
from longmemory.methods.contracts import MemoryMethod
from longmemory.methods.longmemory_v1.method import LongMemoryV1
from longmemory.methods.backend_contracts import BackendAssembly, StateResource


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


def build_memory_runtime(database_path: Path, *, clock=None) -> MemoryRuntime:
    """装配日常入口的默认记忆运行时，但不创建或迁移数据库。

    ``existing_only`` 保留此前网页入口的安全边界；跨网页/圆屏线程使用
    同一个常驻方法实例。具体实现选择位于装配层，而不泄漏进 Runtime。
    """

    method = LongMemoryV1(
        database_path,
        existing_only=True,
        allow_cross_thread=True,
    )
    return build_legacy_runtime(database_path, method=method, clock=clock,
                                include_personas=False)


def build_legacy_runtime(database_path: Path, *, method, include_personas=True,
                         clock=None, management=None, **extensions) -> MemoryRuntime:
    """只有显式旧适配器可装配 SQLite 派生能力，不按路径后缀猜测。"""
    from longmemory.methods.daily_llm.method import DailyLLMMemory
    from longmemory.adapters.storage.sqlite_persona_recall import SQLitePersonaRecallProvider
    from longmemory.entrypoints.api.method_management import LegacyMemoryAdministration
    from longmemory.entrypoints.api.memory_backend import MemoryBackend
    if not isinstance(method, (LongMemoryV1, DailyLLMMemory)):
        raise TypeError("非旧引擎必须使用 build_backend_runtime。")
    providers = {}
    try:
        providers["scenario_provider"] = SQLiteScenarioRecallProvider(database_path)
        providers["temporal_provider"] = SQLiteTemporalRecallProvider(database_path)
        providers["memory_command_handler"] = SQLiteNaturalMemoryCommandHandler(database_path)
        providers["temporary_interaction_provider"] = SQLiteTemporaryInteractionProvider(database_path)
        if include_personas:
            providers["persona_provider"] = SQLitePersonaRecallProvider(database_path)
        return MemoryRuntime(database_path, method=method, clock=clock,
            backend_assembly=BackendAssembly(method, (
                StateResource("legacy_state", database_path.resolve(), "file"),
            ), management=management or LegacyMemoryAdministration(MemoryBackend(database_path)),
                legacy_sqlite=True), **providers, **extensions)
    except BaseException:
        for provider in providers.values():
            close = getattr(provider, "close", None)
            if close:
                close()
        method.close()
        raise


def assemble_backend(*, method: MemoryMethod, resources: tuple[StateResource, ...],
                     source_path: Path, management=None, create_sources=False) -> BackendAssembly:
    """新后端显式接入点；不注册任意模块路径，不安装或切换日用引擎。

    method.observe 是完整 add/pipeline，平台不依赖其内部阶段；只有用户消息
    会投递给它。来源库独立新建/重开，不能与引擎资源重叠。
    """
    from longmemory.adapters.storage.sqlite_source_journal import SQLiteSourceJournal
    from longmemory.application.managed_memory import ManagedMemoryMethod
    source = source_path.resolve()
    try:
        import json
        for resource in resources:
            path = resource.path.resolve()
            if source == path or (resource.kind == "directory" and source.is_relative_to(path)):
                raise ValueError("source_and_engine_state_overlap")
        identity = json.dumps({"method": method.name, "version": method.implementation_version,
            "resources": sorted((item.name, str(item.path.resolve()), item.kind) for item in resources)}, sort_keys=True)
        journal = SQLiteSourceJournal(source, engine_name=identity, create=create_sources)
        managed = ManagedMemoryMethod(method, journal)
    except BaseException:
        method.close()
        raise
    return BackendAssembly(managed, resources + (
        StateResource("platform_sources", source, "file"),
    ), management=management)


def build_backend_runtime(assembly: BackendAssembly, *, clock=None) -> MemoryRuntime:
    """结构不同的新引擎不能继承旧 SQL 自然纠错/历史/画像等能力。"""
    if assembly.legacy_sqlite:
        raise ValueError("旧引擎应使用 build_legacy_runtime。")
    from longmemory.application.backend_commands import UnsupportedBackendCommands
    sources = next((item.path for item in assembly.resources if item.name == "platform_sources"), None)
    if sources is None:
        raise ValueError("platform_sources_required")
    return MemoryRuntime(sources, method=assembly.method, backend_assembly=assembly,
                         memory_command_handler=UnsupportedBackendCommands(assembly.method),
                         clock=clock)


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
