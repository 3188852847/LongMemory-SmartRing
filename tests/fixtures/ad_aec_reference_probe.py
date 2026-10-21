"""固定_apply_aec的纯合成特征核查；不导入连接/模型，不读音频或配置。"""
import ast
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT.parents[2] if ROOT.parent.name == "worktrees" else ROOT
PIN = "eb4b28c59ed7ed885258498cf757ce14352d620e"


def main():
    import numpy as np
    source = subprocess.check_output(["git", "-C", str(MAIN / "local/runtime/xiaozhi-esp32-server"),
        "show", PIN + ":main/xiaozhi-server/core/connection.py"], text=True, encoding="utf-8")
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "ConnectionHandler")
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_apply_aec")
    namespace = {"np": np, "TAG": "synthetic"}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "pinned_apply_aec", "exec"), namespace)
    warnings = []
    logger = NS(bind=lambda **_: NS(warning=lambda *_: warnings.append("aec_warning")))
    phase = np.arange(960) / 16000
    ref = np.rint(9000 * np.sin(2 * np.pi * 400 * phase)).astype(np.int16)
    near = np.rint(5000 * np.sin(2 * np.pi * 700 * phase)).astype(np.int16)
    quadrature = np.rint(5000 * np.cos(2 * np.pi * 400 * phase)).astype(np.int16)
    echo = np.rint(ref.astype(float) * .5).astype(np.int16)
    mixture = (near.astype(np.int32) + echo).astype(np.int16)
    rms = lambda values: float(np.sqrt(np.mean(values.astype(np.float64) ** 2)))
    def projection_700(values):
        sine = float(np.dot(values.astype(float), np.sin(2 * np.pi * 700 * phase))) * 2 / 960
        cosine = float(np.dot(values.astype(float), np.cos(2 * np.pi * 700 * phase))) * 2 / 960
        return math.hypot(sine, cosine) / math.sqrt(2)
    rows, raw_output = [], {}
    cases = [
        ("no_reference", near, {}, 1060),
        ("one_reference", near, {1000: ref.tobytes()}, 1060),
        ("echo_only", echo, {1000: ref.tobytes(), 1060: ref.tobytes()}, 1060),
        ("near_only_disjoint_spectrum", near, {1000: ref.tobytes(), 1060: ref.tobytes()}, 1060),
        ("near_only_quadrature", quadrature, {1000: ref.tobytes(), 1060: ref.tobytes()}, 1060),
        ("echo_plus_near", mixture, {1000: ref.tobytes(), 1060: ref.tobytes()}, 1060),
        ("stale_reference_quadrature", quadrature, {1000: ref.tobytes(), 1060: ref.tobytes()}, 61060),
    ]
    for label, mic, cache, timestamp in cases:
        age = 60 if label == "stale_reference_quadrature" else 0
        conn = NS(aec_audio_cache=cache,
                  aec_audio_cache_time={key: time.time() - age for key in cache}, logger=logger)
        output_bytes = namespace["_apply_aec"](conn, timestamp, mic.tobytes())
        output = np.frombuffer(output_bytes, np.int16)
        window = np.hanning(960)
        mic_psd = 10 * np.log10(abs(np.fft.rfft(mic.astype(float) * window)) ** 2 + 1e-8)
        ref_psd = 10 * np.log10(abs(np.fft.rfft(ref.astype(float) * window)) ** 2 + 1e-8)
        corr = abs(float(np.dot(mic_psd, ref_psd))) / (np.linalg.norm(mic_psd) * np.linalg.norm(ref_psd) + 1e-8)
        before, after = rms(mic), rms(output)
        rows.append(dict(case=label, pcm_samples=len(output), before_rms=round(before, 3),
            after_rms=round(after, 3), rms_ratio=round(after / before, 6),
            source_log_psd_correlation=round(float(corr), 6),
            nearest_raw_timestamp_delta_ms=min((abs(key - timestamp) for key in cache), default=None),
            synthesized_reference_age_seconds=age,
            near_700hz_projection_before=round(projection_700(mic), 3),
            near_700hz_projection_after=round(projection_700(output), 3),
            output_equals_input=output_bytes == mic.tobytes()))
        raw_output[label] = output_bytes

    # 只核对真实Opus不同编码率解至AEC固定16kHz/960样本的契约，无网络。
    voice = MAIN / "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server"
    sys.path.insert(0, str(voice))
    native = voice / "native/libopus-1.6.1/Library/bin"
    os.environ["PATH"] = str(native) + os.pathsep + os.environ.get("PATH", "")
    cookie = os.add_dll_directory(str(native))
    from core.utils.opus_encoder_utils import OpusEncoderUtils
    from opuslib_next import Decoder
    formats = []
    try:
        for rate in (16000, 24000):
            encoder = OpusEncoderUtils(rate, 1, 60)
            values = np.rint(5000 * np.sin(2 * np.pi * 400 * np.arange(rate * 60 // 1000) / rate)).astype(np.int16)
            packets = []
            try:
                encoder.encode_pcm_to_opus_stream(values.tobytes(), end_of_stream=True, callback=packets.append)
                decoded = Decoder(16000, 1).decode(packets[0], 960)
                formats.append(dict(encoded_rate=rate, encoded_frames=len(packets),
                                    reference_decode_rate=16000, reference_pcm_bytes=len(decoded)))
            finally:
                encoder.close()
    finally:
        cookie.close()
    assert "torch" not in sys.modules
    print(json.dumps(dict(source_pin=PIN, numpy_version=np.__version__, format="PCM16LE_16k_mono_60ms",
        scenarios=rows, codec_formats=formats, aec_warnings=len(warnings),
        stale_and_current_outputs_identical=raw_output["near_only_quadrature"] == raw_output["stale_reference_quadrature"],
        quadrature_time_domain_dot=int(np.dot(quadrature.astype(np.int64), ref.astype(np.int64))),
        torch_imported=False, asr_vad_models_executed=False, network_used=False, audio_files_written=False)))


if __name__ == "__main__":
    main()
