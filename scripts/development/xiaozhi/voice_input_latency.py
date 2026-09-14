"""补充圆屏停嘴、VAD 端点和 ASR 处理的脱敏计时。

不保存音频、识别文本或设备标识。计时只暂存在连接对象上，并由紧随其后的顶层
chat 轮次领取；超过十秒的孤立结果自动失效，避免串到下一轮内部提示。
"""

import time


PENDING_SECONDS = 10


def install_voice_input_latency(asr_base_module):
    if getattr(asr_base_module, "_longmemory_input_latency_installed", False):
        return
    provider_class = asr_base_module.ASRProviderBase
    original_handle = provider_class.handle_voice_stop
    original_start = asr_base_module.startToChat

    async def handle_voice_stop(provider, connection, audio_task):
        now_wall_ms = time.time() * 1000
        last_voice_ms = getattr(connection, "vad_last_voice_time", 0)
        endpoint_ms = None
        if type(last_voice_ms) in {int, float} and 0 < last_voice_ms <= now_wall_ms:
            candidate = round(now_wall_ms - last_voice_ms)
            if 0 <= candidate <= 30_000:
                endpoint_ms = candidate
        connection._longmemory_voice_input_active = {
            "started": time.perf_counter(), "vad_endpoint_ms": endpoint_ms,
        }
        try:
            return await original_handle(provider, connection, audio_task)
        finally:
            connection.__dict__.pop("_longmemory_voice_input_active", None)

    async def start_to_chat(connection, text):
        active = getattr(connection, "_longmemory_voice_input_active", None)
        if isinstance(active, dict):
            elapsed = max(0, round((time.perf_counter() - active["started"]) * 1000))
            connection._longmemory_voice_input_pending = {
                "expires_at": time.perf_counter() + PENDING_SECONDS,
                "input_timings_ms": {
                    "vad_endpoint_ms": active.get("vad_endpoint_ms"),
                    "asr_processing_ms": elapsed,
                },
            }
        return await original_start(connection, text)

    provider_class.handle_voice_stop = handle_voice_stop
    asr_base_module.startToChat = start_to_chat
    asr_base_module._longmemory_input_latency_installed = True

