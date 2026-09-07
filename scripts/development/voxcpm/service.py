"""VoxCPM2 本机 TTS 服务：模型常驻显存，向同机 Xiaozhi 返回 WAV。

该入口只允许环回地址，不读取聊天数据库、模型密钥或任意参考音频。
第一版采用整句非流式合成；HTTP 契约刻意兼容 Xiaozhi 的 CustomTTS。
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import ipaddress
import json
import os
from pathlib import Path
import threading
from typing import Protocol

from trial import MODEL, REVISION, ROOT, verify_weights

MAX_REQUEST_BYTES = 32 * 1024
MAX_TEXT_CHARS = 600
DEFAULT_PORT = 18768
PROFILE_PATH = ROOT / "data/audio/voxcpm-settings.json"
AUDIO_ROOT = (ROOT / "data/audio").resolve()
QUALITY_STEPS = {"fast": 6, "balanced": 10, "quality": 20}


def current_profile():
    default = {"version": 1, "reference": None, "style": "", "cfg_value": 2.0,
               "quality": "balanced"}
    try:
        value = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return default
    if not isinstance(value, dict) or set(value) != set(default) or value.get("version") != 1:
        return default
    reference = value.get("reference")
    if reference is not None:
        if not isinstance(reference, str) or not reference.endswith(".wav"):
            return default
        path = (AUDIO_ROOT / reference).resolve()
        try:
            path.relative_to(AUDIO_ROOT)
        except ValueError:
            return default
        if not path.is_file() or path.is_symlink():
            return default
    if (not isinstance(value.get("style"), str) or len(value["style"]) > 100
            or any(ord(char) < 32 for char in value["style"])):
        return default
    if type(value.get("cfg_value")) not in {int, float} or not 1.0 <= value["cfg_value"] <= 3.0:
        return default
    if value.get("quality") not in QUALITY_STEPS:
        return default
    return value


class SpeechSynthesizer(Protocol):
    def synthesize(self, text: str) -> bytes: ...


class VoxCPMSynthesizer:
    """持有唯一模型实例；串行访问 GPU，并缓存少量重复句子。"""

    def __init__(self, cache_entries: int = 24):
        verify_weights()
        # 推理时严格离线，避免日常启动意外访问 Hugging Face。
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        import torch
        import soundfile as sf
        from voxcpm import VoxCPM

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable")
        self._torch = torch
        self._soundfile = sf
        self._model = VoxCPM.from_pretrained(
            str(MODEL), load_denoiser=False, optimize=False, device="cuda"
        )
        self._sample_rate = int(self._model.tts_model.sample_rate)
        self._cache_entries = cache_entries
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.Lock()

    def synthesize(self, text: str) -> bytes:
        # VoxCPM/PyTorch 的随机状态与模型对象不是并发请求边界；一次只生成一句。
        with self._lock:
            profile = current_profile()
            cache_key = json.dumps(profile, ensure_ascii=False, sort_keys=True) + "\0" + text
            cached = self._cache.pop(cache_key, None)
            if cached is not None:
                self._cache[cache_key] = cached
                return cached
            self._torch.manual_seed(42)
            self._torch.cuda.manual_seed_all(42)
            reference = profile["reference"]
            styled_text = f"({profile['style']}){text}" if profile["style"].strip() else text
            waveform = self._model.generate(
                text=styled_text,
                reference_wav_path=str(AUDIO_ROOT / reference) if reference else None,
                cfg_value=float(profile["cfg_value"]),
                inference_timesteps=QUALITY_STEPS[profile["quality"]],
                normalize=False,
                denoise=False,
                retry_badcase=False,
                max_len=300,
            )
            if not len(waveform):
                raise RuntimeError("empty audio")
            output = BytesIO()
            self._soundfile.write(
                output, waveform, self._sample_rate, format="WAV", subtype="PCM_16"
            )
            audio = output.getvalue()
            self._cache[cache_key] = audio
            while len(self._cache) > self._cache_entries:
                self._cache.popitem(last=False)
            return audio


class VoxCPMHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # Xiaozhi/启动面板会轮询健康接口，停止后 Windows 留下 TIME_WAIT。
    # 仅环回监听且启动器另行拒绝真实 listener，允许立即重启同一服务端口。
    allow_reuse_address = True

    def __init__(self, address, synthesizer: SpeechSynthesizer):
        super().__init__(address, VoxCPMHandler)
        self.synthesizer = synthesizer
        # 忙时立即拒绝第二次生成，避免多个 GPU 推理堆积。重复句缓存仍在模型层生效。
        self.generation_gate = threading.Lock()


class VoxCPMHandler(BaseHTTPRequestHandler):
    server: VoxCPMHTTPServer

    def log_message(self, _format, *_args):
        # 日常日志不保存合成文本；启动/错误状态由固定消息表达。
        return

    def _json(self, status: int, body: dict):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path != "/health":
            self._json(404, {"error": "not_found"})
            return
        self._json(200, {"ready": True, "provider": "voxcpm2", "revision": REVISION})

    def do_OPTIONS(self):
        # 不提供 CORS；网页不能把本服务当作任意本机 GPU 接口。
        self._json(405, {"error": "method_not_allowed"})

    def _discard_small_body(self):
        """拒绝请求前排空有限正文，避免 Windows 用 TCP reset 吞掉 HTTP 错误响应。"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        if 0 < length <= MAX_REQUEST_BYTES:
            self.rfile.read(length)

    def do_POST(self):
        if self.path != "/v1/audio/speech":
            self._json(404, {"error": "not_found"})
            return
        if self.headers.get("Origin") is not None:
            self._discard_small_body()
            self._json(403, {"error": "browser_origin_rejected"})
            return
        content_type = self.headers.get_content_type()
        length_text = self.headers.get("Content-Length")
        try:
            length = int(length_text) if length_text is not None else -1
        except ValueError:
            length = -1
        if content_type != "application/json" or not 0 < length <= MAX_REQUEST_BYTES:
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
            or body.get("stream", False) is not False
        ):
            self._json(400, {"error": "invalid_request"})
            return
        if not self.server.generation_gate.acquire(blocking=False):
            self._json(503, {"error": "busy"})
            return
        try:
            audio = self.server.synthesizer.synthesize(text.strip())
        except Exception:
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
        raise argparse.ArgumentTypeError("VoxCPM2 服务只允许环回地址")
    return str(address)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=loopback_address, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口必须在 1024–65535")
    synthesizer = VoxCPMSynthesizer()
    server = VoxCPMHTTPServer((args.host, args.port), synthesizer)
    print(f"VoxCPM2 已就绪：http://{args.host}:{args.port}/health", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
