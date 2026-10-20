"""受限 JSONL 子进程调用；SDK/Chroma 不进入主解释器环境。"""

from datetime import datetime
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
from time import perf_counter

from .sdk_bridge import HyResponseError
from .observation import CURRENT, measured


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
        MEMORY_EXISTING_TAGS_CACHE_TTL_SEC="0",
        MEMORY_PIPELINE_TRACE_ENABLED="false", MEMORY_ENABLE_GRAPH="false",
        MEMORY_ENABLE_INTENTION="false", MEMORY_CODING_ENABLED="false", HY_MEMORY_READER="legacy")
    # 归纳限定图式；不在后台把意图、治疗/画像推断转换成用户事实。
    for name in ("FORGET", "CANONICAL_STATE", "HOLISTIC_THERAPY", "PROFILE_FACT_PROMOTION", "BALANCED_CATALOG", "SPECIFIC_SUPPLEMENT"):
        result["MEMORY_EVOLING_" + name + "_ENABLED"] = "false"
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

    @measured('sdk_roundtrip_ms')
    def _rpc(self, operation, *, _read_only=False, **arguments):
        observation=CURRENT.get()
        lock_started=perf_counter() if observation is not None else None
        if not self._lock.acquire(blocking=not _read_only):
            from .layer_data import HyLayerDataBusy
            raise HyLayerDataBusy("hy_layer_data_busy")
        try:
            if observation is not None:
                observation.add('sdk_rpc_lock_ms',max(0,perf_counter()-lock_started)*1000)
            if self._closed:
                raise HyResponseError("hy_worker_closed")
            self._counter += 1
            request = {"id": self._counter, "operation": operation, "arguments": arguments}
            if observation is not None:
                request['observation_id']=observation.trace_id
            payload = json.dumps(request, ensure_ascii=False)
            if len(payload) > MAX_LINE:
                raise ValueError("hy_rpc_payload_too_large")
            try:
                self._process.stdin.write(payload + "\n")
                self._process.stdin.flush()
                line = self._responses.get(timeout=5 if _read_only else self.timeout)
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
            if observation is not None:
                observation.merge(response.get('observation'))
            if response.get("ok") is not True:
                kind = response.get("error_type", "unknown")
                if not isinstance(kind, str) or not kind.isidentifier() or len(kind) > 60:
                    kind = "unknown"
                raise HyResponseError("hy_worker_operation_failed_" + kind + "_state_unknown")
            return response["result"]
        finally:
            self._lock.release()

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

    def semantic_status(self):
        return self._rpc("semantic_status", _read_only=True)

    def semantic_task(self, *, task_id):
        return self._rpc("semantic_task", _read_only=True, task_id=task_id)

    def semantic_enqueue(self, *, task_id, kind="evolve", max_batches=1):
        return self._rpc("semantic_enqueue", task_id=task_id, kind=kind, max_batches=max_batches)

    def semantic_cancel(self, *, task_id):
        return self._rpc("semantic_cancel", task_id=task_id)

    def semantic_pause(self, *, paused):
        return self._rpc("semantic_pause", paused=paused)

    def candidate_snapshot(self, *, query_embedding, limit=5):
        return self._rpc("candidate_snapshot", _read_only=True, query_embedding=query_embedding, limit=limit)

    def candidate_validate(self, *, snapshot_token):
        return self._rpc("candidate_validate", _read_only=True, snapshot_token=snapshot_token)

    def layer_page(self, *, layer, limit=20, offset=0, state="all"):
        return self._rpc("layer_page", _read_only=True, layer=layer, limit=limit, offset=offset, state=state)

    def layer_detail(self, *, layer, item_id):
        return self._rpc("layer_detail", _read_only=True, layer=layer, item_id=item_id)

    def management_capabilities(self):
        return self._rpc("management_capabilities")

    def history(self, *, memory_id):
        return self._rpc("history", memory_id=memory_id)

    def update(self, *, memory_id, content):
        return self._rpc("update", memory_id=memory_id, content=content)

    def delete(self, *, memory_id):
        return self._rpc("delete", memory_id=memory_id)

    def close(self):
        with self._lock:
            if not self._closed:
                try:
                    self._rpc("close")
                finally:
                    self._stop(graceful=True)
