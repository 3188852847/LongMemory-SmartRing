"""装配 Hy-Memory 引擎、来源账本和共享运行时。"""

from pathlib import Path
from longmemory.application.memory_runtime import MemoryRuntime
from longmemory.methods.backend_contracts import BackendAssembly, StateResource
from longmemory.methods.contracts import MemoryMethod


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


def build_backend_runtime(assembly: BackendAssembly, *, clock=None, state_identity=None) -> MemoryRuntime:
    """结构不同的新引擎不能继承旧 SQL 自然纠错/历史/画像等能力。"""
    from longmemory.application.backend_commands import UnsupportedBackendCommands
    from longmemory.adapters.storage.sqlite_platform_rounds import SQLitePlatformRounds
    sources = next((item.path for item in assembly.resources if item.name == "platform_sources"), None)
    if sources is None:
        raise ValueError("platform_sources_required")
    return MemoryRuntime(sources, method=assembly.method, backend_assembly=assembly,
                         memory_command_handler=UnsupportedBackendCommands(assembly.method),
                         round_screen_store=SQLitePlatformRounds(assembly.method.journal, clock=clock),
                         state_identity=state_identity,
                         clock=clock)


def build_hy_memory_runtime(*, settings, state_directory, source_path, create=False,
                            python=None, client_factory=None, clock=None,
                            expected_python_version=None, management_verification=None) -> MemoryRuntime:
    """通过指定的 SDK 解释器装配 Hy 引擎并绑定平台来源库。"""
    from longmemory.methods.hy_memory.assembly import assemble_hy_backend
    assembly = assemble_hy_backend(settings=settings, state_directory=state_directory,
        source_path=source_path, create=create, python=python, client_factory=client_factory,
        expected_python_version=expected_python_version, management_verification=management_verification)
    try:
        return build_backend_runtime(assembly, clock=clock, state_identity=settings.identity())
    except BaseException:
        assembly.method.close()
        raise
