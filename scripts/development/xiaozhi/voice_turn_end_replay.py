"""中文话轮场景的合成控制流回放；脚本分数不代表真实中文模型准确率。

无网络、录音或服务。报告误切/漏切/判停延迟，首个有效回答声音始终 unknown。
运行 python -B scripts/development/xiaozhi/voice_turn_end_replay.py。
"""

import argparse
import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import time
import wave

from voice_turn_end import TurnEndConfig, TurnEndState


@dataclass(frozen=True)
class Scenario:
    name: str
    # 按 60ms 整帧描述：音频是人工常数 PCM，不模拟语义或真人声学特征。
    speech_ms: tuple
    pause_ms: tuple
    pause_probabilities: tuple
    inference_ms: int = 30


SCENARIOS = (
    Scenario("完整陈述", (1200,), (), (0.95,)),
    Scenario("中文思考后续说", (1200, 900), (780,), (0.1, 0.95)),
    Scenario("列举中间停顿", (1200, 960, 900), (660, 900), (0.1, 0.2, 0.95)),
    Scenario("短答", (540,), (), (0.95,)),
    Scenario("短停顿后续说", (1200, 900), (240,), (0.95, 0.95)),
    Scenario("错误高分导致误抢话", (1200, 900), (540,), (0.95, 0.95)),
    Scenario("错误低分导致漏判延迟", (1200,), (), (0.1,)),
    Scenario("慢推理退回原端点", (1200,), (), (0.95,), 300),
)


class ScriptedSlot:
    def __init__(self, now, score, inference_ms):
        self.now, self.score, self.inference_ms = now, score, inference_ms
        self.jobs = []

    def start(self, pcm):
        if any(not job[0].done() for job in self.jobs):
            return None, "busy"
        future = asyncio.get_running_loop().create_future()
        self.jobs.append((future, self.now[0] + self.inference_ms / 1000))
        return future, "started"

    def tick(self):
        for future, ready in self.jobs:
            if not future.done() and self.now[0] >= ready:
                future.set_result(self.score[0])


class MeasuredReplaySlot(ScriptedSlot):
    """离线串行 CPU 测量：按实测特征+推理耗时，在音频时轴归还结果。

    不用于服务接收路径；避免把快速离线喂帧误当成模型永远赶不上实时音频。
    """

    def __init__(self, now, detector):
        super().__init__(now, [0.0], 0)
        self.detector = detector
        self.durations = []
        self.failures = 0

    def start(self, pcm):
        if any(not job[0].done() for job in self.jobs):
            return None, "busy"
        started = time.perf_counter()
        try:
            value = self.detector.predict(pcm)
            if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("invalid_probability")
        except Exception:
            self.failures += 1
            return None, "unavailable"
        duration = time.perf_counter() - started
        self.durations.append(round(duration * 1000, 3))
        future = asyncio.get_running_loop().create_future()
        # 每次结果有独立值，不能在续说后套用最新一次打分。
        self.jobs.append((future, self.now[0] + duration, value))
        return future, "started"

    def tick(self):
        for future, ready, value in self.jobs:
            if not future.done() and self.now[0] >= ready:
                future.set_result(value)


def percentile(values, fraction):
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


