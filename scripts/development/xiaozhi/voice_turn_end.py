"""音频话轮结束判定：默认关闭，显式启用后接管自然话轮端点。

只拥有语音适配边界。无网络、磁盘、记忆、模型网关、播放或设备操作。
on_event(connection, event) 必须同步、快速；调用方负责把音频版本绑定到真实文本。
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
import math
import threading
import time


STATE = "_longmemory_voice_turn_end"


@dataclass(frozen=True)
class TurnEndConfig:
    mode: str = "off"
    silence_ms: int = 300
    confirm_ms: int = 420
    max_silence_ms: int = 1800
    inference_timeout_ms: int = 150
    retry_ms: int = 300
    max_attempts: int = 4
    threshold: float = 0.7
    min_audio_ms: int = 960

    def __post_init__(self):
        if (self.mode not in {"off", "shadow", "enabled"}
                or not 200 <= self.silence_ms <= self.confirm_ms <= self.max_silence_ms <= 3000
                or not 10 <= self.inference_timeout_ms <= 500
                or not 100 <= self.retry_ms <= 1000 or not 1 <= self.max_attempts <= 8
                or not 0.5 <= self.threshold <= 1 or not 960 <= self.min_audio_ms <= 8000):
            raise ValueError("invalid_turn_end_limits")


class InferenceSlot:
    """所有连接共用一个真实线程工位，超时不释放仍在运行的同步推理。

    不可杀线程只占一个槽；后续请求立即 busy，不积压任务。线程最终返回前不
    再加载/排队。超时只取消结果权限，不宣称中止了底层模型。
    """

    def __init__(self, detector):
        self.detector = detector
        self.lock = threading.Lock()

    def start(self, pcm):
        if self.detector is None:
            return None, "unavailable"
        if not self.lock.acquire(blocking=False):
            return None, "busy"

        def run():
            try:
                value = self.detector.predict(pcm)
                if type(value) not in {float, int} or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("invalid_turn_end_probability")
                return float(value)
            finally:
                self.lock.release()

        try:
            return asyncio.get_running_loop().run_in_executor(None, run), "started"
        except BaseException:
            self.lock.release()
            raise


class TurnEndState:
    def __init__(self, config, slot, emit=None, clock=time.monotonic):
        self.config, self.slot, self.emit, self.clock = config, slot, emit, clock
        self.turn_id = 0
        self.audio_revision = 0
        self.cancel_epoch = 0
        self.counts = Counter()
        self.closed = False
        self._clear()

    def _clear(self):
        self.voice_stamp = None
        self.in_pause = False
        self.attempts = 0
        self.next_attempt_ms = self.config.silence_ms
        self.pending = None
        self.probability = None
        self.has_result = False
        self.failed = False
        self.provisional = False
        self.confirmed = False
        self.latest_status = "idle"

    def _event(self, kind, reason, silence_ms=0, *, authoritative=False):
        self.counts[kind] += 1
        event = {"version": 1, "type": kind,
                 "signal": {"provisional": "eou", "continued": "continued_speech",
                            "confirmed": "confirmed_turn", "cancel": "cancel"}[kind],
                 "turn_id": self.turn_id, "audio_revision": self.audio_revision,
                 "transcript_revision": None, "cancel_epoch": self.cancel_epoch,
                 "mode": self.config.mode, "authoritative": authoritative,
                 "reason": reason, "silence_ms": round(silence_ms)}
        if self.emit is not None:
            try:
                self.emit(event)
            except Exception:
                self.counts["callback_failed"] += 1

    def cancel(self, reason="reset", *, close=False):
        if not self.confirmed and (self.in_pause or self.pending is not None):
            self.cancel_epoch += 1
            self._event("cancel", reason, authoritative=self.config.mode == "enabled")
        self.turn_id += 1
        self.audio_revision = 0
        self._clear()
        self.closed = self.closed or close

    def _invalidate(self, silence_ms):
        self.cancel_epoch += 1
        self._event("cancel", "speech_resumed", silence_ms,
                    authoritative=self.config.mode == "enabled")
        self.audio_revision += 1
        self.pending = None  # 真实工位仍由线程持有；旧结果不再有提交权限。
        self.probability = None
        self.has_result = False
        self.provisional = False
        self.confirmed = False
        self.failed = False
        self.in_pause = False
        self.next_attempt_ms = self.config.silence_ms
        self._event("continued", "speech_resumed", 0,
                    authoritative=self.config.mode == "enabled")

    def observe(self, *, pcm, audio_have_voice, voice_stamp, silence_ms, upstream_stop):
        """每帧同步调用，不等待推理；返回这一帧是否可让上游正式提交。

        pcm 是当前完整话轮的末尾至多八秒，正式 ASR 始终保留完整输入。
        只有有效分数可改变端点；失败/不可用/繁忙回到原静音端点。
        """
        if self.closed or self.config.mode == "off":
            return upstream_stop
        if audio_have_voice or (self.voice_stamp is not None and voice_stamp != self.voice_stamp):
            if self.in_pause or self.pending is not None or self.provisional:
                self._invalidate(silence_ms)
            self.voice_stamp = voice_stamp
            return False if self.config.mode == "enabled" else upstream_stop
        self.voice_stamp = voice_stamp
        if self.confirmed:
            return upstream_stop
        if len(pcm) < self.config.min_audio_ms * 32 or not pcm or len(pcm) % 2:
            return upstream_stop
        self.in_pause = True
        if self.pending is not None:
            future, started = self.pending
            # 即便线程已完成，过期结果也不能在迟到的帧上重新取得权限。
            if (self.clock() - started) * 1000 > self.config.inference_timeout_ms:
                self.pending = None
                self.failed = True
                self.latest_status = "timeout"
                self.counts["timeout"] += 1
            elif future.done():
                self.pending = None
                try:
                    self.probability = future.result()
                    self.has_result = True
                    self.latest_status = "complete" if self.probability >= self.config.threshold else "incomplete"
                except Exception:
                    self.failed = True
                    self.latest_status = "failed"
                    self.counts["failed"] += 1
        if (self.pending is None and not self.failed and self.probability is None
                and silence_ms >= self.next_attempt_ms and self.attempts < self.config.max_attempts):
            future, status = self.slot.start(pcm[-256000:])
            self.latest_status = status
            if future is None:
                self.failed = True
                self.counts[status] += 1
            else:
                # 消费异常，避免超时/续说丢弃 Future 后出现未取回异常日志。
                future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
                self.pending = (future, self.clock())
                self.attempts += 1
                self.counts["started"] += 1
                self.next_attempt_ms = silence_ms + self.config.retry_ms
        complete = self.probability is not None and self.probability >= self.config.threshold
        if complete and not self.provisional:
            self.provisional = True
            self._event("provisional", "model_complete", silence_ms)
        reason = None
        if complete and silence_ms >= self.config.confirm_ms:
            reason = "model_complete"
        elif silence_ms >= self.config.max_silence_ms and self.has_result and not self.failed:
            reason = "silence_budget"
        elif upstream_stop and (self.failed or not self.has_result):
            reason = "legacy_fallback"
        if reason is not None:
            self.confirmed = True
            self._event("confirmed", reason, silence_ms,
                        authoritative=self.config.mode == "enabled")
        # 低分定期重新看全话轮，不把多次静音当成新的话轮/预算。
        if (not complete and self.probability is not None and silence_ms >= self.next_attempt_ms
                and self.attempts < self.config.max_attempts):
            self.probability = None
        return bool(reason) if self.config.mode == "enabled" else upstream_stop

    def snapshot(self):
        return {"version": 1, "mode": self.config.mode, "turn_id": self.turn_id,
                "audio_revision": self.audio_revision, "cancel_epoch": self.cancel_epoch,
                "latest_status": self.latest_status, "counts": dict(self.counts)}


def install_voice_turn_end(connection_class, asr_provider_class, *, detector=None,
                           config=None, on_event=None, calibration_approved=False):
    """AI 接线入口：先装 ASR 预取，再装本模块；仅 LOCAL auto/realtime。

    enabled 由组合层显式选择。calibration_approved仅记录真实中文验收状态，
    不将已授权的功能体验误写成校准通过，也不再阻挡显式启用。
    回退为重启时 mode=off，不在已打补丁的进程内动态切换。
    """
    config = config or TurnEndConfig()
    if config.mode == "off":
        return {"mode": "off", "installed": False}
    if getattr(asr_provider_class, "_longmemory_turn_end_installed", False):
        raise RuntimeError("turn_end_already_installed_restart_required")
    original_receive = asr_provider_class.receive_audio
    original_reset = connection_class.reset_audio_states
    original_close = connection_class.close
    slot = InferenceSlot(detector)

    def state_for(connection):
        state = getattr(connection, STATE, None)
        if state is None:
            emit = (lambda event: on_event(connection, event)) if on_event else None
            state = TurnEndState(config, slot, emit)
            setattr(connection, STATE, state)
        return state

    async def receive_audio(provider, connection, pcm_frame, audio_have_voice):
        stamp = getattr(connection, "vad_last_voice_time", None)
        supported = (getattr(getattr(provider, "interface_type", None), "value", None) == "LOCAL"
                     and getattr(connection, "client_listen_mode", None) in {"auto", "realtime"}
                     and not getattr(connection, "voiceprint_provider", None)
                     and not getattr(connection, "client_is_speaking", False)
                     and getattr(connection, "client_have_voice", False)
                     and not connection.stop_event.is_set()
                     and isinstance(pcm_frame, bytes) and len(pcm_frame) == 1920
                     and type(stamp) in {int, float} and math.isfinite(stamp)
                     and 0 < stamp <= time.time() * 1000
                     and time.time() * 1000 - stamp <= 30000)
        if not supported:
            state = getattr(connection, STATE, None)
            if state is not None:
                state.cancel("unsupported")
            return await original_receive(provider, connection, pcm_frame, audio_have_voice)
        audio = getattr(connection, "asr_audio", [])
        if not all(isinstance(frame, bytes) and len(frame) == 1920 for frame in audio[-134:]):
            state = getattr(connection, STATE, None)
            if state is not None:
                state.cancel("unsupported")
            return await original_receive(provider, connection, pcm_frame, audio_have_voice)
        # 单帧预先决策，上游随后只追加一次，原 ASR/预取仍取得完整相同字节。
        state = state_for(connection)
        pcm = b"".join(audio[-133:] + [pcm_frame])[-256000:]
        silence_ms = time.time() * 1000 - stamp
        upstream_stop = bool(connection.client_voice_stop)
        decision = state.observe(pcm=pcm, audio_have_voice=bool(audio_have_voice),
                                 voice_stamp=stamp, silence_ms=silence_ms,
                                 upstream_stop=upstream_stop)
        if config.mode == "enabled":
            connection.client_voice_stop = decision
        return await original_receive(provider, connection, pcm_frame, audio_have_voice)

    def reset_audio_states(connection):
        state = getattr(connection, STATE, None)
        if state is not None:
            state.cancel("reset")
        return original_reset(connection)

    async def close(connection, *args, **kwargs):
        state = getattr(connection, STATE, None)
        if state is not None:
            state.cancel("closed", close=True)
        return await original_close(connection, *args, **kwargs)

    asr_provider_class.receive_audio = receive_audio
    asr_provider_class._longmemory_turn_end_installed = True
    connection_class.reset_audio_states = reset_audio_states
    connection_class.close = close
    connection_class._longmemory_voice_turn_end_snapshot = lambda conn: (
        getattr(conn, STATE).snapshot() if hasattr(conn, STATE) else {"version": 1, "mode": config.mode})
    return {"mode": config.mode, "installed": True, "model_available": detector is not None,
            "calibration_approved": bool(calibration_approved)}
