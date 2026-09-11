import pytest

from longmemory.adapters.tts import (
    AudioChunk,
    CancellationToken,
    SynthesisRequest,
    capabilities_for,
)


def test_current_catalog_reports_delivered_not_theoretical_capabilities():
    edge = capabilities_for("edge")
    vox = capabilities_for("voxcpm2")

    assert edge is not None and edge.as_dict()["locality"] == "remote"
    assert edge.streams_audio is False
    assert vox is not None and vox.as_dict()["controls"] == [
        "reference_voice",
        "style_prompt",
    ]
    assert vox.as_dict()["cancellation"] == "none"
    assert capabilities_for("planned-but-not-integrated") is None


def test_request_chunk_and_cancellation_have_strict_small_contracts():
    request = SynthesisRequest(text=" 你好 ", speaking_rate=1.25, style="温柔")
    chunk = AudioChunk(data=b"pcm", mime_type="audio/pcm", sequence=0, final=True)
    cancellation = CancellationToken()

    assert request.text == " 你好 " and chunk.final is True
    assert cancellation.cancelled is False
    cancellation.cancel()
    assert cancellation.cancelled is True

    with pytest.raises(ValueError):
        SynthesisRequest(text="")
    with pytest.raises(ValueError):
        SynthesisRequest(text="有效", speaking_rate=3)
    with pytest.raises(ValueError):
        AudioChunk(data=b"", mime_type="audio/pcm", sequence=0)
