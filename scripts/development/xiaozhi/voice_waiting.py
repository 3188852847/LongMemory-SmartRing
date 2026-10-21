"""同声线等待反馈与真实答案分开计时；只管理语音进程内的一轮临时状态。"""

from pathlib import Path
import struct
import threading
import time
import hashlib
import json
import os
from uuid import uuid4

ASSET_ROOT = Path(__file__).resolve().parents[3] / "assets/audio/voice-waiting/cosyvoice3"
PHRASES = {"model": "稍等。", "web": "稍等。"}
CACHE_ROOT = Path(__file__).resolve().parents[3] / "local/runtime/voice-waiting/cosyvoice3"
WAITING_DELAY_SECONDS = 3.0
WAITING_COOLDOWN_SECONDS = 90.0
_BUDGET_LOCK = threading.Lock()


class _CueBudget:
    """连接内仅在提示首包真实发送返回后计冷却；预留不是消费。"""
    def __init__(self):
        self.lock = threading.RLock()
        self.last_sent_at = self.last_token = self.inflight = None

    def eligible(self, state):
        with self.lock:
            if self.last_token is state.cue_token:
                return True  # 同一次提示的尾帧，不再次消耗名额。
            return ((self.inflight is None or self.inflight is state.cue_token) and (self.last_sent_at is None
                or time.perf_counter() - self.last_sent_at >= WAITING_COOLDOWN_SECONDS))

    def claim(self, state):
        with self.lock:
            if self.last_token is state.cue_token:
                return True
            if self.inflight is not None or not self.eligible(state):
                return False
            self.inflight = state.cue_token
            return True

    def commit(self, state, sent_at):
        with self.lock:
            if self.last_sent_at is None or sent_at >= self.last_sent_at:
                self.last_sent_at, self.last_token = sent_at, state.cue_token
            if self.inflight is state.cue_token:
                self.inflight = None

    def release(self, state):
        with self.lock:
            if self.inflight is state.cue_token:
                self.inflight = None


def _cue_budget(connection):
    with _BUDGET_LOCK:
        value = getattr(connection, "_longmemory_waiting_budget", None)
        if value is None:
            value = _CueBudget()
            connection._longmemory_waiting_budget = value
        return value


def _voice_context():
    from cosyvoice_profiles import waiting_context
    return waiting_context()


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def decode_packets(data):
    if not isinstance(data, bytes) or len(data) > 128 * 1024 or data[:8] != b"LMWAIT01":
        return ()
    offset, packets = 8, []
    while offset + 2 <= len(data):
        size = struct.unpack_from("!H", data, offset)[0]
        offset += 2
        if not 0 < size <= 4096 or offset + size > len(data):
            return ()
        packets.append(data[offset:offset + size])
        offset += size
    return tuple(packets) if offset == len(data) and 1 <= len(packets) <= 35 else ()


def _cache_identity(identity):
    if not isinstance(identity, str) or len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
        raise ValueError('waiting_identity_invalid')
    return identity


def _manifest(identity, blobs):
    from cosyvoice_profiles import WAITING_ENGINE
    return {'version': 1, 'voice_identity': identity, 'engine': WAITING_ENGINE,
        'codec': 'opus-mono-60ms', 'items': {name: {'sha256': _digest(blob), 'bytes': len(blob),
            'phrase_sha256': _digest(PHRASES[name.split('-')[0]].encode())} for name, blob in blobs.items()}}


def _directory(root, identity):
    # 中文深工作树下保留短物理路径；完整身份/摘要仍在清单中核验，冲突拒绝。
    root = Path(root)
    if root.is_symlink() or root.resolve() != root.absolute():
        raise ValueError('waiting_cache_path_invalid')
    return root / _cache_identity(identity)[:16]


def _blob_name(name, digest):
    return name[0] + name.split('-')[1][:2] + '-' + digest[:16] + '.opf'


