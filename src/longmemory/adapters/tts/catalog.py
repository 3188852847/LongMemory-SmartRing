"""当前已经接通的 TTS 能力目录。

候选模型只有完成本机适配和验证后才能加入；因此这里暂不登记 sanoTTS、
CosyVoice 或 GPT-SoVITS。
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
}


def capabilities_for(provider_id: str) -> TTSCapabilities | None:
    """未知或尚未适配的后端返回 ``None``，不猜测供应商能力。"""

    return _CAPABILITIES.get(provider_id)
