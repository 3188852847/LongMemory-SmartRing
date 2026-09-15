"""在既有 CosyVoice 环境比较局部运行路径；只使用固定合成文本。

结果排他写入 experiments/runs，不连接 Memory、回答供应商或圆屏。首次运行用于
找热点，后续交替运行基线与候选；分项时间存在嵌套和 CUDA 流重叠，不能直接相加。
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import random
import subprocess
import sys
from time import perf_counter
import uuid

from service import (
    CosyVoiceSynthesizer, DEFAULT_SOURCE, PROMPT_TEXT,
    REFERENCE_SPEAKER_ID,
)

ROOT = Path(__file__).resolve().parents[3]


def synthesis_units(case, *, punctuation_segments=False):
    """可复用当前实际切段，避免把整条长答当成日用首段而夸大流式收益。"""
    if not punctuation_segments:
        return [case]
    from benchmark_handoff import plan
    return [replace(case, id=f"{case.id}-segment{index}", text=text)
            for index, text in enumerate(plan(case.text), 1)]


class StageTrace:
    """仅为实验实例包裹方法，记录墙钟与所在 CUDA 流的事件间隔。"""

    def __init__(self, torch):
        self.torch = torch
        self.records = []
        self.started = perf_counter()

    def wrap(self, stack, owner, name, stage):
        original = getattr(owner, name)
        had_local = name in owner.__dict__
        local = owner.__dict__.get(name)

        def measured(*args, **kwargs):
            start = self.torch.cuda.Event(enable_timing=True)
            end = self.torch.cuda.Event(enable_timing=True)
            began = perf_counter()
            start.record()
            try:
                return original(*args, **kwargs)
            finally:
                end.record()
                self.records.append((stage, began, perf_counter(), start, end))

        def restore():
            if had_local:
                setattr(owner, name, local)
            else:
                delattr(owner, name)

        setattr(owner, name, measured)
        stack.callback(restore)

    def summary(self):
        # 只在该轮生成全部结束后同步；避免每步同步破坏模型内部并发关系。
        self.torch.cuda.synchronize()
        groups = {}
        for stage, began, ended, start, end in self.records:
            group = groups.setdefault(stage, {"calls": 0, "wall_ms": 0.0, "stream_elapsed_ms": 0.0})
            group["calls"] += 1
            group["wall_ms"] += (ended - began) * 1000
            group["stream_elapsed_ms"] += start.elapsed_time(end)
        return {
            name: {key: round(value, 3) if isinstance(value, float) else value for key, value in group.items()}
            for name, group in groups.items()
        }


def git_revision(root):
    result = subprocess.run(
        ["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def run_case(synth, case, *, variant, repeat, stream, profile, output, service_path=False, timeline_started=None):
    import numpy as np
    import torch
    from runtime_optimizations import install_qwen2_hidden_only

    handles = []
    runtime = synth._model.model
    previous_streaming = synth.model_streaming
    try:
        synth.model_streaming = stream
        if variant == "hidden_only":
            handles.append(install_qwen2_hidden_only(runtime.llm.llm))
        if any(not handle.applied for handle in handles):
            raise RuntimeError("optimization_unavailable: " + ",".join(handle.reason for handle in handles))
        random.seed(42 + repeat)
        np.random.seed(42 + repeat)
        torch.manual_seed(42 + repeat)
        torch.cuda.manual_seed_all(42 + repeat)
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        synth._prepare_stream()
        chunks, arrivals = [], []
        with ExitStack() as stack:
            trace = StageTrace(torch) if profile else None
            if trace is not None:
                trace.wrap(stack, runtime.llm.llm, "forward_one_step", "token_transformer")
                trace.wrap(stack, runtime.llm, "sampling_ids", "token_sampling")
                trace.wrap(stack, runtime.flow, "inference", "flow")
                trace.wrap(stack, runtime.hift, "inference", "hift_including_f0")
                trace.wrap(stack, runtime.hift.f0_predictor, "forward", "f0")
            started = perf_counter()
            if service_path:
                def service_items():
                    for wav in synth.stream_chunks(case.text, use_cache=False):
                        audio, rate = synth._soundfile.read(BytesIO(wav), dtype="float32")
                        if rate != synth._sample_rate:
                            raise RuntimeError("unexpected_sample_rate")
                        yield {"tts_speech": torch.from_numpy(audio).unsqueeze(0)}
                items = service_items()
            else:
                items = synth._model.inference_zero_shot(
                    case.text, PROMPT_TEXT, synth._prompt_wav,
                    zero_shot_spk_id=REFERENCE_SPEAKER_ID, stream=stream,
                )
            for item in items:
                speech = item["tts_speech"].detach().cpu()
                if speech.numel() == 0 or not torch.isfinite(speech).all():
                    raise RuntimeError("invalid_audio_chunk")
                chunks.append(speech)
                arrivals.append({
                    "at_ms": round((perf_counter() - started) * 1000, 3),
                    "audio_ms": round(speech.shape[-1] / synth._sample_rate * 1000, 3),
                    "samples": int(speech.shape[-1]),
                })
            torch.cuda.synchronize()
            completed_ms = (perf_counter() - started) * 1000
            stages = trace.summary() if trace is not None else None
        wave = torch.cat(chunks, dim=-1).squeeze(0).numpy()
        audio_ms = len(wave) / synth._sample_rate * 1000
        name = f"{case.id}-{variant}-{'stream' if stream else 'complete'}-{repeat}.wav"
        target = output / name
        # 输出目录新建且名称由封闭选项组成；音频仅含公开固定合成句，不接触个人数据。
        if target.exists():
            raise FileExistsError(target)
        synth._soundfile.write(target, wave, synth._sample_rate, subtype="PCM_16")
        return {
            "case": case.id, "variant": variant, "repeat": repeat, "stream": stream,
            "first_chunk_ms": arrivals[0]["at_ms"], "completed_ms": round(completed_ms, 3),
            "audio_ms": round(audio_ms, 3), "rtf": round(completed_ms / audio_ms, 4),
            "chunks": arrivals, "stages": stages,
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
            "audio_file": name, "audio_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            # 在模型计时真正开始处取全局偏移，避免把线程创建/随机种子准备
            # 错减到块到达时刻；供串行标点片段的统一库存时间轴使用。
            "sequence_offset_ms": round((started - timeline_started) * 1000, 3) if timeline_started is not None else 0.0,
        }
    finally:
        synth.model_streaming = previous_streaming
        for handle in reversed(handles):
            handle.restore()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", nargs="+", choices=("baseline", "hidden_only"), default=["baseline"])
    parser.add_argument("--cases", nargs="+", default=["short_reply", "expressive"])
    parser.add_argument("--repeat", type=int, choices=range(1, 11), default=1)
    parser.add_argument("--complete", action="store_true", help="模型一次生成完整片段，仍为隔离实验")
    parser.add_argument("--compare-modes", action="store_true", help="交替比较内部流式与完整片段")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--worker-thread", action="store_true", help="在新请求线程中生成，复核HTTP线程与主线程差异")
    parser.add_argument("--torch-threads", type=int, choices=(1, 2, 4, 8), default=None)
    parser.add_argument("--service-path", action="store_true", help="包含服务WAV封装与缓存关闭路径")
    parser.add_argument("--system-qos", action="store_true", help="对照系统默认调度；默认与日用服务一样申请 HighQoS")
    parser.add_argument("--punctuation-segments", action="store_true", help="复用当前标点切段，连续测各段供给；文字预先给定")
    args = parser.parse_args()
    if args.compare_modes and args.complete:
        parser.error("--compare-modes 与 --complete 不可同用")
    sys.path.insert(0, str(ROOT / "src"))
    from longmemory.application.voice_benchmark import CASES
    cases = {case.id: case for case in CASES}
    if len(set(args.variants)) != len(args.variants) or len(set(args.cases)) != len(args.cases):
        parser.error("variants/cases 不得重复")
    if any(name not in cases for name in args.cases):
        parser.error("需要已有固定合成用例")
    output = ROOT / "experiments/runs" / ("cosyvoice-runtime-" + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "project_revision": git_revision(ROOT), "cosyvoice_revision": git_revision(DEFAULT_SOURCE),
        "reply_cache": False, "reference_cache": True, "profile": args.profile,
        "limitations": ["固定合成输入；不含回答模型、HTTP、Opus或设备播放", "分项时间嵌套且可能重叠，不能相加", "随机种子不保证并行路径逐采样一致", "当前工作区代码可能尚未提交"],
        "records": [],
        "sequences": [],
        "source_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("service.py", "runtime_optimizations.py", "benchmark_runtime.py", "windows_qos.py")
        },
    }
    print(json.dumps({"output": str(output)}, ensure_ascii=False), flush=True)
    # 基准直接构造合成器，不经过 service.main；必须显式复现当前日用 QoS，
    # 避免把后台调度差异误当成完整/流式模式的差异。只设置本实验进程。
    from windows_qos import apply_current_process_high_qos
    report["windows_qos"] = (
        {"applied": False, "reason": "disabled", "before": None, "after": None}
        if args.system_qos else apply_current_process_high_qos()
    )
    print(json.dumps({"windows_qos": report["windows_qos"]}), flush=True)
    import torch
    if args.torch_threads is not None:
        torch.set_num_threads(args.torch_threads)
    # 基准显式关闭日用默认优化，再按每一轮 variant 安装，避免伪基线。
    synth = CosyVoiceSynthesizer(hidden_only=False, model_streaming=True)
    report.update(torch=str(torch.__version__), gpu=torch.cuda.get_device_name(), sample_rate=synth._sample_rate,
                  torch_threads=torch.get_num_threads(), interop_threads=torch.get_num_interop_threads(),
                  worker_thread=args.worker_thread, service_path=args.service_path,
                  punctuation_segments=args.punctuation_segments)
    if args.punctuation_segments:
        report["limitations"].append("切段序列已预先给定；段间含实验归档开销，不能冒充真实LLM输入或设备播放")
    for repeat in range(args.repeat):
        variants = args.variants if repeat % 2 == 0 else list(reversed(args.variants))
        modes = [True, False] if args.compare_modes else [not args.complete]
        if repeat % 2:
            modes.reverse()
        for name in args.cases:
            for stream in modes:
                for variant in variants:
                    sequence = {"case": name, "variant": variant, "repeat": repeat,
                                "stream": stream, "segments": []}
                    sequence_started = perf_counter()
                    for index, unit in enumerate(synthesis_units(cases[name], punctuation_segments=args.punctuation_segments), 1):
                        kwargs = dict(variant=variant, repeat=repeat, stream=stream, profile=args.profile, output=output, service_path=args.service_path, timeline_started=sequence_started)
                        if args.worker_thread:
                            with ThreadPoolExecutor(max_workers=1) as executor:
                                record = executor.submit(run_case, synth, unit, **kwargs).result()
                        else:
                            record = run_case(synth, unit, **kwargs)
                        record.update(source_case=name, segment_index=index)
                        sequence["segments"].append(record)
                        report["records"].append(record)
                        # 每轮单独落盘便于失败定位；最终报告只在全部完成后排他创建。
                        with (output / f"record-{len(report['records']):03}.json").open("x", encoding="utf-8") as handle:
                            json.dump(record, handle, ensure_ascii=False, indent=2)
                        print(json.dumps(record, ensure_ascii=False), flush=True)
                    sequence["completed_ms"] = round((perf_counter() - sequence_started) * 1000, 3)
                    report["sequences"].append(sequence)
    with (output / "report.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
