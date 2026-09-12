"""CosyVoice 3 本机常驻服务；提供完整 WAV 与受限的本机分块通道。

完整 WAV 接口继续服务网页试听和兼容回退。分块接口使用长度前缀传输模型原生
生成块，只供同机 Xiaozhi 启动适配器消费；它不接受浏览器来源，也不暴露到局域网。
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import importlib.util
import ipaddress
import json
from pathlib import Path
import struct
import sys
from time import perf_counter
import threading
from typing import Protocol

# 多个隔离 TTS 目录都可能有 trial.py。使用唯一模块名加载同目录文件，避免
# 完整 pytest 进程中的 sys.modules 把 CosyVoice 与 VoxCPM2 试验模块串台。
_TRIAL_SPEC = importlib.util.spec_from_file_location(
    "longmemory_cosyvoice_trial", Path(__file__).with_name("trial.py")
)
if _TRIAL_SPEC is None or _TRIAL_SPEC.loader is None:
    raise RuntimeError("CosyVoice trial module unavailable")
_trial = importlib.util.module_from_spec(_TRIAL_SPEC)
_TRIAL_SPEC.loader.exec_module(_trial)
DEFAULT_MODEL = _trial.DEFAULT_MODEL
DEFAULT_SOURCE = _trial.DEFAULT_SOURCE
PROMPT_TEXT = _trial.PROMPT_TEXT
configure_runtime_cache = _trial.configure_runtime_cache
validate_local_files = _trial.validate_local_files


DEFAULT_PORT = 18770
MAX_REQUEST_BYTES = 32 * 1024
MAX_TEXT_CHARS = 600
WARMUP_TEXT = "你好，我准备好了。"
CAPABILITIES = {
    "contract_version": 2,
    "provider_id": "cosyvoice3",
    "display_name": "CosyVoice 3 0.5B",
    "locality": "local",
    "delivery_modes": ["buffered", "audio_stream"],
    "output_mime_types": ["audio/wav"],
    "controls": [],
    # 客户端关闭 HTTP 响应后，服务端在下一个模型块写出时终止迭代。它不是逐采样
    # 抢占，因此只声明协作式取消，不能冒充即时 GPU 中止。
    "cancellation": "cooperative",
    "max_text_chars": MAX_TEXT_CHARS,
}


class SpeechSynthesizer(Protocol):
    def synthesize(self, text: str, *, use_cache: bool = True) -> bytes: ...

    def stream_chunks(self, text: str): ...


class CosyVoiceSynthesizer:
    """只加载一个模型实例，并串行处理 GPU 推理。"""

    def __init__(
        self,
        source_root: Path = DEFAULT_SOURCE,
        model_dir: Path = DEFAULT_MODEL,
        *,
        cache_entries: int = 24,
    ):
        paths = validate_local_files(source_root, model_dir)
        configure_runtime_cache()
        sys.path.insert(0, str(source_root))
        sys.path.insert(0, str(source_root / "third_party" / "Matcha-TTS"))
        import soundfile
        import torch
        from cosyvoice.cli.cosyvoice import CosyVoice3

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable")
        self._torch = torch
        self._soundfile = soundfile
        self._prompt_wav = paths["prompt_wav"]
        self._lock = threading.Lock()
        self._cache_entries = cache_entries
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        load_started = perf_counter()
        self._model = CosyVoice3(str(model_dir), fp16=True)
        self.load_seconds = perf_counter() - load_started
        self._sample_rate = int(self._model.sample_rate)
        # 服务只有在懒初始化路径也跑过之后才宣告 ready，避免首位用户承担额外冷启动。
        warmup_started = perf_counter()
        self._generate(WARMUP_TEXT)
        self.warmup_seconds = perf_counter() - warmup_started

    def _generate(self, text: str) -> bytes:
        chunks = []
        for item in self._model.inference_zero_shot(
            text, PROMPT_TEXT, self._prompt_wav, stream=True
        ):
            speech = item.get("tts_speech")
            if speech is None or speech.numel() == 0:
                raise RuntimeError("empty audio chunk")
            chunks.append(speech.detach().cpu())
        if not chunks:
            raise RuntimeError("empty audio")
        waveform = self._torch.cat(chunks, dim=1).squeeze(0)
        if not self._torch.isfinite(waveform).all():
            raise RuntimeError("invalid audio")
        peak = float(waveform.abs().max())
        rms = float(self._torch.sqrt(self._torch.mean(waveform.float() ** 2)))
        if waveform.numel() < self._sample_rate // 20 or peak < 0.015 or rms < 0.0015:
            raise RuntimeError("near-silent audio")
        output = BytesIO()
        self._soundfile.write(
            output,
            waveform.numpy(),
            self._sample_rate,
            format="WAV",
            subtype="PCM_16",
        )
        return output.getvalue()

    def _wave_bytes(self, speech) -> bytes:
        """把一个模型输出块封装为可独立解码的 PCM WAV。"""
        waveform = speech.detach().cpu().squeeze(0)
        if waveform.numel() == 0 or not self._torch.isfinite(waveform).all():
            raise RuntimeError("invalid audio chunk")
        output = BytesIO()
        self._soundfile.write(
            output,
            waveform.numpy(),
            self._sample_rate,
            format="WAV",
            subtype="PCM_16",
        )
        return output.getvalue()

    def stream_chunks(self, text: str):
        """串行占用模型，但不再等待整段语音生成完才交付第一个音频块。"""
        with self._lock:
            for item in self._model.inference_zero_shot(
                text, PROMPT_TEXT, self._prompt_wav, stream=True
            ):
                speech = item.get("tts_speech")
                if speech is None:
                    raise RuntimeError("empty audio chunk")
                yield self._wave_bytes(speech)

    def synthesize(self, text: str, *, use_cache: bool = True) -> bytes:
        with self._lock:
            if use_cache:
                cached = self._cache.pop(text, None)
                if cached is not None:
                    self._cache[text] = cached
                    return cached
            audio = self._generate(text)
            if use_cache:
                self._cache[text] = audio
                while len(self._cache) > self._cache_entries:
                    self._cache.popitem(last=False)
            return audio


class CosyVoiceHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, synthesizer: SpeechSynthesizer):
        super().__init__(address, CosyVoiceHandler)
        self.synthesizer = synthesizer
        self.generation_gate = threading.Lock()


class CosyVoiceHandler(BaseHTTPRequestHandler):
    server: CosyVoiceHTTPServer

    def log_message(self, _format, *_args):
        # 不把合成文本写入长期日志。
        return

    def _json(self, status: int, body: dict) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/v1/capabilities":
            self._json(200, CAPABILITIES)
            return
        if self.path != "/health":
            self._json(404, {"error": "not_found"})
            return
        body = {"ready": True, "provider": "cosyvoice3", "capabilities": CAPABILITIES}
        for name in ("load_seconds", "warmup_seconds"):
            value = getattr(self.server.synthesizer, name, None)
            if isinstance(value, (int, float)):
                body[name] = round(value, 3)
        self._json(200, body)

    def do_OPTIONS(self):
        self._json(405, {"error": "method_not_allowed"})

    def _discard_small_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        if 0 < length <= MAX_REQUEST_BYTES:
            self.rfile.read(length)

    def do_POST(self):
        if self.path not in {"/v1/audio/speech", "/v1/audio/stream"}:
            self._json(404, {"error": "not_found"})
            return
        if self.headers.get("Origin") is not None:
            self._discard_small_body()
            self._json(403, {"error": "browser_origin_rejected"})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if self.headers.get_content_type() != "application/json" or not 0 < length <= MAX_REQUEST_BYTES:
            self._json(400, {"error": "invalid_request"})
            return
        try:
            body = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"error": "invalid_request"})
            return
        text = body.get("input") if isinstance(body, dict) else None
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > MAX_TEXT_CHARS
            or body.get("response_format", "wav") != "wav"
            or type(body.get("stream", False)) is not bool
            or type(body.get("cache", True)) is not bool
        ):
            self._json(400, {"error": "invalid_request"})
            return
        streaming = self.path == "/v1/audio/stream"
        if streaming != body.get("stream", False):
            self._json(400, {"error": "invalid_request"})
            return
        if not self.server.generation_gate.acquire(blocking=False):
            self._json(503, {"error": "busy"})
            return
        try:
            if streaming:
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.longmemory.wav-chunks")
                self.send_header("Cache-Control", "no-store")
                # HTTP/1.0 会以连接关闭标记响应结束。每个 WAV 前的无符号大端长度
                # 让客户端不依赖 TCP 分包边界，最大块仍由客户端再次限制。
                self.end_headers()
                for chunk in self.server.synthesizer.stream_chunks(text.strip()):
                    self.wfile.write(struct.pack("!I", len(chunk)))
                    self.wfile.write(chunk)
                    self.wfile.flush()
                return
            audio = self.server.synthesizer.synthesize(text.strip(), use_cache=body.get("cache", True))
        except (BrokenPipeError, ConnectionResetError):
            # 用户打断或 Xiaozhi 退出时，关闭生成器即可释放模型锁；无需把正常取消
            # 记录成合成故障，也不能在已经发送部分音频后回写 JSON。
            return
        except Exception:
            if not streaming:
                self._json(500, {"error": "synthesis_failed"})
            return
        finally:
            self.server.generation_gate.release()
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(audio)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(audio)


def loopback_address(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("需要数字形式的环回 IP") from error
    if not address.is_loopback:
        raise argparse.ArgumentTypeError("CosyVoice 服务只允许环回地址")
    return str(address)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=loopback_address, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口必须在 1024–65535")
    synthesizer = CosyVoiceSynthesizer(args.source_root, args.model_dir)
    server = CosyVoiceHTTPServer((args.host, args.port), synthesizer)
    print(
        "CosyVoice 3 已就绪："
        f"http://{args.host}:{args.port}/health "
        f"load={synthesizer.load_seconds:.2f}s warmup={synthesizer.warmup_seconds:.2f}s",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
