"""TTS V2 的框架无关契约。

这里描述项目实际接通的能力，而不是底层模型论文或演示页面宣称的能力。
例如模型原生支持流式，但适配器仍等待完整 WAV 时，``delivery_modes`` 只能写
``buffered``。这让控制台、启动器和以后的小智流式提供器使用同一组事实。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Iterable, Protocol


_DELIVERY_MODES = frozenset({"buffered", "audio_stream"})
_LOCALITIES = frozenset({"local", "remote", "browser", "device"})
_CANCELLATION_MODES = frozenset({"none", "cooperative"})
_CONTROL_NAMES = frozenset({
    "voice_selection",
    "reference_voice",
    "style_prompt",
    "speaking_rate",
    "volume",
    "emotion",
})


@dataclass(frozen=True, slots=True)
class TTSCapabilities:
    """一个已接入后端在当前适配器中的真实能力清单。"""

    provider_id: str
    display_name: str
    locality: str
    delivery_modes: tuple[str, ...]
    output_mime_types: tuple[str, ...]
    controls: tuple[str, ...] = ()
    cancellation: str = "none"
    max_text_chars: int = 600
    contract_version: int = 2

    def __post_init__(self) -> None:
        if self.contract_version != 2:
            raise ValueError("unsupported TTS contract version")
        if not self.provider_id or not self.display_name:
            raise ValueError("provider identity is required")
        if self.locality not in _LOCALITIES:
            raise ValueError("unsupported TTS locality")
        if not self.delivery_modes or not set(self.delivery_modes) <= _DELIVERY_MODES:
            raise ValueError("unsupported TTS delivery mode")
        if not self.output_mime_types or any(
            not value.startswith("audio/") for value in self.output_mime_types
        ):
            raise ValueError("audio MIME type is required")
        if not set(self.controls) <= _CONTROL_NAMES:
            raise ValueError("unsupported TTS control")
        if self.cancellation not in _CANCELLATION_MODES:
            raise ValueError("unsupported TTS cancellation mode")
        if self.max_text_chars < 1:
            raise ValueError("max_text_chars must be positive")

    @property
    def streams_audio(self) -> bool:
        return "audio_stream" in self.delivery_modes

    def as_dict(self) -> dict[str, object]:
        """生成稳定、可直接公开给本机控制台的 JSON 数据。"""

        return {
            "contract_version": self.contract_version,
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "locality": self.locality,
            "delivery_modes": list(self.delivery_modes),
            "output_mime_types": list(self.output_mime_types),
            "controls": list(self.controls),
            "cancellation": self.cancellation,
            "max_text_chars": self.max_text_chars,
        }


@dataclass(frozen=True, slots=True)
class SynthesisRequest:
    """进入 TTS 后端的最小请求；不允许携带任意模型路径或供应商参数。"""

    text: str
    voice_id: str | None = None
    speaking_rate: float = 1.0
    style: str | None = None

    def __post_init__(self) -> None:
        if not self.text.strip() or len(self.text) > 600:
            raise ValueError("invalid synthesis text")
        if self.voice_id is not None and (not self.voice_id or len(self.voice_id) > 120):
            raise ValueError("invalid voice id")
        if not 0.5 <= self.speaking_rate <= 2.0:
            raise ValueError("invalid speaking rate")
        if self.style is not None and len(self.style) > 200:
            raise ValueError("invalid style prompt")


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """流式提供器交付的有序音频块；整段模式也可只返回一个终块。"""

    data: bytes
    mime_type: str
    sequence: int
    final: bool = False

    def __post_init__(self) -> None:
        if not self.data or not self.mime_type.startswith("audio/") or self.sequence < 0:
            raise ValueError("invalid audio chunk")


@dataclass(slots=True)
class CancellationToken:
    """跨线程协作取消信号；只有声明 cooperative 的适配器才能承诺响应。"""

    _event: Event = field(default_factory=Event, repr=False)

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class TTSProvider(Protocol):
    """后续 sanoTTS、CosyVoice 与现有后端共同实现的最小接口。"""

    @property
    def capabilities(self) -> TTSCapabilities: ...

    def synthesize(
        self, request: SynthesisRequest, cancellation: CancellationToken
    ) -> Iterable[AudioChunk]: ...
