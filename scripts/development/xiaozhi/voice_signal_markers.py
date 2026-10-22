"""一次本机发声外侧按键标记及离线计数对齐；无网络、麦克风或正文存储。"""

import argparse
import json
from pathlib import Path
import time


LIMIT = 2**31 - 1
INPUT_KEYS = ("queue_put", "vad_check", "vad_speech", "formal_begin", "speech_begin", "abort_begin", "abort_return")
PAIR_KEYS = ("valid", "invalid", "zero_input", "below_floor", "original_error", "observer_error")
SIGNAL_FIELDS = {"version", "kind", "state", "clock_ms", "observation_generation", "aec_pairs"}
MARKER_FIELDS = {"version", "event", "monotonic_ms", "unix_ms", "timing_kind"}
TIMING_KIND = "manual_outer_bracket_not_exact_voice_boundary"
RATIO_EDGES = [.1, .25, .5, .9, 1.1]


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


def _milliseconds(value):
    return type(value) is int and 0 <= value <= 2**63 - 1


def _marker_window(markers):
    if type(markers) is not list or len(markers) != 3:
        return None
    for row in markers:
        if (type(row) is not dict or set(row) != MARKER_FIELDS or type(row["version"]) is not int
                or row["version"] != 1 or row["timing_kind"] != TIMING_KIND
                or not _milliseconds(row["monotonic_ms"]) or not _milliseconds(row["unix_ms"])):
            return None
    if [row["event"] for row in markers] != ["ready", "speech_start", "speech_end"]:
        return None
    if not all(a["monotonic_ms"] <= b["monotonic_ms"] for a, b in zip(markers, markers[1:])):
        return None
    return markers[1]["monotonic_ms"], markers[2]["monotonic_ms"]


def _valid_pairs(pairs):
    if type(pairs) is not dict or set(pairs) != {"rms_floor_pcm16", "ratio_edges", "total"}:
        return False
    if (type(pairs["rms_floor_pcm16"]) is not int or pairs["rms_floor_pcm16"] != 500
            or type(pairs["ratio_edges"]) is not list or pairs["ratio_edges"] != RATIO_EDGES
            or any(type(value) not in (int, float) for value in pairs["ratio_edges"])):
        return False
    total = pairs["total"]
    return (type(total) is dict and set(total) == {*PAIR_KEYS, "ratio_bins"}
            and all(_count(total[key]) for key in PAIR_KEYS)
            and type(total["ratio_bins"]) is list and len(total["ratio_bins"]) == 6
            and all(_count(value) for value in total["ratio_bins"])
            and total["valid"] == total["zero_input"] + total["below_floor"] + sum(total["ratio_bins"]))


def _anchor(row):
    """采样器必须用同机单调时钟包住整组device+signal请求。"""
    before, after = row.get("monotonic_before_ms"), row.get("monotonic_after_ms")
    signal, device = row.get("signal_v2", row.get("signal", {})), row.get("device", {})
    if type(signal) is not dict or set(signal) != SIGNAL_FIELDS:
        return None
    clock, generation = signal.get("clock_ms"), signal.get("observation_generation")
    if not (all(_milliseconds(value) for value in (before, after, clock))
            and before <= clock <= after and signal.get("state") == "observed"
            and type(signal["version"]) is int and signal["version"] == 2 and signal["kind"] == "aec_pairs_supplement"
            and device.get("ready") is True and type(generation) is str and len(generation) == 16
            and all(character in "0123456789abcdef" for character in generation)):
        return None
    counts = device.get("voice_input_observation", {}).get("counts") or {}
    if not all(_count(counts.get(key)) for key in INPUT_KEYS):
        return None
    pairs = signal["aec_pairs"]
    if pairs is not None and not _valid_pairs(pairs):
        return None
    total = None if pairs is None else pairs["total"]
    return {"before": before, "after": after, "clock_ms": clock, "observation_id": generation,
            "input": {key: counts[key] for key in INPUT_KEYS},
            "pairs": None if total is None else {key: total[key] for key in (*PAIR_KEYS, "ratio_bins")}}


