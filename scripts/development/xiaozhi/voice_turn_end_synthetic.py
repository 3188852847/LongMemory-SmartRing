"""用已安装 Windows 中文系统声线离线生成 AC 专用回放语料，不播放。

只写本工作树 experiments/runs/ 下的新目录，不改声线选择、私有配置或日用服务。
人工分句加静音标签不等于自然中文 VAD 标注，只作模型兼容与停顿初筛。
"""

from array import array
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import uuid
import wave


ROOT = Path(__file__).resolve().parents[3]
VOICES = ("Microsoft Huihui Desktop",)
CORPUS = (
    ("complete", ("今天下午三点，请提醒我喝水。",), ()),
    ("thinking", ("我想问一下，", "明天会下雨吗？"), (780,)),
    ("listing", ("帮我记一下，", "我喜欢喝绿茶，", "不太喜欢太甜的饮料。"), (660, 900)),
    ("short", ("好的。",), ()),
    ("short_pause", ("我的意思是，", "先不用提醒。"), (240,)),
    ("correction", ("不是周六，", "应该改成下周一。"), (1080,)),
)

POWERSHELL = r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $installed = @($speaker.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name })
    if ($installed -notcontains $request.voice) { throw 'requested installed voice unavailable' }
    $speaker.SelectVoice($request.voice)
    $speaker.Rate = 0
    $speaker.Volume = 100
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    foreach ($part in $request.parts) {
        if (Test-Path -LiteralPath $part.path) { throw 'output already exists' }
        $speaker.SetOutputToWaveFile($part.path, $format)
        $speaker.Speak($part.text)
        $speaker.SetOutputToNull()
    }
} finally {
    $speaker.Dispose()
}
'''


def trim_to_active_frames(pcm):
    """仅裁去系统 TTS 首尾低能量帧；内部停顿仍属于句内，边界分辨率 60ms。"""
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    windows = [samples[start:start + 960] for start in range(0, len(samples), 960)]
    energies = [math.sqrt(sum(value * value for value in window) / len(window)) for window in windows]
    threshold = max(80.0, max(energies, default=0) * 0.02)
    active = [index for index, energy in enumerate(energies) if energy >= threshold]
    if not active:
        raise ValueError("turn_end_synthetic_empty_speech")
    first, end = active[0] * 1920, (active[-1] + 1) * 1920
    return pcm[first:end].ljust(end - first, b"\x00")


def generate(output=None, voices=VOICES):
    if os.name != "nt":
        raise RuntimeError("turn_end_synthetic_windows_only")
    allowed = (ROOT / "experiments/runs").resolve()
    target = (Path(output).resolve() if output else
              allowed / ("ac-smart-turn-synthetic-" + uuid.uuid4().hex[:12]))
    if target == allowed or not target.is_relative_to(allowed) or target.exists():
        raise ValueError("turn_end_synthetic_new_owned_directory_required")
    target.mkdir(parents=True)
    cases = []
    for voice_index, voice in enumerate(voices):
        parts = []
        for name, phrases, _ in CORPUS:
            for index, text in enumerate(phrases):
                parts.append({"path": str(target / f"v{voice_index}-{name}-part{index}.wav"), "text": text})
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", POWERSHELL],
                                input=json.dumps({"voice": voice, "parts": parts}, ensure_ascii=True).encode("ascii"),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                                creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        if result.returncode:
            (target / "generation-error.txt").write_bytes(result.stderr[:16384])
            raise RuntimeError("turn_end_installed_voice_generation_failed")
        for name, phrases, pauses in CORPUS:
            audio, speech = [], []
            for index, _ in enumerate(phrases):
                with wave.open(str(target / f"v{voice_index}-{name}-part{index}.wav"), "rb") as source:
                    if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16000):
                        raise ValueError("turn_end_synthetic_format_mismatch")
                    pcm = trim_to_active_frames(source.readframes(source.getnframes()))
                audio.append(pcm)
                speech.append(len(pcm) // 32)
                if index < len(pauses):
                    audio.append(b"\x00" * (pauses[index] * 32))
            path = target / f"v{voice_index}-{name}.wav"
            with wave.open(str(path), "wb") as sink:
                sink.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                sink.writeframes(b"".join(audio))
            cases.append({"audio": path.name, "audio_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "speech_ms": speech, "pause_ms": list(pauses),
                          "voice": voice, "scenario": name})
    corpus_spec = json.dumps(CORPUS, ensure_ascii=False, separators=(",", ":"))
    manifest = {"provenance": "synthetic", "language": "zh", "generator": "Windows.System.Speech.CPU",
                "created_at_utc": datetime.now(timezone.utc).isoformat(), "voices": list(voices),
                "corpus_sha256": hashlib.sha256(corpus_spec.encode()).hexdigest(),
                "label_source": "separate_tts_phrases_energy_trim_60ms_plus_injected_pauses_not_natural_vad",
                "cases": cases}
    path = target / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"manifest": str(path), "cases": len(cases),
            "pause_opportunities": sum(len(case["pause_ms"]) for case in cases),
            "corpus_sha256": manifest["corpus_sha256"], "voices": list(voices),
            "gpu_used": False, "audio_played": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(generate(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