def publish_cache(root, identity, blobs):
    """只在显式维护准备中发布完整缓存；运行中加载绝不创建/修补文件。"""
    directory = _directory(root, identity)
    expected = {f'{kind}-{rate}' for kind in PHRASES for rate in (16000, 24000)}
    if set(blobs) != expected or any(not decode_packets(blob) for blob in blobs.values()):
        raise ValueError('waiting_cache_incomplete')
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink() or directory.resolve() != directory.absolute():
        raise ValueError('waiting_cache_path_invalid')
    existing = directory / 'manifest.json'
    if existing.exists():
        if existing.is_symlink() or existing.stat().st_size > 8192:
            raise ValueError('waiting_cache_existing_identity_invalid')
        old = json.loads(existing.read_text(encoding='utf-8'))
        if not isinstance(old, dict) or old.get('voice_identity') != identity:
            raise ValueError('waiting_cache_existing_identity_invalid')
    manifest = _manifest(identity, blobs)
    for name, blob in blobs.items():
        target = directory / _blob_name(name, _digest(blob))
        if target.exists():
            if target.is_symlink() or target.stat().st_size != len(blob) or target.read_bytes() != blob:
                raise ValueError('waiting_cache_existing_blob_invalid')
            continue
        temporary = directory / ('.' + uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(blob); stream.flush(); os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    temporary = directory / ('.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, sort_keys=True); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(directory / 'manifest.json')  # 只有整套声线一致的资产才可见。
    finally:
        temporary.unlink(missing_ok=True)


def cached_packets(root, identity, kind, sample_rate):
    try:
        directory = _directory(root, identity)
        path = directory / 'manifest.json'
        if (directory.is_symlink() or directory.resolve() != directory.absolute()
                or path.is_symlink() or path.stat().st_size > 8192):
            return ()
        manifest = json.loads(path.read_text(encoding='utf-8'))
        from cosyvoice_profiles import WAITING_ENGINE
        if (not isinstance(manifest, dict) or set(manifest) != {'version','voice_identity','engine','codec','items'}
                or type(manifest.get('version')) is not int or manifest['version'] != 1
                or not isinstance(manifest['items'], dict)
                or set(manifest['items']) != {f'{k}-{r}' for k in PHRASES for r in (16000,24000)}
                or manifest.get('voice_identity') != identity
                or manifest.get('engine') != WAITING_ENGINE or manifest.get('codec') != 'opus-mono-60ms'):
            return ()
        name = f'{kind}-{sample_rate}'
        item = manifest['items'][name]
        if not isinstance(item, dict) or set(item) != {'sha256','bytes','phrase_sha256'} or type(item['bytes']) is not int:
            return ()
        digest = _cache_identity(item['sha256'])
        path = directory / _blob_name(name, digest)
        if (item['phrase_sha256'] != _digest(PHRASES[kind].encode()) or path.is_symlink()
                or not 0 < item['bytes'] <= 128 * 1024 or path.stat().st_size != item['bytes']):
            return ()
        data = path.read_bytes()
        return decode_packets(data) if _digest(data) == digest else ()
    except (OSError, ValueError, KeyError, TypeError):
        return ()


class WaitingPacket(bytes):
    def __new__(cls, value, state):
        packet = super().__new__(cls, value)
        packet.state = state
        answer = issubclass(cls, AnswerPacket)
        packet._longmemory_cosy_cancelled = lambda: (not state.current()
            or (not answer and (state.answer_ready or not state.cue_current() or not state.budget.eligible(state))))
        packet._longmemory_send_receipt = _SendReceipt(state, answer)
        return packet


class AnswerPacket(WaitingPacket):
    """真正回答的包也绑定话轮，不能把提示或停止提示音算作答案首包。"""


class _SendReceipt:
    """一包一个进程内事实标记，由真实socket.send成功返回确认，不使用共享计数推断。"""
    def __init__(self, state, answer):
        self.state, self.answer = state, answer
        self.sent_at = None
        self.lock = threading.Lock()

    def confirm(self):
        with self.lock:
            if self.sent_at is not None:
                return
            self.sent_at = time.perf_counter()
        state = self.state
        with state.lock:
            elapsed = round((self.sent_at - state.started) * 1000)
            if self.answer:
                if state.first_answer_ms is None:
                    state.first_answer_ms = elapsed
                    tracker = getattr(state.connection, "_longmemory_voice_latency", None)
                    if tracker is not None:
                        tracker.mark("first_audio_sent_ms", sentence_id=state.sentence_id)
            elif state.first_feedback_ms is None:
                # 已发送事实不能因返回瞬间取消而撤回；后续新轮仍须遵守冷却。
                state.first_feedback_ms = elapsed
                state.cue_state = "sent"
                state.budget.commit(state, self.sent_at)


def record_packet_sent(packet):
    """仅供实际传输边界或合成传输替身调用；不改变音频字节。"""
    receipt = getattr(packet, "_longmemory_send_receipt", None)
    if receipt is not None:
        receipt.confirm()


def load_packets(kind, sample_rate):
    """两场景共用当前文案/声线缓存；旧内置素材无文案清单，不能回退。"""
    if kind not in PHRASES or sample_rate not in (16000, 24000):
        return ()
    context = _voice_context()
    if context is None:
        return ()
    return cached_packets(CACHE_ROOT, context['identity'], kind, sample_rate)


class WaitingTurn:
    def __init__(self, connection, kind, *, delay=WAITING_DELAY_SECONDS, packets=None):
        self.connection, self.kind = connection, kind
        self.sentence_id = connection.sentence_id
        current = getattr(getattr(connection, "_longmemory_voice_latency", None), "current", None)
        self.started = current["started"] if current else time.perf_counter()
        self.cue_deadline = self.started + delay
        self.cue_token = object()
        self.budget = _cue_budget(connection)
        self.status = "querying" if kind == "web" else "answering"
        self.query_ms = None
        self.first_feedback_ms = None
        self.first_answer_ms = None
        self.answer_ready = False
        self.closed = False
        self.cue_state = "pending"
        self.lock = threading.RLock()
        context = _voice_context() if packets is None else None
        self.voice_identity = context['identity'] if context else None
        self.profile_bound = packets is None
        self.packets = load_packets(kind, connection.sample_rate) if packets is None else packets
        self.timer = threading.Timer(max(0, self.cue_deadline - time.perf_counter()), self.enqueue)
        self.timer.daemon = True

    def current(self):
        return (not self.closed and not self.connection.stop_event.is_set()
                and not self.connection.client_abort
                and self.sentence_id == self.connection.sentence_id
                and getattr(self.connection, "_longmemory_waiting", None) is self)

    def cancel(self):
        with self.lock:
            self.closed = True
            self.timer.cancel()
            self.budget.release(self)
            if self.first_feedback_ms is None:
                self.cue_state = "skipped"

    def cue_current(self):
        if not self.profile_bound:
            return True  # 仅用于显式合成 fixture 包。
        context = _voice_context()
        return context is not None and context['identity'] == self.voice_identity

    def enqueue(self):
        with self.lock:
            return self._enqueue_once()

    def _enqueue_once(self):
        if self.cue_state != 'pending':
            return
        if time.perf_counter() < self.cue_deadline:
            return
        if not self.current() or self.answer_ready:
            self.cue_state = "skipped"
            return
        if not self.budget.eligible(self):
            self.cue_state = "skipped"
            return
        if not self.packets or not self.cue_current():
            self.cue_state = "unavailable"
            return
        from core.providers.tts.dto.dto import SentenceType
        # 不写入文本切段队列，不调用模型、不争用共享 Opus 编码器，也不发送 LAST。
        # 字幕留给真正答案，避免取消后仍展示“正在查”的迟到字幕。
        self.cue_state = "queued"
        # 整句一次入队，防止后台答案恰好插入两帧提示之间。
        self.connection.tts.tts_audio_queue.put(
            (SentenceType.MIDDLE, [WaitingPacket(packet, self) for packet in self.packets],
             None, self.sentence_id))

    def snapshot(self):
        with self.lock:
            return {"version": 1, "kind": self.kind, "status": self.status,
                    "cue_state": self.cue_state, "query_ms": self.query_ms,
                    "first_feedback_ms": self.first_feedback_ms, "first_answer_ms": self.first_answer_ms}


def begin_waiting(connection, dialogue):
    if not getattr(connection, "_longmemory_waiting_enabled", False):
        return dialogue
    from fast_voice_responses import _uses_cosyvoice3
    if not _uses_cosyvoice3(connection):
        return dialogue
    old = getattr(connection, "_longmemory_waiting", None)
    if old is not None and old.current():
        return dialogue  # 记忆→模型→工具/递归共用一次计时，不重新等待/重复提示。
    if old is not None:
        old.cancel()
    state = WaitingTurn(connection, "model")
    connection._longmemory_waiting = state
    state.timer.start()
    return dialogue


def mark_answer_ready(connection):
    state = getattr(connection, "_longmemory_waiting", None)
    if state is not None and state.current():
        with state.lock:
            state.answer_ready = True
            state.timer.cancel()
            if state.cue_state in {"pending", "queued"} and state.first_feedback_ms is None:
                state.cue_state = "skipped"


def install_waiting_sender(send_module):
    """在最终套接字发送入口区分提示和答案，覆盖流控队列中的迟到包。"""
    if getattr(send_module, "_longmemory_waiting_installed", False):
        return
    original = send_module._do_send_audio

    def discard(packet):
        if not isinstance(packet, WaitingPacket) or isinstance(packet, AnswerPacket):
            return False
        state = packet.state
        if (state.current() and not state.answer_ready and state.cue_current()
                and time.perf_counter() >= state.cue_deadline
                and state.budget.eligible(state)):
            return False
        if state.first_feedback_ms is None:
            state.cue_state = 'skipped'
        return True

    original_start = getattr(send_module, '_start_background_sender', None)
    if callable(original_start):
        def start(connection, controller, flow_control):
            class ControllerProxy:
                def __getattr__(self, name):
                    return getattr(controller, name)
                def start_sending(self, callback):
                    async def filtered(packet):
                        if discard(packet):
                            # 固定上游在 callback 前已给这帧增加虚拟播放位置。
                            # 丢弃的提示不应继续消耗后续每帧60ms配额；只退本次配额。
                            if (flow_control.get('sentence_id') == connection.sentence_id
                                    and getattr(controller, 'frame_duration', None) == 60
                                    and type(getattr(controller, 'play_position', None)) is int
                                    and controller.play_position >= 60):
                                controller.play_position -= 60
                            return
                        await callback(packet)
                    return controller.start_sending(filtered)
            return original_start(connection, ControllerProxy(), flow_control)
        send_module._start_background_sender = start

    async def send(connection, packet, flow_control):
        state = getattr(connection, "_longmemory_waiting", None)
        tagged = isinstance(packet, WaitingPacket)
        waiting = tagged and not isinstance(packet, AnswerPacket)
        if tagged:
            state = packet.state
            if not state.current() or discard(packet):
                if waiting and state.first_feedback_ms is None:
                    state.cue_state = "skipped"
                return
        claimed = False
        if waiting:
            with state.lock:
                if discard(packet) or not state.budget.claim(state):
                    return None
                claimed = True
        try:
            # 不持有线程锁跨await，也不让等待提示占据答案的调度槽。
            result = await original(connection, packet, flow_control)
        finally:
            if claimed:
                with state.lock:
                    state.budget.release(state)
        return result

    send_module._do_send_audio = send
    send_module._longmemory_waiting_installed = True
