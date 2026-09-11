"""可替换 TTS（文本转语音）适配器的公共边界。"""

from longmemory.adapters.tts.catalog import capabilities_for
from longmemory.adapters.tts.contracts import (
    AudioChunk,
    CancellationToken,
    SynthesisRequest,
    TTSCapabilities,
    TTSProvider,
)

__all__ = [
    "AudioChunk",
    "CancellationToken",
    "SynthesisRequest",
    "TTSCapabilities",
    "TTSProvider",
    "capabilities_for",
]
