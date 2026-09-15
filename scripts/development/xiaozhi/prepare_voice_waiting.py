"""显式准备两条固定同声线提示；只调用本机 CosyVoice，不接收任意文本。"""

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import struct
import sys
from urllib.request import Request, build_opener, ProxyHandler

from voice_waiting import ASSET_ROOT, PHRASES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--server-dir", type=Path, required=True)
    args = parser.parse_args()
    if not args.prepare:
        print("未生成；需显式 --prepare，且本机 CosyVoice 已就绪。")
        return
    targets = [ASSET_ROOT / f"{kind}-{rate}.opusframes" for kind in PHRASES for rate in (16000, 24000)]
    if any(path.exists() for path in targets):
        raise ValueError("waiting_assets_already_exist")
    # 使用小智已经安装的音频依赖，自己的编码器与日用 TTS 编码器不共享。
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    from math import gcd
    sys.path.insert(0, str(args.server_dir.resolve()))
    opus_dir = args.server_dir.resolve() / "native/libopus-1.6.1/Library/bin"
    if not (opus_dir / "opus.dll").is_file():
        raise ValueError("existing_opus_library_missing")
    os.environ["PATH"] = str(opus_dir) + os.pathsep + os.environ.get("PATH", "")
    dll_handle = os.add_dll_directory(str(opus_dir)) if os.name == "nt" else None
    from core.utils.opus_encoder_utils import OpusEncoderUtils
    opener = build_opener(ProxyHandler({}))
    prepared = []
    for kind, phrase in PHRASES.items():
        request = Request("http://127.0.0.1:18770/v1/audio/speech",
                          data=json.dumps({"input": phrase, "cache": False}).encode(),
                          headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=30) as response:
            audio, sample_rate = sf.read(BytesIO(response.read(2 * 1024 * 1024)), dtype="float32")
        if audio.ndim != 1:
            raise ValueError("waiting_audio_not_mono")
        for rate in (16000, 24000):
            divisor = gcd(rate, sample_rate)
            values = resample_poly(audio, rate // divisor, sample_rate // divisor)
            pcm = (np.clip(values, -1, 1) * 32767).astype("<i2").tobytes()
            packets = []
            encoder = OpusEncoderUtils(sample_rate=rate, channels=1, frame_size_ms=60)
            try:
                encoder.encode_pcm_to_opus_stream(pcm, end_of_stream=True, callback=packets.append)
            finally:
                encoder.close()
            if not 1 <= len(packets) <= 35:
                raise ValueError("waiting_phrase_too_long")
            blob = b"LMWAIT01" + b"".join(struct.pack("!H", len(p)) + p for p in packets)
            prepared.append((ASSET_ROOT / f"{kind}-{rate}.opusframes", blob, len(packets)))
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    for path, blob, count in prepared:
        with path.open("xb") as handle:
            handle.write(blob)
        print(json.dumps({"asset": path.name, "packets": count, "playable_ms": count * 60}))


if __name__ == "__main__":
    main()
