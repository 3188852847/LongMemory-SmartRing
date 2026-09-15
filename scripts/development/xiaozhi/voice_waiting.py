"""同声线等待反馈与真实答案分开计时；只管理语音进程内的一轮临时状态。"""

from pathlib import Path
import struct
import threading
import time

ASSET_ROOT = Path(__file__).resolve().parents[3] / "assets/audio/voice-waiting/cosyvoice3"
PHRASES = {"model": "我想一下。", "web": "我查一下。"}


class WaitingPacket(bytes):
    def __new__(cls, value, state):
        packet = super().__new__(cls, value)
        packet.state = state
        return packet


class AnswerPacket(WaitingPacket):
    """真正回答的包也绑定话轮，不能把提示或停止提示音算作答案首包。"""


def load_packets(kind, sample_rate):
    """固定资产格式，限制长度与帧数；未知采样率/缺资产直接安静降级。"""
    path = ASSET_ROOT / f"{kind}-{sample_rate}.opusframes"
    if not path.is_file() or path.stat().st_size > 128 * 1024:
        return ()
    data = path.read_bytes()
    if data[:8] != b"LMWAIT01":
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


class WaitingTurn:
    def __init__(self, connection, kind, *, delay=0.9, packets=None):
        self.connection, self.kind = connection, kind
        self.sentence_id = connection.sentence_id
        current = getattr(getattr(connection, "_longmemory_voice_latency", None), "current", None)
        self.started = current["started"] if current else time.perf_counter()
        self.status = "querying" if kind == "web" else "answering"
        self.query_ms = None
        self.first_feedback_ms = None
        self.first_answer_ms = None
        self.answer_ready = False
        self.closed = False
        self.cue_state = "pending"
        self.packets = load_packets(kind, connection.sample_rate) if packets is None else packets
        self.timer = threading.Timer(delay, self.enqueue)
        self.timer.daemon = True

    def current(self):
        return (not self.closed and not self.connection.stop_event.is_set()
                and not self.connection.client_abort
                and self.sentence_id == self.connection.sentence_id
                and getattr(self.connection, "_longmemory_waiting", None) is self)

    def cancel(self):
        self.closed = True
        self.timer.cancel()

    def enqueue(self):
        if not self.current() or self.answer_ready:
            self.cue_state = "skipped"
            return
        if not self.packets:
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
    if old is not None:
        old.cancel()
    state = WaitingTurn(connection, "model")
    connection._longmemory_waiting = state
    state.timer.start()
    return dialogue


def mark_answer_ready(connection):
    state = getattr(connection, "_longmemory_waiting", None)
    if state is not None and state.current():
        state.answer_ready = True
        state.timer.cancel()
        if state.cue_state == "pending":
            state.cue_state = "skipped"


def install_waiting_sender(send_module):
    """在最终套接字发送入口区分提示和答案，覆盖流控队列中的迟到包。"""
    if getattr(send_module, "_longmemory_waiting_installed", False):
        return
    original = send_module._do_send_audio

    async def send(connection, packet, flow_control):
        state = getattr(connection, "_longmemory_waiting", None)
        tagged = isinstance(packet, WaitingPacket)
        waiting = tagged and not isinstance(packet, AnswerPacket)
        if tagged:
            state = packet.state
            if not state.current() or (waiting and state.answer_ready and state.first_feedback_ms is None):
                if waiting:
                    state.cue_state = "skipped"
                return
        # 已经开始的短提示完整说完，避免词中硬切；最长 35*60ms，通常更短。
        # 用户打断/换轮时上面的检查仍立即废弃尚未发送的提示。
        result = await original(connection, packet, flow_control)
        if tagged and state.current():
            field = "first_feedback_ms" if waiting else "first_answer_ms"
            if getattr(state, field) is None:
                setattr(state, field, round((time.perf_counter() - state.started) * 1000))
            if waiting:
                state.cue_state = "sent"
            else:
                tracker = getattr(connection, "_longmemory_voice_latency", None)
                if tracker is not None:
                    tracker.mark("first_audio_sent_ms", sentence_id=state.sentence_id)
        return result

    send_module._do_send_audio = send
    send_module._longmemory_waiting_installed = True
