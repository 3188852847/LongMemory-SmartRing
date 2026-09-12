"""当前已经接通的 TTS 能力目录。

候选模型只有完成本机适配和验证后才能加入；GPT-SoVITS 尚未登记。
"""

from longmemory.adapters.tts.contracts import TTSCapabilities


_CAPABILITIES = {
    "edge": TTSCapabilities(
        provider_id="edge",
        display_name="EdgeTTS",
        locality="remote",
        delivery_modes=("buffered",),
        output_mime_types=("audio/mpeg",),
        controls=("voice_selection",),
    ),
    "voxcpm2": TTSCapabilities(
        provider_id="voxcpm2",
        display_name="VoxCPM2",
        locality="local",
        delivery_modes=("buffered",),
        output_mime_types=("audio/wav",),
        controls=("reference_voice", "style_prompt"),
    ),
    "sanotts": TTSCapabilities(
        provider_id="sanotts",
        display_name="sanoTTS 中文小雅",
        locality="local",
        delivery_modes=("buffered",),
        output_mime_types=("audio/wav",),
        controls=("speaking_rate",),
    ),
    "cosyvoice3": TTSCapabilities(
        provider_id="cosyvoice3",
        display_name="CosyVoice 3 0.5B",
        locality="local",
        # 模型原生流式，但当前 Xiaozhi CustomTTS 等待完整 HTTP 正文。
        delivery_modes=("buffered",),
        output_mime_types=("audio/wav",),
    ),
}


def capabilities_for(provider_id: str) -> TTSCapabilities | None:
    """未知或尚未适配的后端返回 ``None``，不猜测供应商能力。"""

    return _CAPABILITIES.get(provider_id)
