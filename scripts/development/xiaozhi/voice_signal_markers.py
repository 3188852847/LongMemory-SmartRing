"""一次本机发声外侧按键标记及离线计数对齐；无网络、麦克风或正文存储。"""

import argparse
import json
from pathlib import Path
import time


LIMIT = 2**31 - 1
INPUT_KEYS = ("queue_put", "vad_check", "vad_speech", "formal_begin", "speech_begin", "abort_begin", "abort_return")
PAIR_KEYS = ("valid", "invalid", "zero_input", "below_floor", "original_error", "observer_error")


def _clock():
    return time.monotonic_ns() // 1_000_000, time.time_ns() // 1_000_000


def record(path, *, ask=input, clock=_clock):
    """起键后再说、说完再按止键：只是手动外侧括号，绝非精确音频边界。"""
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        def write(event):
            monotonic, unix = clock()
            row = dict(version=1, event=event, monotonic_ms=monotonic, unix_ms=unix,
                       timing_kind="manual_outer_bracket_not_exact_voice_boundary")
            stream.write(json.dumps(row, allow_nan=False) + "\n")
            stream.flush()
        write("ready")
        try:
            for event, prompt in (("speech_start", "准备好后按回车，随即说一次口令；输入 q 取消："),
                                  ("speech_end", "说完后立即按回车；输入 q 取消：")):
                # 任意输入文字均不保存；最多三次错误输入后取消，不循环要求实测。
                for _ in range(3):
                    answer = ask(prompt)
                    if answer == "":
                        write(event)
                        break
                    if answer == "q":
                        write("cancelled")
                        return "cancelled"
                else:
                    write("cancelled")
                    return "cancelled"
        except (KeyboardInterrupt, EOFError):
            write("cancelled")
            return "cancelled"
    return "marked_not_audio_verified"


def _count(value):
    return type(value) is int and 0 <= value < LIMIT


def _anchor(row):
    """采样器必须用同机单调时钟包住整组device+signal请求。"""
    before, after = row.get("monotonic_before_ms"), row.get("monotonic_after_ms")
    signal, device = row.get("signal_v2", row.get("signal", {})), row.get("device", {})
    clock, generation = signal.get("clock_ms"), signal.get("observation_generation")
    if not (all(type(value) is int and value >= 0 for value in (before, after, clock))
            and before <= clock <= after and signal.get("state") == "observed"
            and signal.get("version") == 2 and signal.get("kind") == "aec_pairs_supplement"
            and device.get("ready") is True and type(generation) is str and len(generation) == 16
            and all(character in "0123456789abcdef" for character in generation)):
        return None
    counts = device.get("voice_input_observation", {}).get("counts") or {}
    if not all(_count(counts.get(key)) for key in INPUT_KEYS):
        return None
    pairs = signal.get("aec_pairs")
    total = pairs.get("total") if type(pairs) is dict else None
    if total is not None and not (type(total) is dict and all(_count(total.get(key)) for key in PAIR_KEYS)
            and type(total.get("ratio_bins")) is list and len(total["ratio_bins"]) == 6
            and all(_count(value) for value in total["ratio_bins"])):
        return None
    return {"before": before, "after": after, "clock_ms": clock, "observation_id": generation,
            "input": {key: counts[key] for key in INPUT_KEYS},
            "pairs": None if total is None else {key: total[key] for key in (*PAIR_KEYS, "ratio_bins")}}


def _decreased(first, last):
    if any(last["input"][key] < first["input"][key] for key in INPUT_KEYS):
        return True
    a, b = first["pairs"], last["pairs"]
    return (a is not None and b is not None and (any(b[key] < a[key] for key in PAIR_KEYS)
            or any(y < x for x, y in zip(a["ratio_bins"], b["ratio_bins"]))))


def align(markers, samples):
    """仅累计差分；任何代次变化、饱和、下降或缺锚点均不给有效差分。"""
    starts = [row.get("monotonic_ms") for row in markers if row.get("event") == "speech_start"]
    ends = [row.get("monotonic_ms") for row in markers if row.get("event") == "speech_end"]
    if (any(row.get("event") == "cancelled" for row in markers) or len(starts) != 1 or len(ends) != 1
            or not all(type(value) is int and value >= 0 for value in starts + ends) or starts[0] > ends[0]):
        return {"state": "invalid_or_cancelled_marker"}
    try:
        anchors = [_anchor(row) for row in samples]
    except (TypeError, AttributeError, KeyError):
        return {"state": "malformed_samples"}
    left = [(index, row) for index, row in enumerate(anchors) if row and row["after"] <= starts[0]]
    right = [(index, row) for index, row in enumerate(anchors) if row and row["before"] >= ends[0]]
    if not left or not right:
        return {"state": "missing_outer_sample_brackets"}
    li, first = max(left, key=lambda item: item[1]["after"])
    ri, last = min(right, key=lambda item: item[1]["before"])
    if li > ri or any(row is None or row["observation_id"] != first["observation_id"] for row in anchors[li:ri + 1]):
        return {"state": "generation_changed_or_unknown_or_saturated"}
    if any(b["clock_ms"] < a["clock_ms"] for a, b in zip(anchors[li:ri], anchors[li + 1:ri + 1])):
        return {"state": "clock_not_monotonic"}
    if any(_decreased(a, b) for a, b in zip(anchors[li:ri], anchors[li + 1:ri + 1])):
        return {"state": "counter_decreased"}
    result = {"state": "bounded_cumulative_difference_not_voice_verification",
              "observation_generation": first["observation_id"], "speech_start_ms": starts[0], "speech_end_ms": ends[0],
              "sample_before_ms": first["before"], "sample_after_ms": last["after"],
              "start_uncertainty_ms": starts[0] - first["before"],
              "end_uncertainty_ms": last["after"] - ends[0],
              "input_delta": {key: last["input"][key] - first["input"][key] for key in INPUT_KEYS},
              "pair_delta": None}
    if first["pairs"] is not None and last["pairs"] is not None:
        a, b = first["pairs"], last["pairs"]
        if (any(b[key] < a[key] for key in PAIR_KEYS)
                or any(y < x for x, y in zip(a["ratio_bins"], b["ratio_bins"]))):
            return {"state": "counter_decreased"}
        result["pair_delta"] = {key: b[key] - a[key] for key in PAIR_KEYS}
        result["pair_delta"]["ratio_bins"] = [y - x for x, y in zip(a["ratio_bins"], b["ratio_bins"])]
    return result


def _read(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    mark = modes.add_parser("record")
    mark.add_argument("--output", type=Path, required=True)
    compare = modes.add_parser("align")
    compare.add_argument("--markers", type=Path, required=True)
    compare.add_argument("--samples", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.mode == "record":
        print(record(args.output))
    else:
        value = align(_read(args.markers), _read(args.samples))
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, allow_nan=False, indent=2)
            stream.write("\n")
        print(value["state"])


if __name__ == "__main__":
    main()
