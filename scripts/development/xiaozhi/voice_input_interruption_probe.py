"""纯合成输入边界回环：无端口、模型、GPU、设备或日用连接。

固定上游方法快照 + 注入 VAD/解码/识别结果，只证明控制流，不证明声学识别。
"""

import asyncio
from collections import Counter, deque
from enum import Enum
import importlib.util
import json
from pathlib import Path
import queue
import threading
import time
from types import SimpleNamespace
import uuid


ROOT = Path(__file__).resolve().parents[3]
PCM = b"\x01\x00" * 960


class SilentLogger:
    def __init__(self, counts):
        self.counts = counts

    def bind(self, **kwargs):
        return self

    def error(self, *args, **kwargs):
        self.counts["caught_error"] += 1

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class InterfaceType(Enum):
    LOCAL = "LOCAL"
    STREAM = "STREAM"


def harness(*, speaking=True, aec=False, just_woken=False, prefetch=False,
            blocked_send=False, blocked_model=False, protocol_timeout=None):
    path = ROOT / "tests/fixtures/xiaozhi_input_snapshot_eb4b28c.py"
    spec = importlib.util.spec_from_file_location("ac_input_snapshot_" + uuid.uuid4().hex, path)
    upstream = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upstream)
    counts = Counter()
    upstream.logger = SilentLogger(counts)
    upstream.InterfaceType = InterfaceType
    upstream.lang_tag_filter = lambda text: {"content": text}
    original_handle = upstream.handleAudioMessage
    original_abort = upstream.handleAbortMessage

    async def counted_handle(connection, frame):
        counts["handle_audio_entered"] += 1
        return await original_handle(connection, frame)

    async def counted_abort(connection):
        counts["abort_entered"] += 1
        result = await original_abort(connection)
        counts["abort_returned"] += 1
        return result

    upstream.handleAudioMessage = counted_handle
    upstream.handleAbortMessage = counted_abort

    class RawSocket:
        def __init__(self):
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            if not blocked_send:
                self.release.set()

        async def send(self, value):
            counts["socket_send_entered"] += 1
            self.entered.set()
            await self.release.wait()
            counts["socket_send_returned"] += 1

        async def close(self, *args, **kwargs):
            counts["socket_closed"] += 1
            self.release.set()

    class VAD:
        voiced = True

        def is_vad(self, connection, frame):
            counts["vad_called"] += 1
            if self.voiced:
                counts["vad_positive"] += 1
                connection.client_have_voice = True
                connection.vad_last_voice_time = time.time() * 1000
            return self.voiced

    class Model:
        kwargs = {}

        def __init__(self):
            self.entered = threading.Event()
            self.release = threading.Event()
            if not blocked_model:
                self.release.set()

        def generate(self, **kwargs):
            counts["synthetic_model_entered"] += 1
            self.entered.set()
            if not self.release.wait(1):
                raise RuntimeError("probe_release_missing")
            counts["synthetic_model_returned"] += 1
            return [{"text": "synthetic-result"}]

    class Connection(upstream.ConnectionHandler):
        def __init__(self):
            self.bind_completed_event = asyncio.Event()
            self.bind_completed_event.set()
            self.need_bind = False
            self.conn_from_mqtt_gateway = False
            self.client_is_speaking = speaking
            self.client_aec = aec
            self.client_listen_mode = "auto"
            self.just_woken_up = just_woken
            self.stop_event = threading.Event()
            self.asr_audio_queue = queue.Queue()
            self.asr_audio = []
            self.client_audio_buffer = bytearray()
            self.client_voice_window = deque(maxlen=5)
            self.client_have_voice = self.client_voice_stop = self.last_is_voice = False
            self.vad_last_voice_time = 0
            self.last_activity_time = 0
            self.close_after_chat = False
            self.client_abort = False
            self.voiceprint_provider = None
            self.logger = upstream.logger
            self.config = {"close_connection_no_voice_time": 120}
            self.session_id = "synthetic"
            self.tts = SimpleNamespace(tts_text_queue=queue.Queue(), tts_audio_queue=queue.Queue())
            self.report_queue = queue.Queue()
            self.loop = asyncio.get_running_loop()
            self.vad = VAD()
            self.websocket = RawSocket()

        def _decode_opus_packet(self, packet):
            counts["decode_stub"] += 1
            return PCM

        def reset_audio_states(self):
            counts["reset"] += 1
            return super().reset_audio_states()

        async def close(self):
            self.stop_event.set()

    class Provider(upstream.LocalASR):
        model_dir = "models/SenseVoiceSmall"
        interface_type = InterfaceType.LOCAL
        delete_audio_file = True
        language = "zh"

        def __init__(self):
            self.model = Model()

        async def receive_audio(self, connection, frame, have_voice):
            counts["asr_receive_entered"] += 1
            return await super().receive_audio(connection, frame, have_voice)

        async def handle_voice_stop(self, connection, frames):
            # 不装正式计时/聊天/上报；这里仅记录正式方法调用边界。
            counts["formal_asr_entered"] += 1
            artifacts = SimpleNamespace(pcm_bytes=b"".join(frames), file_path=None)
            result, _ = await self.speech_to_text(frames, connection.session_id, artifacts)
            counts["formal_asr_returned"] += 1
            if isinstance(result, dict) and result.get("content"):
                counts["synthetic_handoff"] += 1

    if prefetch:
        from voice_asr_prefetch import install_voice_asr_prefetch
        install_voice_asr_prefetch(Connection, SimpleNamespace(ASRProvider=Provider,
            lang_tag_filter=upstream.lang_tag_filter), enabled=True)
    connection = Connection()
    provider = connection.asr = Provider()
    raw = connection.websocket
    protocol = None
    if protocol_timeout is not None:
        from voice_output_protocol import OutputProtocol, SocketProxy
        protocol = OutputProtocol(connection, raw, send_timeout=protocol_timeout)
        protocol.proxy = SocketProxy(protocol)
        connection.websocket = protocol.proxy
    return SimpleNamespace(connection=connection, provider=provider, raw=raw, counts=counts,
                           upstream=upstream, protocol=protocol)


