"""受限 JSONL 子进程调用；SDK/Chroma 不进入主解释器环境。"""

from datetime import datetime
import json
import os
from pathlib import Path
import queue
import subprocess
import threading

from .sdk_bridge import HyResponseError


MAX_LINE = 2_000_000


def clean_environment(workspace: Path) -> dict:
    allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "SYSTEMDRIVE"}
    result = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    home = workspace / "home"
    temp = workspace / "temp"
    home.mkdir(exist_ok=True)
    temp.mkdir(exist_ok=True)
    result.update(HOME=str(home), USERPROFILE=str(home), TEMP=str(temp), TMP=str(temp),
        PYTHONIOENCODING="utf-8", PYTHON_DOTENV_DISABLED="1", ANONYMIZED_TELEMETRY="False",
        TOKENIZERS_PARALLELISM="false", MEMORY_DATA_DIR=str(workspace),
        MEMORY_LOG_DIR=str(workspace / "logs"), MEMORY_LOG_LEVEL="CRITICAL",
        MEMORY_SEARCH_DEDUP_ENABLED="false", MEMORY_RECALL_STRENGTH_ENABLED="false",
        MEMORY_RECALL_ACCESS_TRACKING="false", MEMORY_HISTORY_RECORD_SEARCHES="false",
        MEMORY_PIPELINE_TRACE_ENABLED="false", MEMORY_ENABLE_GRAPH="false",
        MEMORY_ENABLE_INTENTION="false", MEMORY_CODING_ENABLED="false", HY_MEMORY_READER="legacy")
    return result


class HyProcessClient:
    def __init__(self, *, python: Path, workspace: Path, settings, create: bool, command=None):
        workspace = workspace.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        source = Path(__file__).resolve().parents[3]
        script = "import sys; sys.path.insert(0," + repr(str(source)) + "); from longmemory.methods.hy_memory.worker import main; main()"
        argv = command if command is not None else [str(python.resolve()), "-I", "-X", "utf8", "-B", "-c", script]
        self.timeout = settings.timeout_seconds + 15
        self._lock = threading.RLock()
        self._counter = 0
        self._closed = False
        self._responses = queue.Queue()
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(argv, cwd=workspace, env=clean_environment(workspace),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1, creationflags=flags)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        try:
            self._rpc("initialize", settings=settings.wire(), workspace=str(workspace), create=create)
        except BaseException:
            self._stop()
            raise

    def _read(self):
        while True:
            line = self._process.stdout.readline(MAX_LINE + 1)
            self._responses.put(line)
            if not line or len(line) > MAX_LINE:
                break

    def _stop(self, *, graceful=False):
        self._closed = True
        if graceful and self._process.poll() is None:
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
        for stream in (self._process.stdin, self._process.stdout):
            if stream:
                stream.close()

    def _rpc(self, operation, **arguments):
        with self._lock:
            if self._closed:
                raise HyResponseError("hy_worker_closed")
            self._counter += 1
            request = {"id": self._counter, "operation": operation, "arguments": arguments}
            payload = json.dumps(request, ensure_ascii=False)
            if len(payload) > MAX_LINE:
                raise ValueError("hy_rpc_payload_too_large")
            try:
                self._process.stdin.write(payload + "\n")
                self._process.stdin.flush()
                line = self._responses.get(timeout=self.timeout)
                if not line or len(line) > MAX_LINE:
                    raise ValueError("response")
                response = json.loads(line)
                if (not isinstance(response, dict) or type(response.get("id")) is not int
                        or response["id"] != self._counter or type(response.get("ok")) is not bool
                        or (response["ok"] and "result" not in response)):
                    raise ValueError("response")
            except Exception:
                self._stop()
                raise HyResponseError("hy_worker_transport_failed_state_unknown") from None
            if response.get("ok") is not True:
                kind = response.get("error_type", "unknown")
                if not isinstance(kind, str) or not kind.isidentifier() or len(kind) > 60:
                    kind = "unknown"
                raise HyResponseError("hy_worker_operation_failed_" + kind + "_state_unknown")
            return response["result"]

    def add(self, data, **kwargs):
        value = kwargs.get("memory_at")
        if isinstance(value, datetime):
            kwargs["memory_at"] = value.isoformat()
        return self._rpc("add", data=data, **kwargs)

    def search(self, query, **kwargs):
        return self._rpc("search", query=query, **kwargs)

    def get_user_profile(self, **kwargs):
        return self._rpc("get_user_profile", **kwargs)

    def get(self, **kwargs):
        return self._rpc("get", **kwargs)

    def list_memories(self, **kwargs):
        return self._rpc("list_memories", **kwargs)

    def diagnostics(self):
        return self._rpc("diagnostics")

    def close(self):
        with self._lock:
            if not self._closed:
                try:
                    self._rpc("close")
                finally:
                    self._stop(graceful=True)
