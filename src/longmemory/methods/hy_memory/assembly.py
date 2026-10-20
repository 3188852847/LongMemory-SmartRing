"""Hy 的可信装配与新目录身份，不改中立协议或默认日用选择。"""

import json
import os
import hashlib
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from longmemory.methods.backend_contracts import StateResource, BackendAssembly
from .method import HyMemoryMethod, HyAdministration
from .process_client import HyProcessClient


def management_primitives_identity():
    from .sdk_bridge import SDK_VERSION
    directory = Path(__file__).parent
    digest = hashlib.sha256(SDK_VERSION.encode())
    # worker新增的内存包装也可影响管理RPC；证明不能只绑定import语句。
    for name in ("worker.py", "process_client.py", "management_rpc.py", "sdk_bridge.py",
                 "short_embedding_input.py", "sdk_observation.py", "observation.py", "layer_data.py", "semantic.py", "candidate_snapshot.py",
                 "method.py", "assembly.py", "provenance.py"):
        digest.update(name.encode())
        digest.update((directory / name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


class HyState:
    def __init__(self, root, settings, *, create):
        self.root = Path(root).resolve()
        self.marker = self.root / "hy-state.json"
        self.identity = settings.identity()
        self._lease = None
        if create:
            self.root.mkdir(parents=True, exist_ok=False)
            (self.root / "sdk").mkdir()
            self._write({"identity":self.identity, "status":"initializing", "files":[]})
        else:
            data = json.loads(self.marker.read_text(encoding="utf-8"))
            if data.get("identity") != self.identity or data.get("status") != "ready" or not data.get("files"):
                raise ValueError("hy_state_identity_or_readiness_mismatch")
            for name in data["files"]:
                path = self.root / name
                if not path.resolve().is_relative_to(self.root) or not path.is_file():
                    raise ValueError("hy_existing_state_incomplete")
        for path in self.root.rglob("*"):
            if path.is_symlink() or path.is_junction():
                raise ValueError("hy_state_links_not_allowed")

    def _write(self, data):
        temporary = self.marker.with_suffix(".tmp")
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(data, stream)
        temporary.replace(self.marker)

    def acquire(self):
        # 来源账本之外再锁引擎目录，防止另一个新账本指向同一活跃引擎。
        self._lease = (self.root / "engine.owner").open("a+b")
        try:
            self._lease.seek(0)
            if os.name == "nt":
                import msvcrt
                if self._lease.read(1) == b"":
                    self._lease.write(b"0")
                    self._lease.flush()
                self._lease.seek(0)
                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.release()
            raise

    def release(self):
        if self._lease is not None:
            self._lease.close()
            self._lease = None

    def ready(self):
        files = sorted(path.relative_to(self.root).as_posix() for path in (self.root / "sdk").rglob("*")
            if path.is_file() and not path.name.endswith(("-wal", "-shm", ".wal", ".tmp", ".lock")))
        # 启用后任务账本成为必需的持久资源；缺失不能悄悄重建为空并丢失
        # uncertain/已认领任务。首次从旧图关闭库启用时由worker建立，再封存。
        if (self.root / "semantic.sqlite3").is_file():
            files.append("semantic.sqlite3")
            files.sort()
        if (self.root / "provenance.sqlite3").is_file():
            files.append("provenance.sqlite3")
            files.sort()
        if not files:
            raise ValueError("hy_sdk_storage_not_initialized")
        self._write({"identity":self.identity, "status":"ready", "files":files})


class StateClient:
    def __init__(self, client, state):
        self.client, self.state = client, state
        try:
            state.ready()
        except BaseException:
            try: client.close()
            finally: state.release()
            raise

    def __getattr__(self, name):
        return getattr(self.client, name)

    def close(self):
        try:
            self.client.close()
            self.state.ready()
        finally:
            self.state.release()


def _source_storage_identity(engine, resources, source, *, create):
    """保留旧JSON的完整匹配；只选择已知等价绑定，不更新身份表。"""
    versions = engine.source_compatible_versions  # 先校验真实运行版本，未知实现不能借别名启动。
    def identity(version):
        return json.dumps({"method":engine.name, "version":version,
            "resources":sorted((item.name,str(item.path.resolve()),item.kind) for item in resources)},sort_keys=True)
    canonical = identity(engine.source_storage_version)
    if create or not source.is_file():
        return canonical
    # 只读不可变身份元数据；SQLiteSourceJournal取得原owner锁后还会独立
    # 严格比较一次。不读取对话、改写旧身份、迁移或创建任何表。
    with closing(sqlite3.connect(source.as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
        rows = db.execute("SELECT engine_name FROM source_journal_identity").fetchall()
    if len(rows)!=1 or rows[0][0] not in tuple(identity(version) for version in versions):
        raise ValueError("source_journal_engine_mismatch")
    return rows[0][0]


def _assemble_hy_sources(engine, resources, source, *, management, create):
    """Hy显式稳定存储绑定；中立ManagedMemory仍报告真实运行适配器版本。"""
    from longmemory.adapters.storage.sqlite_source_journal import SQLiteSourceJournal
    from longmemory.application.managed_memory import ManagedMemoryMethod
    journal = None
    try:
        identity = _source_storage_identity(engine,resources,source,create=create)
        journal = SQLiteSourceJournal(source,engine_name=identity,create=create)
        managed = ManagedMemoryMethod(engine,journal)
        return BackendAssembly(managed,resources+(StateResource("platform_sources",source,"file"),),management=management)
    except BaseException:
        try:
            engine.close()
        finally:
            if journal is not None:
                journal.close()
        raise


def assemble_hy_backend(*, settings, state_directory, source_path, create=False,
                        python=None, client_factory=None, create_sources=None,
                        expected_python_version=None, management_verification=None):
    root, source = Path(state_directory).resolve(), Path(source_path).resolve()
    if create_sources is None:
        create_sources = create
    if source == root or source.is_relative_to(root) or root.is_relative_to(source):
        raise ValueError("hy_source_state_overlap")
    if create_sources and source.exists():
        raise FileExistsError("hy_source_already_exists")
    if client_factory is None and (python is None or not Path(python).is_file()):
        raise FileNotFoundError("hy_dedicated_python_required")
    if management_verification is not None:
        proof = management_verification
        required = ({"protocol", "sdk_version", "rpc_source_sha256", "real_sdk_rpc_verified", "semantic_background_writes",
            "derivation_invalidation_verified", "read_only_intention_verified"} if settings.semantic_layers_enabled else
            {"sdk_version", "rpc_source_sha256", "real_sdk_rpc_verified", "semantic_background_writes_disabled"})
        policy_valid = (isinstance(proof, dict) and ((proof.get("protocol") == 2
            and proof.get("semantic_background_writes") == "managed_v1"
            and proof.get("derivation_invalidation_verified") is True and proof.get("read_only_intention_verified") is True)
            if settings.semantic_layers_enabled else proof.get("semantic_background_writes_disabled") is True))
        if (not isinstance(proof, dict) or set(proof) != required or proof["sdk_version"] != settings.sdk_version
                or proof["rpc_source_sha256"] != management_primitives_identity()
                or proof["real_sdk_rpc_verified"] is not True or not policy_valid):
            raise ValueError("hy_management_verification_identity_mismatch")
        # 仅可信装配接收本轮真实SDK验收回执。画像还须worker在首次空库
        # 建证、每次重开核对持久证明和外部owner锁；旧库不会补发证明。
        settings = replace(settings, management_writes_enabled=True, management_exclusive_profile=True)
    elif settings.semantic_layers_enabled:
        raise ValueError("hy_semantic_verified_contract_required")
    state = HyState(root, settings, create=create)
    def factory():
        state.acquire()
        try:
            client = (client_factory(root, create=create) if client_factory else
                      HyProcessClient(python=Path(python), workspace=root, settings=settings, create=create))
            return StateClient(client, state)
        except BaseException:
            state.release()
            raise
    engine = HyMemoryMethod(settings=settings, client_factory=factory)
    # 只记录可信标准装配声明，不探测worker、不将自定义factory当作标准SDK。
    engine._mechanism_profile = "standard_worker" if client_factory is None else None
    assembly = _assemble_hy_sources(engine, resources=(StateResource("hy_state",root,"directory"),),
        source=source, management=HyAdministration(engine), create=create_sources)
    try:
        assembly.method.wait_until_ready()
        if expected_python_version is not None:
            diagnostics = engine.sdk_call("diagnostics")
            if (diagnostics.get("sdk_python") != expected_python_version
                    or diagnostics.get("actual_sdk_version") != settings.sdk_version):
                raise ValueError("hy_runtime_version_identity_mismatch")
        if management_verification is not None:
            if state._lease is None or assembly.method.journal._lease is None:
                raise ValueError("hy_management_exclusive_ownership_missing")
            assembly.management.extension("workspace")
            # 只有RPC实际宣告该原语可用时才开受控串行门。delete不满足单条语义
            # 时继续为false，不能为让页面出现按钮而放宽SDK限制。
            protocol = assembly.management._protocol()
            if protocol.get("update") is True or protocol.get("delete") is True:
                assembly.management.serialized_writes = True
        return assembly
    except BaseException:
        assembly.method.close()
        raise
