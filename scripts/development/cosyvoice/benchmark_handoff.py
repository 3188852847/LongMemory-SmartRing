"""用固定公开句比较短开头与合并首段的音频供给；只调用回环 TTS。

不连接回答模型、记忆或圆屏。欠载是按片段可用时刻和 60ms 帧计算的服务端
估算，既不是扬声器测量，也不包含 LLM 等待。结果排他写入忽略的实验目录。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from urllib.request import Request, urlopen
import uuid
import wave

ROOT = Path(__file__).resolve().parents[3]
ADAPTERS = ROOT / "scripts/development/xiaozhi"
BOUNDARIES = "，,、。？?！!；;：:"
LEGACY_FIRST_BOUNDARIES = "，~、,。？?！!；;："
CASES = {
    "expressive": "你回来啦。今天辛苦了，如果愿意的话，就把烦心事慢慢说给我听吧。",
    "planning": "可以呀，我们先把今天最重要的一件事做完，再给自己留一点休息时间。如果遇到困难，我们就把任务拆小一点。",
    "numbers_time": "明天下午一点零五分，我会提醒你休息十分钟。",
}


class SegmentProbe:
    """只模拟上游纯文本缓冲；不导入会初始化日志/配置的 Xiaozhi 基类。

    首段的 rfind 顺序和尾文累加行为来自本机基类；固定用例不含 emoji。
    输入逐字到达，避免用已知的上游大增量缺陷夸大对照差异。
    """

    def __init__(self):
        self.tts_text_buff = []
        self.processed_chars = 0
        self.is_first_sentence = True
        self.tts_stop_request = False
        self.spoken = []

    def _get_segment_text(self):
        current = "".join(self.tts_text_buff)[self.processed_chars:]
        positions = [current.rfind(p) for p in LEGACY_FIRST_BOUNDARIES if p in current]
        if not positions:
            return None
        end = min(positions) + 1
        self.processed_chars += end
        self.is_first_sentence = False
        return current[:end].strip(" ，,。.!！“”\"：:-－、[]【】")

    def to_tts_stream(self, text, opus_handler=None):
        self.spoken.append(text)

    def _process_remaining_text_stream(self, opus_handler=None):
        full = "".join(self.tts_text_buff)
        tail = full[self.processed_chars:]
        if not tail:
            return False
        self.to_tts_stream(tail.strip(" ，,。.!！“”\"：:-－、[]【】"))
        self.processed_chars += len(full)
        return True


def plan(text, *, legacy=False, first_minimum_chars=16):
    sys.path.insert(0, str(ADAPTERS))
    if legacy:
        # 固定已知提交作为对照，避免日后主分支改动令“旧策略”漂移。
        source = subprocess.run(
            ["git", "show", "c487bb5:scripts/development/xiaozhi/voice_latency.py"],
            cwd=ROOT, capture_output=True, check=True,
        ).stdout.decode("utf-8")
        namespace = {"__name__": "handoff_legacy_policy"}
        exec(compile(source, "c487bb5/voice_latency.py", "exec"), namespace)
        install = namespace["install_cosyvoice_punctuation_policy"]
    else:
        from cosyvoice_segments import install_cosyvoice_punctuation_policy as install
    probe = SegmentProbe()
    if legacy:
        install(probe)
    else:
        install(probe, first_minimum_chars=first_minimum_chars)
    for char in text:
        probe.tts_text_buff.append(char)
        segment = probe._get_segment_text()
        if segment:
            probe.to_tts_stream(segment)
    probe._process_remaining_text_stream()
    return probe.spoken


def inventory(records):
    """所有段均收齐后播放；库存只按服务器供给估算，不扣除自然静音。"""
    if not records or any(
        not math.isfinite(record["playable_ms"]) or record["playable_ms"] <= 0
        for record in records
    ):
        raise ValueError("audio_inventory_empty_or_invalid")
    end = None
    gaps = []
    for record in records:
        ready = record["available_ms"]
        gap = max(0.0, ready - end) if end is not None else 0.0
        start = max(ready, end) if end is not None else ready
        record["inventory_before_ms"] = round(max(0.0, end - ready) if end is not None else 0.0, 3)
        record["estimated_gap_before_ms"] = round(gap, 3)
        end = start + record["playable_ms"]
        gaps.append(gap)
    duration = sum(r["generation_ms"] for r in records)
    audio = sum(r["playable_ms"] for r in records)
    return {
        "first_available_ms": records[0]["available_ms"],
        "max_estimated_gap_ms": round(max(gaps, default=0), 3),
        "total_estimated_gap_ms": round(sum(gaps), 3),
        "overall_rtf": round(duration / audio, 4),
        "estimated_playback_end_ms": round(end, 3),
    }


def playable_duration_ms(frames, sample_rate):
    """用整数比率向上补齐 60ms，避免完整帧被浮点误差误算成多一包。"""
    if type(frames) is not int or type(sample_rate) is not int or frames <= 0 or sample_rate <= 0:
        raise ValueError("invalid_wave_frames")
    divisor = sample_rate * 60
    return ((frames * 1000 + divisor - 1) // divisor) * 60


def get_health(port):
    with urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
        health = json.load(response)
    if health.get("provider") != "cosyvoice3" or health.get("ready") is not True:
        raise RuntimeError("unexpected_service")
    return health


def measure(port, segments, output, name):
    before = get_health(port)
    began = perf_counter()
    records = []
    audio_files = []
    for index, text in enumerate(segments, 1):
        request = Request(
            f"http://127.0.0.1:{port}/v1/audio/speech",
            data=json.dumps({"input": text, "response_format": "wav", "cache": False}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        started = perf_counter()
        with urlopen(request, timeout=90) as response:
            if response.headers.get_content_type() != "audio/wav":
                raise RuntimeError("unexpected_audio")
            data = response.read()
        available = perf_counter()
        with wave.open(BytesIO(data), "rb") as wav:
            frames, sample_rate = wav.getnframes(), wav.getframerate()
            audio_ms = frames / sample_rate * 1000
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or audio_ms <= 0:
                raise RuntimeError("invalid_wave")
        playable_ms = playable_duration_ms(frames, sample_rate)
        generation = (available - started) * 1000
        filename = f"{name}-{index}.wav"
        audio_files.append((filename, data))
        records.append({
            "index": index, "text": text, "generation_ms": round(generation, 3),
            "available_ms": round((available - began) * 1000, 3),
            "audio_ms": round(audio_ms, 3), "playable_ms": playable_ms,
            "rtf": round(generation / playable_ms, 4),
            "audio_file": filename,
        })
    after = get_health(port)
    # 归档和哈希不应延后下一段请求；全部供给计时完成后才写实验产物。
    for record, (filename, data) in zip(records, audio_files):
        with (output / filename).open("xb") as handle:
            handle.write(data)
        record["audio_sha256"] = hashlib.sha256(data).hexdigest()
    diagnostics = {
        stage: {field: round(values[field] - before["diagnostics"][stage][field], 3)
                for field in ("calls", "wall_ms")}
        for stage, values in after.get("diagnostics", {}).items()
    }
    return {"name": name, "segments": records, "summary": inventory(records), "diagnostics": diagnostics}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18771, choices=range(18771, 18780))
    parser.add_argument("--repeat", type=int, default=2, choices=range(1, 6))
    parser.add_argument("--cases", nargs="+", choices=tuple(CASES), default=list(CASES))
    parser.add_argument("--first-minimum-chars", type=int, default=16, choices=(12, 16, 18))
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    plans = {name: {"legacy": plan(CASES[name], legacy=True),
                    "candidate": plan(CASES[name], first_minimum_chars=args.first_minimum_chars)}
             for name in args.cases}
    if args.plan_only:
        print(json.dumps(plans, ensure_ascii=False, indent=2))
        return
    health = get_health(args.port)
    output = ROOT / "experiments/runs" / ("cosyvoice-handoff-" + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    report = {"version": 1, "at": datetime.now(timezone.utc).isoformat(), "health": health,
              "project_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                                 capture_output=True, check=True).stdout.decode().strip(),
              "legacy_revision": "c487bb5",
              "plans": plans, "first_minimum_chars": args.first_minimum_chars, "records": [],
              "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in [Path(__file__), ADAPTERS / "voice_latency.py", ADAPTERS / "cosyvoice_segments.py"]},
              "limitations": ["固定公开合成文本，缓存关闭，未固定随机种子", "整体耗时含HTTP/WAV，不含LLM、Opus编码或设备",
                              "库存按WAV时长向上补齐60ms估算，不含实际发送与扬声器回执",
                              "顺序交替；两种切法音频与韵律不要求逐采样相同"]}
    print(json.dumps({"output": str(output)}, ensure_ascii=False), flush=True)
    for repeat in range(args.repeat):
        for case in args.cases:
            for variant in (("legacy", "candidate") if repeat % 2 == 0 else ("candidate", "legacy")):
                result = measure(args.port, plans[case][variant], output, f"{repeat}-{case}-{variant}")
                report["records"].append(result)
                with (output / f"record-{len(report['records']):03}.json").open("x", encoding="utf-8") as handle:
                    json.dump(result, handle, ensure_ascii=False, indent=2)
                print(json.dumps({"name": result["name"], **result["summary"]}, ensure_ascii=False), flush=True)
    with (output / "report.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
