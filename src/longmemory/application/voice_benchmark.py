"""日常 TTS 测试台的合成用例和缓冲式测量。

它不使用真实聊天、记忆或用户音频。当前适配器只有在整段音频返回后才能交付，
所以首个可用音频时间与完成时间相同；未来流式实现会使用同一结果字段记录真正
的首块时间。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import math
from time import monotonic
import wave


@dataclass(frozen=True, slots=True)
class TTSBenchmarkCase:
    id: str
    label: str
    text: str
    purpose: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "text": self.text,
            "purpose": self.purpose,
            "text_chars": len(self.text),
        }


CASES = (
    TTSBenchmarkCase("short_reply", "短回复", "好呀，我们慢慢来。", "观察首句等待"),
    TTSBenchmarkCase(
        "numbers_time",
        "数字与时间",
        "明天下午一点零五分，我会提醒你休息十分钟。",
        "检查中文数字、时间和断句",
    ),
    TTSBenchmarkCase(
        "mixed_language",
        "中英混合",
        "LongMemory 已连接，今天的计划是完成 TTS 流式测试。",
        "检查中英文切换和字母发音",
    ),
    TTSBenchmarkCase(
        "expressive",
        "陪伴语气",
        "你回来啦。今天辛苦了，如果愿意的话，就把烦心事慢慢说给我听吧。",
        "主观比较自然度、停顿和表达",
    ),
)


def case_by_id(case_id: str) -> TTSBenchmarkCase | None:
    return next((item for item in CASES if item.id == case_id), None)


def inspect_wave(audio: bytes, content_type: str) -> dict[str, object] | None:
    """只分析标准 PCM WAV；MP3 等格式保留为空，不安装额外解码依赖。"""

    if content_type != "audio/wav" or len(audio) > 8 * 1024 * 1024:
        return None
    try:
        with wave.open(BytesIO(audio), "rb") as source:
            sample_rate = source.getframerate()
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            frames = source.getnframes()
            if sample_rate <= 0 or channels <= 0 or sample_width != 2 or frames <= 0:
                return None
            raw = source.readframes(frames)
    except (EOFError, wave.Error):
        return None

    # 最多抽取约 16000 个 16 位样本，质量门只识别近静音，不承担音质评分。
    values = memoryview(raw).cast("h")
    stride = max(1, len(values) // 16000)
    sampled = values[::stride]
    if not sampled:
        return None
    peak = max(abs(value) for value in sampled) / 32768
    rms = math.sqrt(sum(value * value for value in sampled) / len(sampled)) / 32768
    return {
        "duration_seconds": round(frames / sample_rate, 4),
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "sample_width_bits": 16,
        "rms": round(rms, 6),
        "peak": round(peak, 6),
        "near_silent": rms < 0.0015 or peak < 0.015,
    }


async def measure_buffered_speech(backend, case: TTSBenchmarkCase) -> dict[str, object]:
    """执行一次、不重试；错误由既有声音 API 转换为安全故障类别。"""

    started_at = datetime.now(timezone.utc).isoformat()
    started = monotonic()
    audio, content_type = await backend.speech(case.text)
    completed_ms = round((monotonic() - started) * 1000, 2)
    return {
        "schema_version": 1,
        "case": case.as_dict(),
        "started_at": started_at,
        "adapter_delivery": "buffered",
        "first_audio_available_ms": completed_ms,
        "completed_ms": completed_ms,
        "audio_bytes": len(audio),
        "content_type": content_type,
        "wave": inspect_wave(audio, content_type),
        "limitations": [
            "不含浏览器解码与播放时间",
            "不含圆屏网络、Opus 编码和扬声器开始播放时间",
            "缓冲式适配器无法测量模型原生首包",
        ],
    }