def _decreased(first, last):
    if any(last["input"][key] < first["input"][key] for key in INPUT_KEYS):
        return True
    a, b = first["pairs"], last["pairs"]
    return (a is not None and b is not None and (any(b[key] < a[key] for key in PAIR_KEYS)
            or any(y < x for x, y in zip(a["ratio_bins"], b["ratio_bins"]))))


def _ordered_requests(samples):
    previous = None
    for row in samples:
        if type(row) is not dict:
            return False
        before, after = row.get("monotonic_before_ms"), row.get("monotonic_after_ms")
        if not _milliseconds(before) or not _milliseconds(after) or before > after:
            return False
        if previous is not None and (before < previous[1] or (before, after) == previous):
            return False
        previous = before, after
    return True


def align(markers, samples):
    """仅v2同代次累计差分；device仅为邻近背景，HTTP括号不证明跨端点原子。"""
    window = _marker_window(markers)
    if window is None:
        return {"state": "invalid_or_cancelled_marker"}
    start, end = window
    if type(samples) is not list:
        return {"state": "malformed_samples"}
    # 先校验原文件全序，防止先挑首末时把乱序的窗口内行排到范围外。
    if not _ordered_requests(samples):
        return {"state": "request_brackets_not_monotonic"}
    try:
        anchors = [_anchor(row) for row in samples]
    except (TypeError, AttributeError, KeyError):
        return {"state": "malformed_samples"}
    left = [(index, row) for index, row in enumerate(anchors) if row and row["after"] <= start]
    right = [(index, row) for index, row in enumerate(anchors) if row and row["before"] >= end]
    if not left or not right:
        return {"state": "missing_outer_sample_brackets"}
    li, first = max(left, key=lambda item: item[1]["after"])
    ri, last = min(right, key=lambda item: item[1]["before"])
    if li > ri or any(row is None or row["observation_id"] != first["observation_id"] for row in anchors[li:ri + 1]):
        return {"state": "generation_changed_or_unknown_or_saturated"}
    selected = anchors[li:ri + 1]
    if any(b["clock_ms"] < a["clock_ms"] for a, b in zip(anchors[li:ri], anchors[li + 1:ri + 1])):
        return {"state": "clock_not_monotonic"}
    if any(_decreased(a, b) for a, b in zip(anchors[li:ri], anchors[li + 1:ri + 1])):
        return {"state": "counter_decreased"}
    gaps = [{"after_ms": a["after"], "before_ms": b["before"], "gap_ms": b["before"] - a["after"]}
            for a, b in zip(selected, selected[1:]) if b["before"] > a["after"]]
    result = {"state": "bounded_cumulative_difference_not_voice_verification",
              "observation_generation": first["observation_id"], "speech_start_ms": start, "speech_end_ms": end,
              "sample_before_ms": first["before"], "sample_after_ms": last["after"],
              "start_uncertainty_ms": start - first["before"],
              "end_uncertainty_ms": last["after"] - end,
              "sampling": {"kind": "between_request_groups_not_audio_loss",
                           "sample_count": len(selected), "gap_count": len(gaps),
                           "max_gap_ms": max((item["gap_ms"] for item in gaps), default=0),
                           "total_gap_ms": sum(item["gap_ms"] for item in gaps),
                           "largest_gaps": sorted(gaps, key=lambda item: item["gap_ms"], reverse=True)[:3]},
              "device_background": {"kind": "time_nearby_snapshots_not_atomic_or_same_connection_proof",
                  "before": {"group_before_ms": first["before"], "group_after_ms": first["after"],
                             "counts": first["input"]},
                  "after": {"group_before_ms": last["before"], "group_after_ms": last["after"],
                            "counts": last["input"]}},
              "pair_delta": None, "pair_state": "observed"}
    if first["pairs"] is None:
        result["pair_state"] = "baseline_unknown"
    elif any(row["pairs"] is None for row in selected):
        result["pair_state"] = "unknown_within_window"
    else:
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
