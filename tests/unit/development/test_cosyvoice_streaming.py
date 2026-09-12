"""验证本机分块协议解析；不加载 CosyVoice、CUDA 或 Xiaozhi。"""

from io import BytesIO
import importlib.util
from pathlib import Path
import struct

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/cosyvoice_streaming.py"
SPEC = importlib.util.spec_from_file_location("cosyvoice_streaming_test", SCRIPT)
streaming = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(streaming)


def framed(*chunks):
    return b"".join(struct.pack("!I", len(chunk)) + chunk for chunk in chunks)


def test_iter_wav_chunks_preserves_boundaries():
    assert list(streaming.iter_wav_chunks(BytesIO(framed(b"first", b"second")))) == [
        b"first", b"second",
    ]


@pytest.mark.parametrize("body", [
    b"\x00\x00", struct.pack("!I", 0), struct.pack("!I", streaming.MAX_CHUNK_BYTES + 1),
    struct.pack("!I", 5) + b"no",
])
def test_iter_wav_chunks_rejects_truncated_or_unbounded_frames(body):
    with pytest.raises((EOFError, ValueError)):
        list(streaming.iter_wav_chunks(BytesIO(body)))
