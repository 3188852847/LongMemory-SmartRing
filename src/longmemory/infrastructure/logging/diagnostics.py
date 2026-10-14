"""有界、安全的运行摘要；不读取日志正文，也不把异常文本当作诊断字段。"""

from collections import OrderedDict
from copy import deepcopy
from contextvars import ContextVar
from datetime import UTC, datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import stat
import threading
import time


REQUEST_CONTEXT = ContextVar("longmemory_request_context", default=None)
STAGES = {
    "user_saved": "storage", "extraction_done": "extraction",
    "extraction_failed": "extraction", "memory_write": "storage",
    "memory_retrieved": "retrieval", "context_built": "context",
    "answer_failed": "model", "assistant_saved": "storage",
}
MAX_BYTES = 1024 * 1024
BACKUPS = 2
OPERATIONS = {"console", "chat", "device", "memory", "memory_runtime", "diagnostics"}
CODES = {"pending", "ok", "accepted", "server_error", "request_rejected", "response_unobserved",
         "bridge_not_configured", "bridge_unavailable", "bridge_timeout", "bridge_auth_failed",
         "bridge_invalid_response", "console_internal_error", "console_timeout", "device_offline"}


class SafeRotatingHandler(RotatingFileHandler):
    def handleError(self, record):
        # 标准 logging 会吞掉写入错误，甚至写 stderr。让所有者降级为“观测不可用”。
        raise OSError("diagnostic_write_failed") from None


class Diagnostics:
    """每个进程独占自己的轮转文件；当前状态只在内存中保留 100 个请求。

    不聚合历史日志，重启后摘要为空。跨进程仅依赖显式传递的协议标识，
    不通过猜测时间邻近来关联对话。root=None 用于完全离线的测试。
    """

    def __init__(self, root: Path | None = None, *, capacity=100):
        self.root = Path(root).resolve() if root is not None else None
        self.capacity = capacity
        self.rows = OrderedDict()
        self.started = {}
        self.lock = threading.RLock()
        self.handler = None
        self.write_failed = False
        self.owner = secrets.token_hex(8)
        if self.root is not None:
            path = self.root / "data/logs/diagnostics" / f"api-{os.getpid()}-{self.owner}.jsonl"
            try:
                if not path.resolve().is_relative_to(self.root):
                    raise OSError("diagnostic_path_outside_root")
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.resolve().is_relative_to(self.root):
                    raise OSError("diagnostic_path_outside_root")
                self.handler = SafeRotatingHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
                self.handler.setFormatter(logging.Formatter("%(message)s"))
            except OSError:
                self.write_failed = True

    def begin(self, operation, *, mutating=False):
        if operation not in OPERATIONS:
            operation = "console"
        request_id = secrets.token_hex(12)
        started = time.monotonic()
        with self.lock:
            self.rows[request_id] = {
                "request_id": request_id, "time": datetime.now(UTC).isoformat(),
                "operation": operation, "stage": "request", "outcome": "processing",
                "code": "pending", "duration_ms": 0,
                "stages": [],
            }
            self.started[request_id] = started
            while len(self.rows) > self.capacity:
                dropped, _ = self.rows.popitem(last=False)
                self.started.pop(dropped, None)
        return request_id, started, mutating

    def stage(self, request_id, event):
        # 白名单事件来自记忆核心；不把 turn 原文、memory IDs 或 warning 正文搬到网页。
        if event not in STAGES:
            return
        with self.lock:
            row = self.rows.get(request_id)
            if row:
                row["stage"] = STAGES[event]
                if len(row["stages"]) < 16:
                    row["stages"].append({"stage": STAGES[event], "event": event,
                                          "at_ms": max(0, round((time.monotonic() - self.started[request_id]) * 1000))})

    def finish(self, trace, status, *, code=None):
        request_id, started, mutating = trace
        with self.lock:
            row = self.rows.get(request_id)
            if row is None:
                return
            row.update(status=status, duration_ms=max(0, round((time.monotonic() - started) * 1000)))
            # 错误响应无法证明写操作未执行；成功响应也不证明设备播放或异步任务结束。
            row["outcome"] = ("unknown" if mutating else "failed") if status >= 500 or code == "response_unobserved" else (
                "failed" if status >= 400 else "accepted" if mutating else "succeeded")
            row["code"] = code if code in CODES else ("server_error" if status >= 500 else
                "request_rejected" if status >= 400 else "accepted" if mutating else "ok")
            if self.handler:
                # 直接使用私有 handler，不替换 root/logger；轮转失败只影响观测。
                try:
                    self.handler.acquire()
                    try:
                        record = logging.LogRecord("longmemory.diagnostics", logging.INFO, "", 0,
                                                   json.dumps(row, ensure_ascii=False), (), None)
                        if self.handler.shouldRollover(record):
                            self.handler.doRollover()
                        logging.FileHandler.emit(self.handler, record)
                    finally:
                        self.handler.release()
                except OSError:
                    self.write_failed = True

    def snapshot(self):
        with self.lock:
            requests = [deepcopy(row) for row in reversed(self.rows.values())]
            for row in requests:
                if row["outcome"] == "processing":
                    row["duration_ms"] = max(0, round((time.monotonic() - self.started[row["request_id"]]) * 1000))
            return {"schema_version": 1, "scope": "current_process", "capacity": self.capacity,
                    "persistence": "unavailable" if self.write_failed else "enabled" if self.handler else "disabled",
                    "requests": requests,
                    "device_playback": "unconfirmed",
                    "coverage": ["http_request", "memory_audit_context"],
                    "uncovered": ["asr", "tts", "device_playback", "background_completion"]}

    def close(self):
        if self.handler:
            self.handler.close()


def log_inventory(root: Path | None):
    """仅 stat 固定路径，拒绝链接逃逸；不打开任何正文，不返回绝对路径。"""
    specs = (
        ("launcher", "data/logs/launcher-events.jsonl", "launcher_singleton", "bounded_1MiB_2_backups"),
        ("memory", "data/logs/xiaozhi-demo-v1.jsonl", "memory_audit", "bounded_1MiB_2_backups"),
        ("xiaozhi", "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/tmp/server.log", "vendor", "vendor_managed"),
    )
    result = []
    for name, relative, owner, retention in specs:
        row = {"id": name, "owner": owner, "retention": retention, "state": "unconfigured", "bytes": None}
        if root is not None:
            base = Path(root).resolve()
            path = base / relative
            try:
                if not path.resolve().is_relative_to(base):
                    row["state"] = "outside_root"
                else:
                    metadata = path.stat()
                    if stat.S_ISREG(metadata.st_mode):
                        row.update(state="present", bytes=metadata.st_size)
                    else:
                        row["state"] = "not_a_file"
            except FileNotFoundError:
                row["state"] = "missing"
            except OSError:
                row["state"] = "unavailable"
        result.append(row)
    return result
