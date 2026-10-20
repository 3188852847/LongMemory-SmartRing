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
import hashlib
import ipaddress
import json
import re
import secrets
from pathlib import Path
import struct
import sys
from time import perf_counter
import threading
import select
from typing import Protocol
from voice_profiles import VoiceProfileStore

_STREAM_SPEC = importlib.util.spec_from_file_location(
    "longmemory_cosy_stream_runtime", Path(__file__).with_name("stream_runtime.py"))
_stream_runtime = importlib.util.module_from_spec(_STREAM_SPEC)
_STREAM_SPEC.loader.exec_module(_stream_runtime)

try:
    _VOICE_SPEC = importlib.util.spec_from_file_location("cosyvoice_safe_observation",
        Path(__file__).resolve().parents[1] / "xiaozhi/voice_diagnostics.py")
    _voice_observation = importlib.util.module_from_spec(_VOICE_SPEC)
    _VOICE_SPEC.loader.exec_module(_voice_observation)
except (OSError, ImportError, AttributeError, TypeError):
    _voice_observation = None

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
REFERENCE_SPEAKER_ID = "longmemory-official-zero-shot-v1"
CAPABILITIES = {
    "contract_version": 2,
    "provider_id": "cosyvoice3",
    "display_name": "CosyVoice 3 0.5B",
    "locality": "local",
    "delivery_modes": ["buffered", "audio_stream"],
    "output_mime_types": ["audio/wav"],
    "controls": ["reference_voice", "style_prompt"],
    # 固定增量路径在token/模型调用边界协作取消；兼容路径在下一块写出时观察关闭。
    # 这不是逐采样抢占，不能冒充即时GPU中止。
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
        hidden_only: bool = True,
        model_streaming: bool = False,
        profile_root: Path | None = None,
        force_buffered_audio: bool = False,
        warm_selected_voice: bool = True,
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
        self._stream_cache: OrderedDict[str, tuple[bytes, ...]] = OrderedDict()
        self._profiles = VoiceProfileStore(profile_root or Path(__file__).resolve().parents[3])
        self._speaker_cache = OrderedDict()
        # 圆屏已经按自然标点收齐片段后播放。完整生成该片段可省去内部流式
        # Flow/HiFT 对累计前缀的重复计算；HTTP 仍沿用相同 WAV 长度前缀协议。
        # 保留显式恢复内部流式的开关，以便隔离对照与回退。
        self.model_streaming = model_streaming
        self.force_buffered_audio = force_buffered_audio
        load_started = perf_counter()
        self._model = CosyVoice3(str(model_dir), fp16=True)
        self.load_seconds = perf_counter() - load_started
        self._sample_rate = int(self._model.sample_rate)
        self.stream_runtime = _stream_runtime.install_stream_runtime(self._model.model)
        # 官方参考音频与提示词在服务生命周期内固定。CosyVoice 默认会在每次请求中
        # 重算提示词 token、语音特征、语音 token 和说话人向量；先注册为命名音色，
        # 后续推理即可复用预计算结果，同时仍保持原来的零样本音色。
        if not self._model.add_zero_shot_spk(
            PROMPT_TEXT, self._prompt_wav, REFERENCE_SPEAKER_ID
        ):
            raise RuntimeError("reference speaker registration failed")
        if REFERENCE_SPEAKER_ID not in self._model.list_available_spks():
            raise RuntimeError("reference speaker unavailable")
        runtime_model = getattr(self._model, "model", None)
        # 只跳过语音生成没有使用的文本词表输出；不改权重、精度或语音采样。
        # 适配器对源码与版本做严格检查，不兼容时自然使用原路径。
        self.runtime_optimization = None
        if hidden_only:
            from runtime_optimizations import install_qwen2_hidden_only
            encoder = getattr(getattr(runtime_model, "llm", None), "llm", None)
            self.runtime_optimization = install_qwen2_hidden_only(encoder)
        # 先安装输出等价优化，再观察四个阶段；不逐 token 计时，不做 CUDA 同步。
        # 计数包括暖机，固定合成的开销由请求前后的 health 差值取得。
        from runtime_diagnostics import install_runtime_diagnostics
        self.runtime_diagnostics = install_runtime_diagnostics(self._model)
        import transformers
        self.runtime_info = {
            "service_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "torch_version": str(torch.__version__),
            "transformers_version": str(transformers.__version__),
            "fp16": bool(runtime_model.fp16),
            "model_streaming": self.model_streaming,
            "text_frontend": str(getattr(getattr(self._model, "frontend", None), "text_frontend", "")),
            "torch_threads": torch.get_num_threads(),
            "interop_threads": torch.get_num_interop_threads(),
            "hidden_only": bool(self.runtime_optimization and self.runtime_optimization.applied),
            "optimization_reason": self.runtime_optimization.reason if self.runtime_optimization else "disabled",
            "incremental_audio_supported": self.stream_runtime.applied,
            "stream_runtime_reason": self.stream_runtime.reason,
            "force_buffered_audio": self.force_buffered_audio,
        }
        # 回复LRU只在这个已加载、不可热换权重的模型实例内存中存在。
        # 把模型版本、实现、声线全文摘要、文本、采样/编码及交付模式纳入键；
        # 不把个人回答持久化，已有缓存不能当作本轮流式推理的收益。
        self.audio_cache_identity = ('Fun-CosyVoice3-0.5B-2512', str(model_dir.resolve()),
                                     self.runtime_info['service_sha256'])
        stream_token_hop_len = getattr(runtime_model, "token_hop_len", None)
        if type(stream_token_hop_len) is not int or stream_token_hop_len <= 0:
            raise RuntimeError("stream token hop unavailable")
        # 上游流式实现会在产出音频后把实例字段从 25 逐步放大到 50/100；如果不在
        # 新请求前恢复，后续短句会等到整句完成才只返回一个块。保存模型初始值，
        # 不擅自使用低于训练 static_chunk_size 的分块长度。
        self.stream_token_hop_len = stream_token_hop_len
        self.reference_cached = True
        # 服务只有在懒初始化路径也跑过之后才宣告 ready，避免首位用户承担额外冷启动。
        warmup_started = perf_counter()
        self._generate(WARMUP_TEXT)
        self.warmup_seconds = perf_counter() - warmup_started
        self.selected_warmup_seconds = None
        self.selected_warmup_identity = None
        if warm_selected_voice and self._profiles.profile_path.is_file():
            self.prepare_selected_voice()

    def prepare_selected_voice(self):
        """明确准备当前选中声线和实际音频流，不把默认参考暖机冒充选中声线。

        只使用固定合成句，不缓存任意用户回答。修改声线后健康摘要显示未暖机，
        不在health读取或第一问中暗中重跑此维护动作。
        """
        _, _, identity = self._profiles.model_context()
        started = perf_counter()
        for _ in self.stream_chunks(WARMUP_TEXT, use_cache=False,
                model_streaming=self.stream_runtime.applied):
            pass
        if self._profiles.model_context()[2] != identity:
            raise RuntimeError('selected_voice_changed_during_warmup')
        self.selected_warmup_seconds = perf_counter() - started
        self.selected_warmup_identity = identity
        return self.selected_warmup_seconds

    def _prepare_stream(self) -> None:
        runtime_model = getattr(self._model, "model", None)
        if runtime_model is None:
            raise RuntimeError("stream runtime unavailable")
        runtime_model.token_hop_len = self.stream_token_hop_len

    def _voice_context(self, profile=None):
        """每个片段捕获不可变档案；后续保存不能改变正在生成的声音。"""
        if not hasattr(self, '_profiles'):
            return None
        selected, reference, digest = self._profiles.model_context(profile)
        if selected['reference_id'] is None and not selected['style']:
            return None
        prompt_wav = reference or self._prompt_wav
        if selected['style']:
            prompt = 'You are a helpful assistant. ' + selected['style'] + '<|endofprompt|>'
        else:
            prompt = 'You are a helpful assistant.<|endofprompt|>' + selected['transcript']
        speaker = 'longmemory-profile-' + digest
        if speaker not in self._speaker_cache:
            # 指令模式也注册自己的 prompt_text；不能复用带旧转写的缓存 speaker，
            # 因为上游 frontend_instruct2 会直接复用缓存的 prompt_text token。
            if not self._model.add_zero_shot_spk(prompt, prompt_wav, speaker):
                raise RuntimeError('voice reference registration failed')
            self._speaker_cache[speaker] = True
            while len(self._speaker_cache) > 8:
                old, _ = self._speaker_cache.popitem(last=False)
                self._model.frontend.spk2info.pop(old, None)
        else:
            self._speaker_cache.move_to_end(speaker)
        return {'digest': digest, 'prompt': prompt, 'wav': prompt_wav,
                'speaker': speaker, 'instruct': bool(selected['style'])}

    def _audio_key(self, text, context, mode):
        return (getattr(self, 'audio_cache_identity', ('fixed-model-instance',)),
                context['digest'] if context else 'official-reference-v1', text,
                getattr(self, '_sample_rate', 24000), 'WAV-PCM16-v1', mode)

    def _inference(self, text, context, *, model_streaming=None):
        streaming = self.model_streaming if model_streaming is None else model_streaming
        if context is None:
            return self._model.inference_zero_shot(text, PROMPT_TEXT, self._prompt_wav,
                zero_shot_spk_id=REFERENCE_SPEAKER_ID, stream=streaming)
        method = self._model.inference_instruct2 if context['instruct'] else self._model.inference_zero_shot
        return method(text, context['prompt'], context['wav'],
                      zero_shot_spk_id=context['speaker'], stream=streaming)

    def _generate(self, text: str, context=None) -> bytes:
        self._prepare_stream()
        chunks = []
        iterator = self._inference(text, context)
        try:
            for item in iterator:
                speech = item.get("tts_speech")
                if speech is None or speech.numel() == 0:
                    raise RuntimeError("empty audio chunk")
                chunks.append(speech.detach().cpu())
        finally:
            close = getattr(iterator, 'close', None)
            if callable(close):
                close()
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

    def stream_chunks(self, text: str, *, use_cache: bool = True, voice_profile=None,
                      model_streaming=None, cancel_event=None):
        """逐块交付音频；完全相同的近期回复可复用本次进程内结果。"""
        with self._lock:
            context = self._voice_context(voice_profile)
            streaming = self.model_streaming if model_streaming is None else model_streaming
            streaming = streaming and not getattr(self, 'force_buffered_audio', False)
            key = self._audio_key(text, context, 'incremental' if streaming else 'buffered')
            if use_cache:
                cached = self._stream_cache.pop(key, None)
                if cached is not None:
                    self._stream_cache[key] = cached
                    yield from cached
                    return
            self._prepare_stream()
            generated = []
            guard = getattr(self, 'stream_runtime', None)
            if guard is not None:
                guard.external_cancel = cancel_event
            iterator = self._inference(text, context, model_streaming=streaming)
            try:
                for item in iterator:
                    if cancel_event is not None and cancel_event.is_set():
                        raise _stream_runtime.StreamCancelled()
                    speech = item.get("tts_speech")
                    if speech is None:
                        raise RuntimeError("empty audio chunk")
                    chunk = self._wave_bytes(speech)
                    if use_cache or not streaming:
                        generated.append(chunk)
                    if streaming:
                        yield chunk
                if not streaming:
                    yield from generated
            finally:
                try:
                    close = getattr(iterator, 'close', None)
                    if callable(close):
                        close()
                finally:
                    if guard is not None:
                        guard.external_cancel = None
            if use_cache and generated:
                self._stream_cache[key] = tuple(generated)
                while len(self._stream_cache) > self._cache_entries:
                    self._stream_cache.popitem(last=False)

    def synthesize(self, text: str, *, use_cache: bool = True, voice_profile=None) -> bytes:
        with self._lock:
            context = self._voice_context(voice_profile)
            key = self._audio_key(text, context, 'complete-wav')
            if use_cache:
                cached = self._cache.pop(key, None)
                if cached is not None:
                    self._cache[key] = cached
                    return cached
            audio = self._generate(text, context)
            if use_cache:
                self._cache[key] = audio
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
        self.speech_requests = OrderedDict()
        self.speech_requests_lock = threading.Lock()


class CosyVoiceHandler(BaseHTTPRequestHandler):
    server: CosyVoiceHTTPServer

    def log_message(self, _format, *_args):
        # 不把合成文本写入长期日志。
        return

    def end_headers(self):
        request_id = getattr(self, "speech_request_id", None)
        if request_id is not None:
            self.send_header("X-Request-Id", request_id)
            if self.voice_round_id is not None:
                self.send_header("X-Voice-Round-Id", self.voice_round_id)
        super().end_headers()

    def _speech_stage(self, stage):
        try:
            with self.server.speech_requests_lock:
                row = self.server.speech_requests.setdefault(self.speech_request_id, {
                    "request_id": self.speech_request_id, "voice_round_id": self.voice_round_id,
                    "association": "authenticated_wrapper" if getattr(self, "speech_trace", None) else (
                        "local_caller_claim" if self.voice_round_id else "missing"),
                    "device_playback": "unconfirmed", "stages": [],
                })
                row["stages"].append(stage)
                while len(self.server.speech_requests) > 100:
                    self.server.speech_requests.popitem(last=False)
            trace = getattr(self, "speech_trace", None)
            if trace is not None:
                events = {"synthesis_entered": "tts_service_entered", "synthesis_returned": "tts_service_returned",
                          "response_written": "tts_service_written", "synthesis_failed": "tts_service_failed",
                          "client_disconnected": "tts_service_disconnected", "busy": "tts_service_busy"}
                if stage in events:
                    trace.event(events[stage])
        except Exception:
            pass

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
        body = {"ready": True, "provider": "cosyvoice3", "capabilities": CAPABILITIES,
                "voice_profile_contract_version": 1}
        body['generation_in_flight'] = self.server.generation_gate.locked()
        store = getattr(self.server.synthesizer, '_profiles', None)
        if store is not None:
            try:
                body['voice_profile_config_digest'] = store.profile()[1]
                body['voice_profile_config_state'] = 'valid'
            except (OSError, ValueError):
                body['voice_profile_config_state'] = 'invalid'
        for name in ("load_seconds", "warmup_seconds", "stream_token_hop_len"):
            value = getattr(self.server.synthesizer, name, None)
            if isinstance(value, (int, float)):
                body[name] = round(value, 3)
        reference_cached = getattr(self.server.synthesizer, "reference_cached", None)
        if isinstance(reference_cached, bool):
            body["reference_cached"] = reference_cached
        runtime_info = getattr(self.server.synthesizer, "runtime_info", None)
        if isinstance(runtime_info, dict):
            body["runtime"] = runtime_info
        diagnostics = getattr(self.server.synthesizer, "runtime_diagnostics", None)
        snapshot = getattr(diagnostics, "snapshot", None)
        if callable(snapshot):
            body["diagnostics"] = snapshot()
        guard = getattr(self.server.synthesizer, 'stream_runtime', None)
        if guard is not None:
            body['stream_runtime'] = guard.snapshot()
        body['selected_voice_warmup_seconds'] = getattr(self.server.synthesizer, 'selected_warmup_seconds', None)
        warmed = getattr(self.server.synthesizer, 'selected_warmup_identity', None)
        if warmed is not None and store is not None:
            try:
                body['selected_voice_warm'] = store.model_context()[2] == warmed
            except (OSError, ValueError):
                body['selected_voice_warm'] = False
        else:
            body['selected_voice_warm'] = False
        try:
            with self.server.speech_requests_lock:
                body["speech_requests"] = [dict(row, stages=list(row["stages"]))
                                           for row in reversed(self.server.speech_requests.values())]
        except Exception:
            body["speech_observation"] = "unavailable"
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
        self.speech_request_id = secrets.token_hex(12)
        supplied_round = self.headers.get("X-Voice-Round-Id", "")
        self.voice_round_id = supplied_round if re.fullmatch(r"[0-9a-f]{24}", supplied_round) else None
        self.speech_trace = None
        try:
            verified = _voice_observation.verified_round(self.headers) if _voice_observation else None
            if verified is not None:
                self.speech_trace = _voice_observation.VoiceRound(round_id=verified,
                    source="cosyvoice", request_id=self.speech_request_id)
        except Exception:
            pass
        self._speech_stage("request_received")
        try:
            return self._speech_post()
        except (BrokenPipeError, ConnectionResetError):
            self._speech_stage("client_disconnected")
            raise

    def _speech_post(self):
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
            or body.get('delivery_mode', 'buffered') not in ('incremental', 'buffered')
        ):
            self._json(400, {"error": "invalid_request"})
            return
        streaming = self.path == "/v1/audio/stream"
        if streaming != body.get("stream", False):
            self._json(400, {"error": "invalid_request"})
            return
        version2 = 'delivery_mode' in body
        if version2 and (not streaming or (body['delivery_mode'] == 'incremental'
                and not getattr(getattr(self.server.synthesizer, 'stream_runtime', None), 'applied', False))):
            self._json(409, {'error': 'incremental_stream_unavailable'})
            return
        if not self.server.generation_gate.acquire(blocking=False):
            self._speech_stage("busy")
            self._json(503, {"error": "busy"})
            return
        try:
            self._speech_stage("synthesis_entered")
            kwargs = {'use_cache': body.get('cache', True)}
            if 'voice_profile' in body:
                # 仅用于网页草稿试听：完整白名单校验仍在 synthesizer 的档案库中。
                kwargs['voice_profile'] = body['voice_profile']
            if streaming:
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.longmemory.wav-chunks")
                self.send_header("Cache-Control", "no-store")
                self.send_header('X-LongMemory-Voice-Profile', '1')
                if version2:
                    self.send_header('X-LongMemory-Audio-Stream', '2')
                # HTTP/1.0 会以连接关闭标记响应结束。每个 WAV 前的无符号大端长度
                # 让客户端不依赖 TCP 分包边界，最大块仍由客户端再次限制。
                self.end_headers()
                cancelled = threading.Event()
                finished = threading.Event()
                def watch_peer():
                    while not finished.wait(.02):
                        try:
                            ready, _, _ = select.select([self.connection], [], [], 0)
                            if ready and self.connection.recv(1, __import__('socket').MSG_PEEK) == b'':
                                cancelled.set()
                                return
                        except OSError:
                            cancelled.set()
                            return
                watcher = threading.Thread(target=watch_peer, name='cosyvoice-peer-close', daemon=True)
                if version2:
                    kwargs.update(model_streaming=body['delivery_mode'] == 'incremental', cancel_event=cancelled)
                    watcher.start()
                iterator = self.server.synthesizer.stream_chunks(text.strip(), **kwargs)
                try:
                    for chunk in iterator:
                        if cancelled.is_set():
                            raise _stream_runtime.StreamCancelled()
                        self.wfile.write(struct.pack("!I", len(chunk)))
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    if version2:
                        self.wfile.write(struct.pack('!I', 0))
                        self.wfile.flush()
                finally:
                    cancelled.set()
                    try:
                        close = getattr(iterator, 'close', None)
                        if callable(close):
                            close()
                    finally:
                        finished.set()
                        if version2:
                            watcher.join(timeout=.2)
                self._speech_stage("synthesis_returned")
                self._speech_stage("response_written")
                return
            audio = self.server.synthesizer.synthesize(text.strip(), **kwargs)
            self._speech_stage("synthesis_returned")
        except (BrokenPipeError, ConnectionResetError, _stream_runtime.StreamCancelled):
            self._speech_stage("client_disconnected")
            # 用户打断或 Xiaozhi 退出时，关闭生成器即可释放模型锁；无需把正常取消
            # 记录成合成故障，也不能在已经发送部分音频后回写 JSON。
            return
        except Exception:
            self._speech_stage("synthesis_failed")
            if not streaming:
                self._json(500, {"error": "synthesis_failed"})
            return
        finally:
            self.server.generation_gate.release()
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(audio)))
        self.send_header("Cache-Control", "no-store")
        self.send_header('X-LongMemory-Voice-Profile', '1')
        self.end_headers()
        self.wfile.write(audio)
        self._speech_stage("response_written")


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
    parser.add_argument("--no-hidden-only", action="store_true", help="恢复上游 Qwen 完整文本输出路径")
    parser.add_argument("--model-streaming", action="store_true", help="恢复模型内部流式分块生成")
    parser.add_argument('--force-buffered-audio', action='store_true', help='回退为完整片段生成；不改声线或音频精度')
    parser.add_argument('--skip-selected-warmup', action='store_true', help='隔离对照：只预热默认参考，不预热选中声线')
    parser.add_argument("--system-qos", action="store_true", help="恢复 Windows 默认进程调度，不显式申请 HighQoS")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口必须在 1024–65535")
    # 日用后台进程在本机对照中明显慢于实时；仅对当前声音服务声明需要
    # HighQoS，避免依赖窗口前后台状态。必须早于模型加载及工作线程创建。
    # 不修改系统电源计划、CPU 优先级、模型或 Memory Core；失败继续原路径。
    from windows_qos import apply_current_process_high_qos
    windows_qos = (
        {"applied": False, "reason": "disabled", "before": None, "after": None}
        if args.system_qos else apply_current_process_high_qos()
    )
    synthesizer = CosyVoiceSynthesizer(
        args.source_root, args.model_dir,
        hidden_only=not args.no_hidden_only, model_streaming=args.model_streaming,
        force_buffered_audio=args.force_buffered_audio,
        warm_selected_voice=not args.skip_selected_warmup,
    )
    synthesizer.runtime_info["windows_qos"] = windows_qos
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
