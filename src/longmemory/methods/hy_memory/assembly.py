"""Hy 的可信装配与新目录身份，不改中立协议或默认日用选择。"""

import json
import os
from pathlib import Path

from longmemory.methods.backend_contracts import StateResource
from .method import HyMemoryMethod, HyAdministration
from .process_client import HyProcessClient


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
            if path.is_file() and not path.name.endswith(("-wal", "-shm", ".tmp", ".lock")))
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


def assemble_hy_backend(*, settings, state_directory, source_path, create=False,
                        python=None, client_factory=None, create_sources=None):
    from longmemory.bootstrap import assemble_backend
    root, source = Path(state_directory).resolve(), Path(source_path).resolve()
    if create_sources is None:
        create_sources = create
    if source == root or source.is_relative_to(root) or root.is_relative_to(source):
        raise ValueError("hy_source_state_overlap")
    if create_sources and source.exists():
        raise FileExistsError("hy_source_already_exists")
    if client_factory is None and (python is None or not Path(python).is_file()):
        raise FileNotFoundError("hy_dedicated_python_required")
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
    assembly = assemble_backend(method=engine, resources=(StateResource("hy_state", root, "directory"),),
        source_path=source, management=HyAdministration(engine), create_sources=create_sources)
    try:
        assembly.method.wait_until_ready()
        return assembly
    except BaseException:
        assembly.method.close()
        raise
