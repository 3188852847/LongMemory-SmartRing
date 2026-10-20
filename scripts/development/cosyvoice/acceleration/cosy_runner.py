"""供主会话/AD接入的真实Cosy PCM测量接口；本模块不加载模型或连接服务。"""

from __future__ import annotations

from array import array
from io import BytesIO
import inspect
from pathlib import Path
import sys
import threading
import wave

from .adapters import ExperimentContext
from .benchmark import AudioChunk

ROOT = Path(__file__).resolve().parents[4]
SYNTHETIC_TEXTS = {
    "short": "好呀，我们慢慢来。",
    "numbers": "明天下午一点零五分，我会提醒你休息十分钟。",
    "mixed": "今天的 meeting 安排在下午三点，先检查 Wi-Fi 和 Python 环境。",
}


def evaluation_contract() -> dict:
    return dict(schema_version=1, status="needs_isolated_validation", dependencies_download_required=False,
                gpu_window_required=True, gpu_work_performed=False,
                producer_matrix=dict(cases=list(SYNTHETIC_TEXTS), modes=["buffered", "incremental"], seeds=[17, 29], concurrency=1,
                                     measured_syntheses=12, warmup_separate=True, cache_enabled=False),
                ad_consumer_matrix=dict(policies=["current", "adaptive"], reuse_same_producer_trace=True,
                                        protocol_support_and_instance_availability_separate=True,
                                        required_observations=["first_effective_answer_pcm_ms", "first_opus_ms", "buffer_ready_ms",
                                                               "underrun_count", "worst_gap_ms", "cancel_requested_ms",
                                                               "last_delivered_frame_ms", "native_cleanup_ms", "followup_usable"]),
                cannot_infer=["physical_device_playback", "end_of_speech_to_effective_answer", "voice_quality", "false_interrupts"],
                note="model runner excludes AD playback policy; adaptive benefit must be measured in AD actual consumer")


def _service_origin(synth):
    return Path(inspect.getfile(type(synth))).resolve()


def make_runner(synth, *, context: ExperimentContext, model_streaming: bool):
    """传入已由调用方独占加载的本树合成器；每次重新生成合成文字并关闭缓存。

    主会话整合AD以后由整合树使用同一接口；AG不导入别树service，不新建服务器。
    逐WAV转PCM的耗时属于本次可用PCM边界，不能把HTTP头或等待提示计作首答。
    """
    if not context.isolated_instance or not context.window_id.strip():
        raise ValueError("exclusive_gpu_window_required")
    if _service_origin(synth) != ROOT / "scripts/development/cosyvoice/service.py":
        raise ValueError("synthesizer_source_not_owned_worktree")
    if not getattr(getattr(synth, "stream_runtime", None), "applied", False):
        raise ValueError("native_cancel_adapter_required")
    parameters = inspect.signature(synth.stream_chunks).parameters
    if not {"use_cache", "model_streaming", "cancel_event"}.issubset(parameters):
        raise ValueError("stream_chunks_contract_changed")
    lock = getattr(synth, "_ag_seeded_benchmark_lock", None)
    if lock is None:
        lock = threading.Lock()
        synth._ag_seeded_benchmark_lock = lock

    def runner(case_id, seed, cancel_event):
        if case_id not in SYNTHETIC_TEXTS:
            raise ValueError("synthetic_case_required")
        if not lock.acquire(blocking=False):
            raise RuntimeError("concurrent_seeded_model_use_forbidden")
        iterator = None
        try:
            synth._torch.manual_seed(seed)
            iterator = iter(synth.stream_chunks(SYNTHETIC_TEXTS[case_id], use_cache=False,
                                                model_streaming=model_streaming, cancel_event=cancel_event))
            for data in iterator:
                if cancel_event.is_set():
                    return
                with wave.open(BytesIO(data), "rb") as source:
                    if source.getnchannels() != 1 or source.getsampwidth() != 2:
                        raise ValueError("mono_pcm16_wav_required")
                    rate = source.getframerate()
                    pcm = array("h", source.readframes(source.getnframes()))
                    if sys.byteorder != "little":
                        pcm.byteswap()
                    yield AudioChunk(tuple(value / 32768 for value in pcm), rate)
        finally:
            try:
                if iterator is not None and hasattr(iterator, "close"):
                    iterator.close()
            finally:
                lock.release()
    return runner
