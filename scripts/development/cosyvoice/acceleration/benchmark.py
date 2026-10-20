"""引擎无关的合成实验 harness：PCM 首响、整体速度、连续性、取消与质量门。

runner(case_id, seed, cancel_event) 由隔离调用方提供，产出已转 CPU 的 AudioChunk。
没有 HTTP 客户端或模型加载；不能把本模块 TTS 首个非静音块当作说完到设备首答。
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import statistics
import threading
from time import perf_counter
from typing import Callable, Iterable


@dataclass(frozen=True)
class AudioChunk:
    samples: tuple[float, ...]
    sample_rate: int


def measure(runner: Callable, case_id: str, seed: int, *, cancel_after_chunks: int | None = None,
            clock: Callable = perf_counter, startup_buffer_ms: float = 0.0) -> dict:
    """首块/首个有效块分别计时；空块不计，全部 PCM 必须有限且采样率一致。

    underflow 是无网络/无设备的生产速度回放估计；取消事件后产出字节不交付。
    close 时间计入 cancel_close_ms，模型实际协作取消由 runner 单独证明。
    """
    if cancel_after_chunks is not None and cancel_after_chunks < 1:
        raise ValueError("cancel_after_chunks must be positive")
    if not math.isfinite(startup_buffer_ms) or startup_buffer_ms < 0:
        raise ValueError("invalid startup buffer")
    cancel = threading.Event()
    began = clock()
    iterator = iter(())
    first_chunk = first_voice = None
    sample_rate = samples = chunks = 0
    received = []
    pcm_digest = hashlib.sha256()
    playback_end = None
    worst_gap = 0.0
    underflows = 0
    cancel_started = None
    error_name = None
    try:
        iterator = iter(runner(case_id, seed, cancel))
        for chunk in iterator:
            arrival = (clock() - began) * 1000
            if cancel.is_set():
                break
            if not isinstance(chunk, AudioChunk) or not isinstance(chunk.sample_rate, int) or not 8000 <= chunk.sample_rate <= 192000:
                raise ValueError("invalid PCM format")
            if sample_rate and sample_rate != chunk.sample_rate:
                raise ValueError("sample rate changed")
            if not chunk.samples:
                continue
            sample_rate = chunk.sample_rate
            chunks += 1
            if first_chunk is None:
                first_chunk = arrival
            received.append((arrival, chunk))
            duration_ms = len(chunk.samples) * 1000 / sample_rate
            if playback_end is None:
                playback_end = arrival + startup_buffer_ms + duration_ms
            else:
                gap = max(0.0, arrival - playback_end)
                if gap > 0.01:
                    underflows += 1
                    worst_gap = max(worst_gap, gap)
                playback_end = max(playback_end, arrival) + duration_ms
            samples += len(chunk.samples)
            if cancel_after_chunks is not None and chunks >= cancel_after_chunks:
                cancel_started = clock()
                cancel.set()
                break
    except Exception as error:
        error_name = type(error).__name__
    finally:
        close = getattr(iterator, "close", None)
        if close:
            try:
                close()
            except Exception as error:
                error_name = error_name or type(error).__name__
    ended = clock()
    # 能量、削波与摘要分析放在生成/close计时之后，避免Python逐样本扫描污染
    # 引擎RTF或人为制造块间供给间隙。runner应产出不可变tuple，实验不落盘音频。
    non_silent = clipped = 0
    for arrival, chunk in received:
        if not all(math.isfinite(x) and abs(x) <= 1.0 for x in chunk.samples):
            error_name = error_name or "ValueError"
            continue
        voiced = sum(abs(x) > 0.001 for x in chunk.samples)
        if first_voice is None and voiced >= math.ceil(sample_rate * 0.005):
            first_voice = arrival
        non_silent += voiced
        clipped += sum(abs(x) >= 0.999 for x in chunk.samples)
        pcm_digest.update(json.dumps(chunk.samples, separators=(",", ":")).encode("ascii"))
    duration = samples / sample_rate if sample_rate else 0
    return dict(case_id=case_id, seed=seed, first_pcm_ms=first_chunk, first_voiced_pcm_ms=first_voice,
                total_ms=(ended - began) * 1000, audio_seconds=duration,
                rtf=(ended - began) / duration if duration else None, chunks=chunks,
                non_silent_samples=non_silent, clipping_fraction=clipped / samples if samples else 0,
                underflows=underflows, worst_gap_ms=worst_gap, startup_buffer_ms=startup_buffer_ms,
                cancel_requested=cancel.is_set(), cancel_close_ms=(ended - cancel_started) * 1000 if cancel_started is not None else None,
                error=error_name, pcm_sha256=pcm_digest.hexdigest(),
                scope="isolated_tts_pcm; excludes_asr_llm_transport_device", quality_passed=False)


def audio_gate(baseline: dict, candidate: dict, *, human_voice_passed: bool = False,
               cancellation_passed: bool = False) -> dict:
    """自动筛查仅用于拒绝明显退化；音色/清晰度/角色与取消必须分别验收。"""
    reasons = []
    if (baseline.get("case_id"), baseline.get("seed")) != (candidate.get("case_id"), candidate.get("seed")):
        reasons.append("unpaired_case_or_seed")
    for label, result in (("baseline", baseline), ("candidate", candidate)):
        if result.get("error") or result.get("first_voiced_pcm_ms") is None or result.get("cancel_requested"):
            reasons.append(label + "_invalid_or_incomplete")
    duration = baseline.get("audio_seconds", 0)
    if duration <= 0 or not 0.8 <= candidate.get("audio_seconds", 0) / duration <= 1.2:
        reasons.append("duration_drift")
    if candidate.get("clipping_fraction", 1) > baseline.get("clipping_fraction", 0) + 0.01:
        reasons.append("clipping_regression")
    if candidate.get("underflows", 0) > baseline.get("underflows", 0) or candidate.get("worst_gap_ms", 0) > baseline.get("worst_gap_ms", 0) + 1:
        reasons.append("continuity_regression")
    automatic_passed = not reasons
    if not human_voice_passed:
        reasons.append("human_voice_quality_unverified")
    if not cancellation_passed:
        reasons.append("cancellation_and_residual_audio_unverified")
    return dict(automatic_passed=automatic_passed, eligible_for_review=not reasons, reasons=reasons,
                action="keep_baseline" if reasons else "review_end_to_end_latency_before_selection")


def ranking_gate(baseline: list[list[float]], candidate: list[list[float]], relevant: list[set[int]], *, k: int = 3) -> dict:
    """使用同一合成库/查询的分数比较 Recall@k，不重建或修改任何索引。"""
    if k < 1 or not baseline or len(baseline) != len(candidate) or len(relevant) != len(baseline):
        raise ValueError("invalid ranking inputs")
    recalls = [[], []]
    same_top1 = 0
    for left, right, labels in zip(baseline, candidate, relevant):
        if not left or len(left) != len(right) or not labels or any(i < 0 or i >= len(left) for i in labels):
            raise ValueError("invalid score row or labels")
        if not all(math.isfinite(x) for x in left + right):
            raise ValueError("nonfinite score")
        ranks = [sorted(range(len(row)), key=lambda i: (-row[i], i))[:k] for row in (left, right)]
        same_top1 += ranks[0][0] == ranks[1][0]
        for index in (0, 1):
            recalls[index].append(len(set(ranks[index]) & labels) / len(labels))
    base, cand = map(statistics.mean, recalls)
    return dict(baseline_recall_at_k=base, candidate_recall_at_k=cand, k=k,
                top1_agreement=same_top1 / len(baseline),
                automatic_passed=cand >= base and same_top1 == len(baseline),
                scope="supplied_synthetic_corpus_only; downstream_memory_answers_unverified")


def paired_benchmark(runners: dict[str, Callable], cases: Iterable[str], *, seeds=(17, 29), concurrency: int = 1) -> dict:
    """有界并发 1/2/4；轮流基线/候选，排队不作音频准备，dialog 不等候凑批。"""
    if concurrency not in (1, 2, 4) or not runners:
        raise ValueError("concurrency must be 1, 2 or 4")
    cases = tuple(cases)
    jobs = []
    names = tuple(runners)
    for index, seed in enumerate(seeds):
        for case in cases:
            for name in names if index % 2 == 0 else names[::-1]:
                jobs.append((name, case, seed))
    # 不同 engine 不同时占同一 GPU；同 engine 的并发由调用方为隔离实例加锁/实现。
    records = []
    for offset in range(0, len(jobs), len(names)):
        group = jobs[offset:offset + len(names)]
        for name, case, seed in group:
            began = perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(measure, runners[name], case, seed) for _ in range(concurrency)]
                batch = [future.result() for future in futures]
            records.extend(dict(engine=name, concurrency=concurrency, repetition=i, **record) for i, record in enumerate(batch))
            for record in records[-len(batch):]:
                record["group_wall_ms"] = (perf_counter() - began) * 1000
                record["group_wall_includes_analysis"] = True
    return dict(schema_version=1, created_at=datetime.now(timezone.utc).isoformat(), records=records,
                real_gpu_verified=False, device_first_answer_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", required=True, help="仅确定性 CPU 合成 PCM，不加载模型")
    parser.add_argument("--concurrency", type=int, choices=(1, 2, 4), default=1)
    args = parser.parse_args()

    def synthetic(case, seed, cancel):
        del case, seed
        for _ in range(3):
            if cancel.is_set():
                return
            yield AudioChunk(tuple(0.1 * math.sin(i / 8) for i in range(800)), 16000)

    report = paired_benchmark({"synthetic_baseline": synthetic, "synthetic_candidate": synthetic}, ("short", "long"), concurrency=args.concurrency)
    report["evidence_kind"] = "cpu_mock_only"
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