async def replay(scenario, mode, *, detector=None, audio=None):
    now, score = [0.0], [scenario.pause_probabilities[0]]
    slot = (MeasuredReplaySlot(now, detector) if detector is not None
            else ScriptedSlot(now, score, scenario.inference_ms))
    config = TurnEndConfig(mode=mode)
    state = TurnEndState(config, slot, clock=lambda: now[0])
    timeline = []
    for index, speech in enumerate(scenario.speech_ms):
        timeline += [(True, index)] * (speech // 60)
        pause = scenario.pause_ms[index] if index < len(scenario.pause_ms) else 2400
        timeline += [(False, index)] * (pause // 60)
    true_end = sum(scenario.speech_ms) + sum(scenario.pause_ms)
    total, stamp, has_voice = 0, 0, False
    endpoints = []
    for frame_number, (voice, index) in enumerate(timeline, 1):
        now[0] = frame_number * 0.06
        at = frame_number * 60
        score[0] = scenario.pause_probabilities[index]
        slot.tick()
        total = min(total + 1920, 256000)
        if voice:
            stamp, has_voice = at, True
        if not has_voice:
            continue
        silence = at - stamp
        legacy = not voice and silence >= 600
        pcm = (audio[max(0, frame_number * 1920 - total):frame_number * 1920]
               if audio is not None else b"\x01\x00" * (total // 2))
        decision = state.observe(pcm=pcm,
                                 audio_have_voice=voice, voice_stamp=stamp,
                                 silence_ms=silence, upstream_stop=legacy)
        if decision:
            endpoints.append(at)
            state.cancel()
            total, has_voice = 0, False
    for job in slot.jobs:
        future = job[0]
        if not future.done():
            future.cancel()
    false_cuts = sum(endpoint < true_end for endpoint in endpoints)
    final = next((endpoint for endpoint in endpoints if endpoint >= true_end), None)
    latency = final - true_end if final is not None else None
    return {"scenario": scenario.name, "mode": mode, "pause_opportunities": len(scenario.pause_ms),
            "false_cuts": false_cuts, "missed_1200ms": latency is None or latency > 1200,
            "endpoint_latency_ms": latency, "effective_answer_audio_ms": None,
            "scripted_inference_ms": scenario.inference_ms if detector is None else None,
            "measured_model_p50_ms": percentile(slot.durations, 0.5) if detector is not None else None,
            "measured_model_failures": slot.failures if detector is not None else None,
            "decision_counts": dict(state.counts)}


def load_public_manifest(path):
    """只接受显式公开/合成中文资源声明、相对 WAV 和有界整帧人工标签。"""
    path = Path(path).resolve()
    if path.stat().st_size > 1000000:
        raise ValueError("turn_end_manifest_too_large")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("provenance") not in {"public", "synthetic"} or data.get("language") != "zh":
        raise ValueError("turn_end_public_chinese_provenance_required")
    cases = data.get("cases", [])
    if not isinstance(cases, list) or not 1 <= len(cases) <= 50:
        raise ValueError("turn_end_manifest_case_budget")
    loaded = []
    for index, case in enumerate(cases):
        speech, pauses = case["speech_ms"], case["pause_ms"]
        if (not isinstance(speech, list) or not isinstance(pauses, list)
                or not speech or len(pauses) != len(speech) - 1
                or not all(type(ms) is int and 0 < ms <= 30000 and ms % 60 == 0 for ms in speech + pauses)
                or sum(speech + pauses) > 60000):
            raise ValueError("turn_end_invalid_frame_labels")
        relative = Path(case["audio"])
        target = (path.parent / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(path.parent):
            raise ValueError("turn_end_audio_outside_manifest")
        with wave.open(str(target), "rb") as stream:
            if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (1, 2, 16000, "NONE"):
                raise ValueError("turn_end_wav_requires_16k_mono_pcm16")
            if stream.getnframes() > 62 * 16000:
                raise ValueError("turn_end_wav_duration_budget")
            pcm = stream.readframes(stream.getnframes())
        required = sum(speech + pauses) * 32
        if hashlib.sha256(pcm).hexdigest() != case.get("audio_sha256"):
            raise ValueError("turn_end_audio_hash_mismatch")
        if len(pcm) < required:
            raise ValueError("turn_end_audio_shorter_than_labels")
        # 只使用标签覆盖的原始音频，再补固定静音以观察有界的最后一次端点。
        pcm = pcm[:required] + b"\x00" * (2400 * 32)
        scenario = Scenario(f"public-zh-{index + 1}", tuple(speech), tuple(pauses),
                            tuple(0.0 for _ in speech))
        loaded.append((scenario, pcm))
    return loaded, hashlib.sha256(path.read_bytes()).hexdigest()


def public_report(manifest, detector):
    from voice_turn_end_model import MODEL_SHA256, MODEL_REVISION, SOURCE_COMMIT
    cases, digest = load_public_manifest(manifest)
    async def run():
        return [await replay(scenario, mode, detector=detector, audio=audio)
                for mode in ("off", "shadow", "enabled") for scenario, audio in cases]
    rows = asyncio.run(run())
    return {"version": 1, "evidence": "offline_public_zh_wav_with_annotated_vad_and_zero_tail",
            "manifest_sha256": digest, "rows": rows,
            "source_sha256": hashlib.sha256(Path(__file__).with_name("voice_turn_end.py").read_bytes()).hexdigest(),
            "config": asdict(TurnEndConfig()), "source_commit": SOURCE_COMMIT,
            "model_revision": MODEL_REVISION, "model_sha256": MODEL_SHA256,
            "effective_answer_audio_ms": None,
            "limitations": "annotated_vad_not_live_vad_no_device_playback"}


def report():
    async def run():
        return [await replay(scenario, mode) for mode in ("off", "shadow", "enabled") for scenario in SCENARIOS]
    rows = asyncio.run(run())
    summary = {}
    for mode in ("off", "shadow", "enabled"):
        selected = [row for row in rows if row["mode"] == mode]
        latencies = [row["endpoint_latency_ms"] for row in selected if row["endpoint_latency_ms"] is not None]
        pauses = sum(row["pause_opportunities"] for row in selected)
        cuts = sum(row["false_cuts"] for row in selected)
        summary[mode] = {"turns": len(selected), "pause_opportunities": pauses,
                         "false_cuts": cuts, "false_cut_rate": cuts / pauses if pauses else None,
                         "missed_1200ms": sum(row["missed_1200ms"] for row in selected),
                         "endpoint_p50_ms": percentile(latencies, 0.5),
                         "endpoint_p95_ms": percentile(latencies, 0.95)}
    fixtures = json.dumps([asdict(scenario) for scenario in SCENARIOS], ensure_ascii=False, sort_keys=True)
    return {"version": 1, "evidence": "synthetic_pcm_scripted_scores_not_model_accuracy",
            "dataset_sha256": hashlib.sha256(fixtures.encode()).hexdigest(),
            "source_sha256": hashlib.sha256(Path(__file__).with_name("voice_turn_end.py").read_bytes()).hexdigest(),
            "config": asdict(TurnEndConfig()), "summary": summary, "rows": rows,
            "effective_answer_audio_ms": None, "real_chinese_model_accuracy": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="已本地取得的公开/合成中文 WAV 标签清单")
    parser.add_argument("--model", type=Path, help="固定哈希的本地 v3.2 CPU ONNX")
    args = parser.parse_args()
    if bool(args.manifest) != bool(args.model):
        parser.error("--manifest and --model must be supplied together")
    if args.model:
        from voice_turn_end_model import SmartTurnCPU
        output = public_report(args.manifest, SmartTurnCPU(args.model))
    else:
        output = report()
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
