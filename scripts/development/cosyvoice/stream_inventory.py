"""按模型 WAV 块可用时刻估算连续播放库存，只依赖 Python 标准库。

输入 at_ms 是完整模型块可用的相对时刻，audio_ms 是该块真实 PCM 时长。
结果不包含网络、编码、设备排队和扬声器回执，也不能判断自然语音停顿。
假定所有块属于同一条连续 PCM 流；各块不足 60 ms 的尾部留给下一块，
仅在最后一块代表的 EOS（音频流结束）补齐一个最终帧。

示例：python stream_inventory.py chunks.json --startup-buffer-ms 360
也可将 JSON 数组传入标准输入，并省略 chunks.json 参数。
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from fractions import Fraction
import json
import math
from pathlib import Path
import sys


PACKET_MS = 60


def _number(value, name: str, *, positive: bool = False) -> Fraction:
    """保留输入的十进制精度，避免逐块浮点加法错误地多补一个帧。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}_must_be_finite_number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < 0 or (positive and value == 0):
        bound = "positive" if positive else "nonnegative"
        raise ValueError(f"{name}_must_be_finite_{bound}")
    return Fraction(str(value))


def _milliseconds(value: Fraction) -> float:
    return round(float(value), 6)


def estimate_inventory(
    chunks: Iterable[Mapping], *, startup_buffer_ms: float = 0,
    startup_delay_ms: float = 0,
) -> dict:
    """模拟因果启动和耗尽后立即续播，返回服务器侧预计欠载。

    startup_buffer_ms 是开播所需的已到达可播放时长，0 表示首个完整帧
    可用就开播。其他非负值按完整帧比较（例如 61 ms 需要 120 ms）；
    最后一个块到达后若仍不足目标，则以剩余音频触发开播，不无限等待。
    startup_delay_ms 是达到水位（或 EOS 兜底）后额外等待的固定时长；
    截止时刻在触发时确定，之后到达的音频只增加库存，不能提前首播。
    初始等待不是欠载；欠载只累计开播后、下一批可播放帧到达前的空档。

    输入须非空、at_ms 有限非负且不递减、audio_ms 有限且严格为正。
    不修改输入；所有帧在其所属累计音频足量时才可用，不使用未来缺口
    选择开播点。该估算也不引入欠载后的额外重缓冲策略。
    """
    target = _number(startup_buffer_ms, "startup_buffer_ms")
    delay = _number(startup_delay_ms, "startup_delay_ms")
    try:
        records = list(chunks)
    except TypeError as exc:
        raise ValueError("chunks_must_be_nonempty_iterable") from exc
    if not records:
        raise ValueError("chunks_must_be_nonempty_iterable")

    validated = []
    previous = Fraction(0)
    for index, chunk in enumerate(records):
        if not isinstance(chunk, Mapping) or "at_ms" not in chunk or "audio_ms" not in chunk:
            raise ValueError(f"chunk_{index}_requires_at_ms_and_audio_ms")
        at = _number(chunk["at_ms"], f"chunk_{index}_at_ms")
        audio = _number(chunk["audio_ms"], f"chunk_{index}_audio_ms", positive=True)
        if at < previous:
            raise ValueError("chunk_at_ms_must_be_nondecreasing")
        validated.append((at, audio))
        previous = at

    cumulative_audio = Fraction(0)
    packet_count = 0
    buffered = Fraction(0)
    first_playback = None
    first_packet_available = None
    end = None
    gaps = []
    details = []
    buffer_at_start = Fraction(0)
    start_reason = None
    startup_trigger = None
    startup_deadline = None

    def start_playback():
        nonlocal first_playback, buffer_at_start, end
        first_playback = startup_deadline
        buffer_at_start = buffered
        end = startup_deadline + buffered

    for index, (at, audio) in enumerate(validated):
        # 模拟独立时钟：下一块在截止时刻之后到达时，先在已约定时刻开播。
        # 因而既不会等未来块来驱动首播，也不会借未来块消除已发生的欠载。
        if end is None and startup_deadline is not None and startup_deadline < at:
            start_playback()
        eos = index == len(validated) - 1
        cumulative_audio += audio
        # 非末块只能释放完整帧；最后才将整条 PCM 的尾部向上补齐。
        packet_total = cumulative_audio // PACKET_MS
        if eos and cumulative_audio % PACKET_MS:
            packet_total += 1
        released = packet_total - packet_count
        packet_count = packet_total
        playable = released * PACKET_MS
        gap = Fraction(0)
        queued_before = buffered if end is None else max(Fraction(0), end - at)

        if released and first_packet_available is None:
            first_packet_available = at
        if end is None:
            buffered += playable
            # 触发后截止时刻保持不变；EOS 不会取消已经约定的安全等候。
            if startup_deadline is None and buffered > 0 and (buffered >= target or eos):
                startup_trigger = at
                startup_deadline = at + delay
                start_reason = (
                    "first_packet" if target == 0 else
                    "buffer_target_reached" if buffered >= target else
                    "eos_buffer_fallback"
                )
            if startup_deadline is not None and startup_deadline <= at:
                start_playback()
        elif released:
            # 没有新帧的块不会结束欠载；到真正有帧时才一次结算整个空档。
            gap = max(Fraction(0), at - end)
            end = max(at, end) + playable
            if gap:
                gaps.append(gap)

        details.append({
            "at_ms": _milliseconds(at),
            "audio_ms": _milliseconds(audio),
            "cumulative_audio_ms": _milliseconds(cumulative_audio),
            "released_packet_count": released,
            "released_playable_ms": playable,
            "queued_before_ms": _milliseconds(queued_before),
            "queued_after_ms": _milliseconds(buffered if end is None else max(Fraction(0), end - at)),
            "gap_before_ms": _milliseconds(gap),
            "playback_started": end is not None,
            "eos": eos,
        })

    if end is None:
        # EOS 之后无需新块唤醒；按已经确定的时钟期限播放所有剩余帧。
        start_playback()
    playable_total = packet_count * PACKET_MS
    return {
        "measurement_scope": "model_chunk_availability_estimate_not_speaker_receipt",
        "startup_policy": "causal_fixed_buffer_then_fixed_delay_with_eos_fallback",
        "packet_ms": PACKET_MS,
        "startup_buffer_ms": _milliseconds(target),
        "startup_delay_ms": _milliseconds(delay),
        "startup_trigger_ms": _milliseconds(startup_trigger),
        "chunk_count": len(validated),
        "first_available_ms": _milliseconds(validated[0][0]),
        "first_packet_available_ms": _milliseconds(first_packet_available),
        "first_playback_ms": _milliseconds(first_playback),
        "startup_wait_ms": _milliseconds(first_playback - validated[0][0]),
        "startup_buffer_at_start_ms": _milliseconds(buffer_at_start),
        "start_reason": start_reason,
        "max_gap_ms": _milliseconds(max(gaps, default=Fraction(0))),
        "total_gap_ms": _milliseconds(sum(gaps, Fraction(0))),
        "gap_count": len(gaps),
        "estimated_end_ms": _milliseconds(end),
        "model_eos_ms": _milliseconds(validated[-1][0]),
        "packet_count": packet_count,
        "audio_ms": _milliseconds(cumulative_audio),
        "playable_ms": playable_total,
        "padding_ms": _milliseconds(playable_total - cumulative_audio),
        "chunks": details,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, help="JSON 块数组；省略时读取标准输入")
    parser.add_argument("--startup-buffer-ms", type=float, default=0)
    parser.add_argument("--startup-delay-ms", type=float, default=0)
    args = parser.parse_args(argv)
    try:
        if args.input is None:
            chunks = json.load(sys.stdin)
        else:
            chunks = json.loads(args.input.read_text(encoding="utf-8-sig"))
        result = estimate_inventory(
            chunks, startup_buffer_ms=args.startup_buffer_ms,
            startup_delay_ms=args.startup_delay_ms,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
