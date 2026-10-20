"""显式准备固定同声线短提示供两个场景复用；只调用本机 CosyVoice。"""

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import struct
import sys
from urllib.request import Request, build_opener, ProxyHandler

from voice_waiting import CACHE_ROOT, PHRASES, cached_packets, publish_cache, decode_packets
from cosyvoice_profiles import profile_store, waiting_identity
from voice_budget import NoRedirect


def prepare_cache(store, synthesize, encode, *, root=CACHE_ROOT):
    """维护窗口中先生成整套再原子发布；依赖注入供零TTS合成测试。"""
    selected, _, digest = store.model_context()
    identity = waiting_identity(digest)
    if all(cached_packets(root, identity, kind, rate) for kind in PHRASES for rate in (16000, 24000)):
        return {'status': 'already_ready', 'voice_identity': identity}
    blobs, encoded = {}, {}
    for kind, phrase in PHRASES.items():
        if phrase not in encoded:
            audio = synthesize(phrase, selected)
            if waiting_identity(store.model_context()[2]) != identity:
                raise ValueError('waiting_voice_changed_during_preparation')
            encoded[phrase] = {}
            for rate in (16000, 24000):
                blob = encode(audio, rate)
                if not decode_packets(blob):
                    raise ValueError('waiting_encoded_audio_invalid')
                encoded[phrase][rate] = blob
        if waiting_identity(store.model_context()[2]) != identity:
            raise ValueError('waiting_voice_changed_during_preparation')
        for rate in (16000, 24000):
            blobs[f'{kind}-{rate}'] = encoded[phrase][rate]
    if waiting_identity(store.model_context()[2]) != identity:
        raise ValueError('waiting_voice_changed_during_preparation')
    publish_cache(root, identity, blobs)
    return {'status': 'ready', 'voice_identity': identity, 'items': len(blobs)}


def validate_waveform(audio, sample_rate):
    """整段音频含首尾静音一并计长；拒绝超限，不裁词或自动裁静音。"""
    import numpy as np
    if type(sample_rate) is not int or sample_rate <= 0 or audio.ndim != 1:
        raise ValueError('waiting_audio_format_invalid')
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError('waiting_audio_samples_invalid')
    if len(audio) * 1000 > sample_rate * 35 * 60:
        raise ValueError('waiting_phrase_too_long')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--maintenance-window", action="store_true",
                        help="仅在X已隔离全部语音生产者、TTS独立就绪的维护窗口执行")
    parser.add_argument("--server-dir", type=Path)
    args = parser.parse_args(argv)
    if not args.prepare:
        print("未生成；需显式 --prepare --maintenance-window，且仅在隔离语音生产者后准备。")
        return
    if not args.maintenance_window or args.server_dir is None:
        raise ValueError('waiting_preparation_requires_isolated_maintenance_window')
    store = profile_store()
    if not store.profile_path.is_file():
        raise ValueError('waiting_selected_profile_missing')
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
    opener = build_opener(ProxyHandler({}), NoRedirect())
    def synthesize(phrase, selected):
        request = Request("http://127.0.0.1:18770/v1/audio/speech",
                          data=json.dumps({"input": phrase, "cache": False,
                                           "voice_profile": selected}).encode(),
                          headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=30) as response:
            data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError('waiting_audio_too_large')
            return data

    def encode(data, rate):
        audio, sample_rate = sf.read(BytesIO(data), dtype="float32")
        print(json.dumps({'waiting_audio': {'sample_rate': sample_rate,
              'samples': len(audio), 'duration_ms': round(len(audio) * 1000 / sample_rate, 3),
              'target_rate': rate}}, ensure_ascii=False), flush=True)
        validate_waveform(audio, sample_rate)
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
        return b"LMWAIT01" + b"".join(struct.pack("!H", len(p)) + p for p in packets)
    try:
        print(json.dumps(prepare_cache(store, synthesize, encode), ensure_ascii=False))
    finally:
        if dll_handle is not None:
            dll_handle.close()


if __name__ == "__main__":
    main()
