"""AD隔离全双工反驳探针：固定SDK方法+真实HTTP/WS/Opus，VAD/ASR为明确替身。"""
import ast
import asyncio
from collections import deque
import io
import json
import math
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import threading
import time
import traceback
from types import MethodType, ModuleType, SimpleNamespace as NS
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts/development/xiaozhi"), str(ROOT / "tests/fixtures")]
from voice_interruption_upstream import build, PIN, UPSTREAM


def load(path, name, namespace, cls=None):
    value = subprocess.check_output(["git", "-C", str(UPSTREAM), "show",
        PIN + ":main/xiaozhi-server/" + path], text=True, encoding="utf-8")
    tree = ast.parse(value)
    nodes = tree.body if cls is None else next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls).body
    node = next(n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "pinned:" + name, "exec"), namespace)
    return namespace[name]


def wav(pcm):
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(24000)
        file.writeframes(pcm)
    return output.getvalue()


async def scenario(config, voice, Encoder, Decoder, websockets):
    import cosyvoice_streaming as consumer
    import voice_interruption as guard
    import voice_output_protocol as wire
    u = build()
    c, tts = u.conn, u.conn.tts
    mode, rate = config["mode"], config.get("rate", 16000)
    origin = time.perf_counter()
    events, errors, reports = [], [], []
    def note(stage, **values):
        events.append(dict(stage=stage, at_ms=(time.perf_counter() - origin) * 1000, **values))
    silent = NS(bind=lambda **_: NS(debug=lambda *_: None, info=lambda *_: None,
        warning=lambda *args: print("synthetic-warning", *args, file=sys.stderr),
        error=lambda *args: (errors.append("synthetic_sdk_error"), print("synthetic-error", *args, file=sys.stderr))))
    c.logger = silent
    c.config = {"xiaozhi": {"type": "hello", "audio_params": {"sample_rate": rate},
        "features": {wire.CAPABILITY: True}}, "selected_module": {"TTS": "CustomTTS"},
        "TTS": {"CustomTTS": {"url": "http://127.0.0.1:18770/v1/audio/speech"}}}
    c.voice_mode = "pipeline"
    c.client_aec = config.get("aec", False)  # 合成场景参数，绝不读取或更改日用AEC。
    c.client_audio_buffer = bytearray()
    c.client_voice_window = deque(maxlen=5)
    c.client_have_voice = c.client_voice_stop = False
    c.last_is_voice = False
    c.vad_last_voice_time = 0
    c.asr_audio = []
    c.asr_audio_queue = queue.Queue()
    c.bind_completed_event = asyncio.Event()
    c.bind_completed_event.set()
    c._connection_opus_decoder = Decoder(16000, 1)
    c._init_connection_state = lambda _: None
    c._check_timeout = c._check_aec_cache_expiry = lambda: asyncio.Event().wait()
    async def initialize():
        pass
    c._background_initialize = initialize
    async def save(_):
        for task in (c.timeout_task, c._aec_cache_cleanup_task):
            task.cancel()
        await asyncio.gather(c.timeout_task, c._aec_cache_cleanup_task, return_exceptions=True)
    c._save_and_close = save
    connection_file = "core/connection.py"
    for name in ("_decode_opus_packet", "reset_audio_states"):
        setattr(u.Connection, name, load(connection_file, name, {"TAG": "test"}, "ConnectionHandler"))
    route = load(connection_file, "_route_message", {"asyncio": asyncio}, "ConnectionHandler")
    hello = load("core/handle/helloHandle.py", "handleHelloMessage", {"json": json, "asyncio": asyncio, "TAG": "test"})
    async def routed(message):
        if isinstance(message, str):
            await hello(c, json.loads(message))
        else:
            note("ws_audio_received")
            await route(c, message)
            note("pcm_enqueued", queue_depth=c.asr_audio_queue.qsize())
    c._route_message = routed
    u.Connection.handle_connection = load(connection_file, "handle_connection",
        {"websockets": websockets, "asyncio": asyncio, "time": time, "TAG": "test",
         "traceback": traceback, "AuthenticationError": type("SyntheticAuth", (Exception,), {})}, "ConnectionHandler")

    vad_frames = [0]
    voiced_frames = config.get("voiced_frames", 17)
    def vad(_, pcm):
        vad_frames[0] += 1
        speech = config.get("speech", True) and vad_frames[0] <= voiced_frames
        note("vad_probe_decision", speech=speech)
        if speech:
            c.client_have_voice = True
            c.vad_last_voice_time = time.time() * 1000
        elif c.client_have_voice:
            c.client_voice_stop = True
        return speech
    c.vad = NS(is_vad=vad)
    finished = asyncio.Event()
    class ASR:
        interface_type = "offline"
        async def handle_voice_stop(self, conn, audio):
            note("asr_model_probe_called", pcm_bytes=sum(map(len, audio)))
            await asyncio.sleep(.002)
            nonempty = not config.get("empty_text", False)
            note("asr_model_probe_returned", nonempty=nonempty)
            if nonempty:
                note("asr_text_handoff")
                await u.asr.startToChat(c, "synthetic-recognition-only")
            finished.set()
    namespace = {"InterfaceType": NS(STREAM="stream"), "time": time}
    ASR.receive_audio = load("core/providers/asr/base.py", "receive_audio", namespace, "ASRProviderBase")
    original_receive = ASR.receive_audio
    async def receive_audio(self, conn, pcm, have_voice):
        note("asr_receive_audio", speech=have_voice)
        return await original_receive(self, conn, pcm, have_voice)
    ASR.receive_audio = receive_audio
    c.asr = ASR()
    original_handle = u.receive.handleAudioMessage
    async def handled(conn, pcm):
        if conn.stop_event.is_set():
            return
        note("audio_handler_entered")
        return await original_handle(conn, pcm)
    thread_method = load("core/providers/asr/base.py", "asr_text_priority_thread",
        {"asyncio": asyncio, "queue": queue, "handleAudioMessage": handled,
         "logger": silent, "traceback": traceback, "TAG": "test"}, "ASRProviderBase")
    ASR.asr_text_priority_thread = thread_method

    # 安装消费器时只替代与音频算法无关的DTO/Markdown/文件回退，不导入完整上游应用。
    dto = ModuleType("core.providers.tts.dto.dto")
    dto.SentenceType = u.send.SentenceType
    cleaner = ModuleType("core.utils.tts")
    cleaner.MarkdownCleaner = NS(clean_markdown=lambda value: value)
    utility = ModuleType("core.utils.util")
    utility.audio_bytes_to_data_stream = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("preset_forbidden"))
    for module in (dto, cleaner, utility):
        sys.modules[module.__name__] = module
    tts.to_tts_stream = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("fallback_forbidden"))
    tts._longmemory_cosy_streaming_installed = False
    tts.opus_encoder = Encoder(rate, 1, 60)
    tts.tts_timeout = 3
    tts.report_on_last = False
    tts.tts_stop_request = False
    tts._correct_words_pattern = None
    c._longmemory_cosy_delivery_mode = mode
    c._longmemory_cosy_reply_cache = False
    c._longmemory_voice_latency = NS(record_continuity=lambda report, **_: reports.append(report))
    consumer.default_voice_active = lambda: False
    consumer.for_sentence = lambda *_: None
    consumer.install_cosyvoice_streaming(tts, c)
    u.hello_alias = NS(sendAudioMessage=u.send.sendAudioMessage, send_tts_message=u.send.send_tts_message)
    u.listen_alias = NS(send_tts_message=u.send.send_tts_message)
    guard.install_voice_interruption(u.Connection, u.receive, u.asr, u.send, tts_base_module=u.ttsbase)
    wire.install_tts_interrupt_protocol(u.Connection, u.send, hello_module=u.hello_alias,
        listen_module=u.listen_alias, upstream_root=voice, send_timeout=1)
    state = guard.state_for(c)
    original_revoke = state.revoke
    def revoke(reason):
        note("output_revoked", reason=reason)
        return original_revoke(reason)
    state.revoke = revoke
    tts.handle_opus = MethodType(load("core/providers/tts/base.py", "handle_opus",
        {"SentenceType": u.send.SentenceType, "logger": silent, "TAG": "test"}, "TTSProviderBase"), tts)
    tts.conn = c
    player_method = load("core/providers/tts/base.py", "_audio_play_priority_thread",
        {"SentenceType": u.send.SentenceType, "asyncio": asyncio, "queue": queue, "logger": silent,
         "TAG": "test", "enqueue_tts_report": lambda *_: None, "sendAudioMessage": u.ttsbase.sendAudioMessage},
        "TTSProviderBase")

    data = struct.pack("<14400h", *[round(9000 * math.sin(2 * math.pi * 400 * i / 24000)) for i in range(14400)])
    class HTTP(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.longmemory.wav-chunks")
            self.send_header("X-LongMemory-Audio-Stream", "2")
            self.end_headers()
            try:
                if body["delivery_mode"] == "buffered":
                    time.sleep(.12)
                    chunks = [wav(data * 6)]
                else:
                    chunks = [wav(data)] * 6
                for chunk in chunks:
                    self.wfile.write(struct.pack("!I", len(chunk)) + chunk)
                    self.wfile.flush()
                    if body["delivery_mode"] == "incremental":
                        time.sleep(.04)
                self.wfile.write(b"\0" * 4)
            except (BrokenPipeError, ConnectionResetError):
                pass
    http = ThreadingHTTPServer(("127.0.0.1", 0), HTTP)
    http_thread = threading.Thread(target=http.serve_forever, daemon=True)
    http_thread.start()
    consumer.STREAM_URL = f"http://127.0.0.1:{http.server_port}/v1/audio/stream"
    server = await websockets.serve(c.handle_connection, "127.0.0.1", 0, close_timeout=.1)
    client = await websockets.connect(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}", close_timeout=.1)
    worker = player = receiver = production = None
    voiced, blocked = asyncio.Event(), asyncio.Event()
    decoded = Decoder(rate, 1)
    sent_audio = [0]
    try:
        await client.send(json.dumps({"type": "hello", "features": {wire.CAPABILITY: True}, "audio_params": {"sample_rate": rate}}))
        await asyncio.wait_for(client.recv(), 2)
        p = getattr(c, wire.ATTRIBUTE)
        raw_send = p.raw.send
        async def output(value):
            if isinstance(value, bytes):
                sent_audio[0] += 1
                if config.get("slow_output") and sent_audio[0] == 6:
                    note("synthetic_outbound_backpressure_begin")
                    blocked.set()
                    await asyncio.sleep(.35)
                    note("synthetic_outbound_backpressure_end")
            return await raw_send(value)
        p.raw.send = output
        async def receive_output():
            try:
                async for value in client:
                    if isinstance(value, bytes):
                        pcm = decoded.decode(value, rate * 60 // 1000)
                        samples = struct.unpack("<" + "h" * (len(pcm) // 2), pcm)
                        if sum(abs(v) >= 200 for v in samples) >= rate // 200:
                            if not voiced.is_set():
                                note("voiced_output_received")
                            voiced.set()
                    elif json.loads(value).get("state") == "interrupt":
                        note("wire_interrupt_received")
            except websockets.ConnectionClosed:
                pass
        receiver = asyncio.create_task(receive_output())
        c.client_is_speaking = True
        worker = threading.Thread(target=c.asr.asr_text_priority_thread, args=(c,), daemon=True)
        player = threading.Thread(target=player_method, args=(tts,), daemon=True)
        worker.start()
        player.start()
        production = asyncio.create_task(asyncio.to_thread(tts.to_tts_stream,
            "public-synthetic-playback", opus_handler=tts.handle_opus))
        await asyncio.wait_for(voiced.wait(), 3)
        if config.get("slow_output"):
            await asyncio.wait_for(blocked.wait(), 2)
        input_encoder = Encoder(16000, 1, 60)
        input_packets = []
        mic = [round(6000 * math.sin(2 * math.pi * 300 * i / 16000)) for i in range(voiced_frames * 960)] + [0] * 960
        input_encoder.encode_pcm_to_opus_stream(struct.pack("<" + "h" * len(mic), *mic),
                                                end_of_stream=True, callback=input_packets.append)
        input_encoder.close()
        for packet in input_packets:
            note("synthetic_mic_sent")
            await client.send(packet)
            await asyncio.sleep(.004)
        if config.get("speech", True) and voiced_frames + 1 > 15:
            await asyncio.wait_for(finished.wait(), 2)
            await asyncio.sleep(.04)
        else:
            await asyncio.sleep(.15)
        result = dict(config, events=events, errors=errors, output_packets=sent_audio[0],
            wire=wire.protocol_snapshot(c), input_is_real_opus=True, output_is_real_opus=True,
            vad_model_executed=False, asr_model_executed=False, device_interruption_acknowledged=False,
            continuity=reports)
        return result
    finally:
        c.stop_event.set()
        c.client_abort = True
        c.asr_audio_queue.put(b"")
        if production is not None:
            await asyncio.wait_for(production, 4)
        for thread in (worker, player):
            if thread is not None:
                await asyncio.to_thread(thread.join, 1.5)
                assert not thread.is_alive()
        if hasattr(c, "audio_rate_controller"):
            c.audio_rate_controller.stop_sending()
        await client.close()
        if receiver is not None:
            await receiver
        server.close()
        await server.wait_closed()
        await asyncio.to_thread(http.shutdown)
        http.server_close()
        http_thread.join(1)
        tts.opus_encoder.close()


async def main(config):
    voice = Path(config["voice"])
    sys.path.insert(0, str(voice))
    native = voice / "native/libopus-1.6.1/Library/bin"
    os.environ["PATH"] = str(native) + os.pathsep + os.environ.get("PATH", "")
    dll = os.add_dll_directory(str(native))
    from core.utils.opus_encoder_utils import OpusEncoderUtils
    from opuslib_next import Decoder
    import websockets
    try:
        result = await scenario(config["case"], voice, OpusEncoderUtils, Decoder, websockets)
        assert "torch" not in sys.modules
        print(json.dumps(result))
    finally:
        dll.close()


if __name__ == "__main__":
    asyncio.run(main(json.load(sys.stdin)))
