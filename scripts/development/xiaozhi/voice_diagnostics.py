"""Python 3.10 标准库语音观测桥；有界异步投递，绝不重试业务或保存正文。"""

from contextvars import ContextVar
import json
import hashlib
import hmac
import os
import queue
import re
import secrets
import threading
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener


CURRENT = ContextVar("voice_diagnostic_round", default=None)
ROUND_HEADER = "X-Voice-Round-Id"
EVENTS = frozenset({
    "asr_entered", "asr_handoff", "asr_failed", "chat_entered", "chat_returned",
    "memory_requested", "memory_response", "memory_failed", "model_requested",
    "model_output", "model_returned", "model_failed", "tts_requested", "tts_response",
    "tts_audio_ready", "tts_returned", "tts_failed", "tts_cancelled", "tts_fallback",
    "send_returned", "cancelled", "superseded", "chat_failed",
    "asr_timeout", "memory_timeout", "model_timeout", "tts_timeout",
    "tts_service_entered", "tts_service_returned", "tts_service_written", "tts_service_failed",
    "tts_service_disconnected", "tts_service_busy",
})
_queue = queue.Queue(maxsize=256)
_lock = threading.Lock()
_worker = None
_dropped = 0


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{24}", value) is not None


def _target():
    try:
        url = urlsplit(os.environ.get("LONGMEMORY_RUNTIME_URL", ""))
        token = os.environ.get("LONGMEMORY_RUNTIME_TOKEN", "")
        if (url.scheme != "http" or url.hostname != "127.0.0.1" or url.port is None
                or url.username or url.password or url.query or url.fragment
                or url.path != "/api/internal/memory/prepare"
                or re.fullmatch(r"[0-9a-f]{64}", token) is None):
            return None
        return url._replace(path="/api/internal/memory/voice-events").geturl(), token
    except (ValueError, TypeError):
        return None


def _deliver():
    global _dropped
    opener = build_opener(ProxyHandler({}), NoRedirect())
    while True:
        target, item = _queue.get()
        try:
            request = Request(target[0], data=json.dumps(item).encode("ascii"), method="POST",
                              headers={"Content-Type": "application/json", "Authorization": "Bearer " + target[1]})
            with opener.open(request, timeout=0.5) as response:
                response.read(1024)
        except Exception:
            _dropped += 1  # 固定计数；网络错误、正文、密钥永不进入日志。
        finally:
            _queue.task_done()


def emit(item):
    """观测丢失允许发生；业务线程不等待 HTTP，不自动重试。"""
    global _worker, _dropped
    try:
        target = _target()
        if target is None:
            return
        with _lock:
            if _worker is None:
                _worker = threading.Thread(target=_deliver, name="voice-observer", daemon=True)
                _worker.start()
        _queue.put_nowait((target, item))
    except Exception:
        _dropped += 1


def verified_round(headers):
    """证明本机受信包装器持有启动器凭据；不改变合成服务的业务认证。"""
    try:
        round_id = headers.get(ROUND_HEADER, "")
        proof = headers.get("X-Voice-Round-Proof", "")
        token = os.environ.get("LONGMEMORY_RUNTIME_TOKEN", "")
        if not valid_id(round_id) or re.fullmatch(r"[0-9a-f]{64}", token) is None:
            return None
        expected = hmac.new(token.encode("ascii"), ("voice-round-v1:" + round_id).encode("ascii"), hashlib.sha256).hexdigest()
        return round_id if hmac.compare_digest(proof, expected) else None
    except Exception:
        return None


class VoiceRound:
    def __init__(self, *, round_id=None, source="xiaozhi", request_id=None):
        self.round_id = round_id if valid_id(round_id) else secrets.token_hex(12)
        self.source = source if source in {"xiaozhi", "cosyvoice"} else "xiaozhi"
        self.request_id = request_id if valid_id(request_id) else None
        self.lock = threading.Lock()
        self.sequence = 0
        self.seen = set()

    def event(self, event, *, request_id=None):
        try:
            if event not in EVENTS:
                return
            request_id = request_id or self.request_id
            with self.lock:
                # 段落/音频包很多；每种事实每轮只投递首次，内存和日志均有界。
                key = (event, request_id if valid_id(request_id) else None)
                if key in self.seen or self.sequence >= 64:
                    return
                self.seen.add(key)
                self.sequence += 1
                item = {"round_id": self.round_id, "event": event, "sequence": self.sequence}
                if self.source == "cosyvoice":
                    item["source"] = "cosyvoice"
                if valid_id(request_id):
                    item["http_request_id"] = request_id
            emit(item)
        except Exception:
            pass

    def headers(self):
        result = {ROUND_HEADER: self.round_id}
        token = os.environ.get("LONGMEMORY_RUNTIME_TOKEN", "")
        if re.fullmatch(r"[0-9a-f]{64}", token):
            result["X-Voice-Round-Proof"] = hmac.new(token.encode("ascii"),
                ("voice-round-v1:" + self.round_id).encode("ascii"), hashlib.sha256).hexdigest()
        return result


def headers():
    trace = CURRENT.get()
    return trace.headers() if trace is not None else {}


def event(name, *, request_id=None):
    trace = CURRENT.get()
    if trace is not None:
        trace.event(name, request_id=request_id)


def for_sentence(connection, sentence_id):
    """仅查精确句子映射；绝不回退到连接的“最近一轮”。"""
    rounds = getattr(connection, "_longmemory_diagnostic_sentences", {})
    return rounds.get(sentence_id) if sentence_id is not None else None


class ContextExecutor:
    """只为当前连接 chat 提交复制上下文；保留同一线程池与 Future。"""
    def __init__(self, executor, connection):
        self.executor, self.connection = executor, connection

    def __getattr__(self, name):
        return getattr(self.executor, name)

    def submit(self, function, *args, **kwargs):
        from contextvars import copy_context
        if (getattr(function, "__self__", None) is self.connection
                and getattr(function, "__name__", None) == "chat"):
            return self.executor.submit(copy_context().run, function, *args, **kwargs)
        return self.executor.submit(function, *args, **kwargs)