async def until(predicate, timeout=.5):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise RuntimeError("probe_stage_not_reached")
        await asyncio.sleep(.001)


async def stop(h, worker=None):
    h.connection.stop_event.set()
    h.raw.release.set()
    h.provider.model.release.set()
    if worker is not None:
        await asyncio.to_thread(worker.join, 1.2)
        if worker.is_alive():
            raise RuntimeError("probe_worker_not_reaped")
    task = getattr(h.connection, "vad_resume_task", None)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    if h.protocol is not None:
        await h.protocol.close()


async def probe():
    rows = []
    h = harness(speaking=True, aec=False)
    try:
        await h.connection._route_message(b"synthetic-opus-placeholder")
        queued = h.connection.asr_audio_queue.get_nowait()
        await h.upstream.handleAudioMessage(h.connection, queued)
        rows.append({"case": "speaking_no_aec_forwarded", "counts": dict(h.counts)})
    finally:
        await stop(h)

    h = harness(just_woken=True)
    try:
        await h.upstream.handleAudioMessage(h.connection, PCM)
        rows.append({"case": "just_woken_asr_skipped", "counts": dict(h.counts)})
    finally:
        await stop(h)

    h = harness(speaking=True, aec=True, blocked_send=True)
    worker = threading.Thread(target=h.provider.asr_text_priority_thread, args=(h.connection,), daemon=True)
    worker.start()
    try:
        await h.connection._route_message(b"synthetic-one")
        await until(h.raw.entered.is_set)
        await h.connection._route_message(b"synthetic-two")
        rows.append({"case": "blocked_abort_send_before_asr", "counts": dict(h.counts),
                     "queued_frames": h.connection.asr_audio_queue.qsize()})
    finally:
        await stop(h, worker)

    h = harness(speaking=True, aec=False, blocked_model=True)
    h.connection.asr_audio = [PCM] * 16
    h.connection.client_have_voice = h.connection.client_voice_stop = True
    h.connection.vad.voiced = False
    worker = threading.Thread(target=h.provider.asr_text_priority_thread, args=(h.connection,), daemon=True)
    worker.start()
    try:
        await h.connection._route_message(b"synthetic-one")
        await until(h.provider.model.entered.is_set)
        await h.connection._route_message(b"synthetic-two")
        rows.append({"case": "formal_model_wait_serializes_next_vad", "counts": dict(h.counts),
                     "queued_frames": h.connection.asr_audio_queue.qsize(), "observed_timeout": False})
    finally:
        await stop(h, worker)
    return {"version": 1, "base_commit": "58ca0f3282e4b3e54c38e821eafb60d09e46e82e",
            "evidence": "synthetic_control_flow_not_live_audio_or_recognition", "rows": rows}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(probe()), indent=2))
