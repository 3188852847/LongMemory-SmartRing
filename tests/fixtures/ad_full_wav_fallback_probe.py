"""真实固定SDK完整WAV回退：合成WAV/CPU Opus，无网络、模型、配置或音频落盘。"""
import ast
import asyncio
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
from types import MethodType, ModuleType, SimpleNamespace as NS
from typing import Any, Callable
import wave

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT.parents[2] if ROOT.parent.name == "worktrees" else ROOT
PIN = "eb4b28c59ed7ed885258498cf757ce14352d620e"


def method(path, name, namespace, cls=None):
    source = subprocess.check_output(["git", "-C", str(MAIN / "local/runtime/xiaozhi-esp32-server"),
        "show", PIN + ":main/xiaozhi-server/" + path], text=True, encoding="utf-8")
    tree = ast.parse(source)
    nodes = tree.body if cls is None else next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls).body
    node = next(n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "fixed-sdk:" + name, "exec"), namespace)
    return namespace[name]


def main():
    voice = MAIN / "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server"
    sys.path[:0] = [str(voice), str(ROOT / "scripts/development/xiaozhi")]
    native = voice / "native/libopus-1.6.1/Library/bin"
    os.environ["PATH"] = str(native) + os.pathsep + os.environ.get("PATH", "")
    dll = os.add_dll_directory(str(native))
    import numpy as np
    import opuslib_next
    from pydub import AudioSegment
    from core.utils.opus_encoder_utils import OpusEncoderUtils
    import cosyvoice_streaming as consumer
    assert Path(consumer.__file__).resolve() == ROOT / "scripts/development/xiaozhi/cosyvoice_streaming.py"
    from cosyvoice_delivery import delivery_snapshot
    sentence = NS(FIRST="first")
    dto = ModuleType("core.providers.tts.dto.dto")
    dto.SentenceType = sentence
    cleaner = ModuleType("core.utils.tts")
    cleaner.MarkdownCleaner = NS(clean_markdown=lambda text: text)
    utility = ModuleType("core.utils.util")
    conversion = dict(Callable=Callable, Any=Any, AudioSegment=AudioSegment,
                      BytesIO=BytesIO, np=np, opuslib_next=opuslib_next)
    method("core/utils/util.py", "pcm_to_data_stream", conversion)
    utility.audio_bytes_to_data_stream = method("core/utils/util.py", "audio_bytes_to_data_stream", conversion)
    for module in (dto, cleaner, utility):
        sys.modules[module.__name__] = module
    consumer.default_voice_active = lambda: False
    consumer.for_sentence = lambda *_: None
    def fail_stream(*_a, **_k):
        raise OSError("synthetic stream failure before audio")
    consumer._open_stream = fail_stream
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(struct.pack("<4320h", *[round(6000 * math.sin(2 * math.pi * 400 * i / 24000)) for i in range(4320)]))
    wav = output.getvalue()
    rows = []
    try:
        for case in ("normal", "callback_raises", "cancel_before_callback", "cancel_after_first",
                     "cancel_after_first_raises", "synthesis_returns_empty", "synthesis_raises", "invalid_wav"):
            calls, packets = [], []
            logger = NS(bind=lambda **_: NS(info=lambda *_: None, warning=lambda *_: None, error=lambda *_: None))
            namespace = dict(asyncio=asyncio, Callable=Callable, logger=logger, TAG="synthetic",
                             MarkdownCleaner=cleaner.MarkdownCleaner, SentenceType=sentence,
                             audio_bytes_to_data_stream=utility.audio_bytes_to_data_stream)
            native_stream = method("core/providers/tts/base.py", "to_tts_stream", namespace, "TTSProviderBase")
            conn = NS(sample_rate=24000, client_abort=False, sentence_id="synthetic",
                      _longmemory_cosy_delivery_mode="adaptive", logger=logger)
            encoder = OpusEncoderUtils(24000, 1, 60)
            tts = NS(conn=conn, delete_audio_file=True, audio_file_type="wav", _correct_words_pattern=None,
                     tts_audio_queue=queue.Queue(), current_sentence_id="synthetic",
                     opus_encoder=encoder, tts_timeout=2, tts_stop_request=False)
            conn.tts = tts
            async def synthesize(_text, _path):
                calls.append(True)
                if case == "synthesis_raises":
                    raise OSError("synthetic generation failure")
                if case == "synthesis_returns_empty":
                    return None
                if case == "cancel_before_callback":
                    conn.client_abort = True
                return b"not-a-wave" if case == "invalid_wav" else wav
            tts.text_to_speak = synthesize
            tts.to_tts_stream = MethodType(native_stream, tts)
            consumer.install_cosyvoice_streaming(tts, conn)
            def handoff(packet):
                packets.append(bytes(packet))
                if case == "callback_raises":
                    raise OSError("synthetic error after enqueue")
                if case in {"cancel_after_first", "cancel_after_first_raises"}:
                    conn.client_abort = True
                    if case == "cancel_after_first_raises":
                        raise OSError("synthetic cancelled callback")
            try:
                tts.to_tts_stream("public-synthetic-fallback", opus_handler=handoff)
                decoder = opuslib_next.Decoder(24000, 1)
                decoded = sum(len(decoder.decode(packet, 1440)) // 2 for packet in packets)
                rows.append(dict(case=case, synthetic_full_wav_calls=len(calls),
                    packets_handed_off=len(packets), decoded_samples=decoded, delivery=delivery_snapshot(conn)))
            finally:
                encoder.close()
        assert "torch" not in sys.modules
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
        print(json.dumps(dict(source_pin=PIN, checkout_head=head, checkout_dirty=dirty,
            consumer_sha256=hashlib.sha256(Path(consumer.__file__).read_bytes()).hexdigest(),
            source_functions=["TTSProviderBase.to_tts_stream",
            "audio_bytes_to_data_stream", "pcm_to_data_stream"],
            cases=rows, real_cpu_opus=True, real_wav_conversion=True, network_used=False,
            torch_imported=False, audio_files_written=False)))
    finally:
        dll.close()


if __name__ == "__main__":
    main()
