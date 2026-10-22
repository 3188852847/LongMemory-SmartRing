"""一次本机发声外侧按键标记及离线计数对齐；无网络、麦克风或正文存储。"""

import argparse
import ctypes
import json
import os
from pathlib import Path
import time


LIMIT = 2**31 - 1
INPUT_KEYS = ("queue_put", "vad_check", "vad_speech", "formal_begin", "speech_begin", "abort_begin", "abort_return")
PAIR_KEYS = ("valid", "invalid", "zero_input", "below_floor", "original_error", "observer_error")
SIGNAL_FIELDS = {"version", "kind", "state", "clock_ms", "observation_generation", "aec_pairs"}
MARKER_FIELDS = {"version", "event", "monotonic_ms", "unix_ms", "timing_kind"}
TIMING_KIND = "manual_outer_bracket_not_exact_voice_boundary"
RATIO_EDGES = [.1, .25, .5, .9, 1.1]
LIVE_PRODUCER_KEYS = ("producer_adaptive_buffer", "producer_incremental_pcm", "producer_buffered_pcm")
_CONSOLE_INPUT = None


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


def _live_samples(path):
    """只读最近完整行；尾部正在写入的半行不作为一次观测。"""
    try:
        with Path(path).open("rb") as stream:
            stream.seek(0, 2)
            start = max(0, stream.tell() - 262144)
            stream.seek(start)
            data = stream.read()
        if start:
            data = data.partition(b"\n")[2]
        complete = data.split(b"\n")[:-1]
        return [json.loads(line) for line in complete[-32:] if line.strip()]
    except (OSError, UnicodeError, ValueError):
        return None


class _ConsoleChar(ctypes.Union):
    _fields_ = [("UnicodeChar", ctypes.c_uint16), ("AsciiChar", ctypes.c_char)]


class _ConsoleKeyEvent(ctypes.Structure):
    _fields_ = [("bKeyDown", ctypes.c_int32), ("wRepeatCount", ctypes.c_uint16),
                ("wVirtualKeyCode", ctypes.c_uint16), ("wVirtualScanCode", ctypes.c_uint16),
                ("uChar", _ConsoleChar), ("dwControlKeyState", ctypes.c_uint32)]


class _ConsoleEvent(ctypes.Union):
    _fields_ = [("KeyEvent", _ConsoleKeyEvent), ("reserved", ctypes.c_ubyte * 16)]


class _ConsoleRecord(ctypes.Structure):
    _fields_ = [("EventType", ctypes.c_uint16), ("Event", _ConsoleEvent)]


class _ConsoleKeyReader:
    """只认可本控制台观察到的按下边沿；重复字符不等于释放后重新按下。"""
    def __init__(self, read_event):
        self.read_event, self.held = read_event, set()

    def read(self):
        record = self.read_event()
        if record is None:
            return None
        if record.EventType != 1:  # KEY_EVENT；不把方向键后半码或窗口事件当文字。
            return "other"
        key = record.Event.KeyEvent
        virtual = key.wVirtualKeyCode
        if virtual not in (0x0D, 0x48, 0x51, 0x43):  # Enter/H/Q/C，仅暂存有关键的按下状态。
            return "other"
        control = key.dwControlKeyState
        identity = (virtual, key.wVirtualScanCode, bool(control & 0x0100))
        if not key.bKeyDown:
            self.held.discard(identity)
            return "other"
        char = chr(key.uChar.UnicodeChar)
        # 取消无需新确认边沿，长按Q/Ctrl-C也应立即安全结束。
        if char == "\x03" or (virtual == 0x43 and control & 0x000C):
            return "cancel"
        if virtual == 0x51 and char.lower() == "q" and not control & 0x000F:
            return "cancel"
        already_held = any(item[0] == virtual for item in self.held)
        self.held.add(identity)
        if already_held:
            return "other"
        if key.wRepeatCount != 1:
            return "other"  # 合并的自动重复同样不能充当一次新的确认。
        if virtual == 0x0D and not control & 0x000F:
            return "enter"
        if not control & 0x000F:  # 不把Ctrl/Alt组合键误作普通H/Q。
            if virtual == 0x48 and char.lower() == "h":
                return "heard"
        return "other"


class _WindowsConsoleInput:
    """仅读当前STD_INPUT_HANDLE的控制台事件；不装钩子、不改变控制台模式。"""
    def __init__(self, api=None):
        if api is None:
            if os.name != "nt":
                raise OSError("console_input_unavailable")
            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.GetStdHandle.argtypes = [ctypes.c_uint32]
            api.GetStdHandle.restype = ctypes.c_void_p
            api.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            api.GetConsoleMode.restype = ctypes.c_int32
            api.GetNumberOfConsoleInputEvents.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            api.GetNumberOfConsoleInputEvents.restype = ctypes.c_int32
            api.ReadConsoleInputW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ConsoleRecord),
                                            ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
            api.ReadConsoleInputW.restype = ctypes.c_int32
        self.api = api
        self.handle = api.GetStdHandle(0xFFFFFFF6)  # STD_INPUT_HANDLE = -10
        mode = ctypes.c_uint32()
        if self.handle in (None, 0, ctypes.c_void_p(-1).value) or not api.GetConsoleMode(self.handle, ctypes.byref(mode)):
            raise OSError("console_input_unavailable")
        self.reader = _ConsoleKeyReader(self._read_event)

    def _read_event(self):
        count = ctypes.c_uint32()
        if not self.api.GetNumberOfConsoleInputEvents(self.handle, ctypes.byref(count)):
            raise OSError("console_input_unavailable")
        if count.value == 0:
            return None
        record, read = _ConsoleRecord(), ctypes.c_uint32()
        if not self.api.ReadConsoleInputW(self.handle, ctypes.byref(record), 1, ctypes.byref(read)) or read.value != 1:
            raise OSError("console_input_unavailable")
        return record

    def read(self):
        return self.reader.read()


def _console_key():
    global _CONSOLE_INPUT
    if _CONSOLE_INPUT is None:
        _CONSOLE_INPUT = _WindowsConsoleInput()
    return _CONSOLE_INPUT.read()


def _keys(read_key):
    result = []
    for _ in range(64):
        value = read_key()
        if value is None:
            return result, False
        result.append(value)
    return result, True


class _Gate:
    """v2代次及累计可核验；device模式/输出只是时间邻近启发门禁。"""
    def __init__(self, started, freshness_ms):
        self.started, self.freshness = started, freshness_ms
        self.generation = None
        self.last_seen = None
        self.previous = None
        self.paired = []
        self.latest = None
        self.reason = None
        self.ready = False
        self.last_update = started
        self.delivery_seen = False

    def update(self, rows, now, *, pre_start):
        self.ready = False
        if now < self.last_update or (self.generation is not None and now - self.last_update > self.freshness):
            self.reason = "gate_processing_gap_or_clock_rewound"
            return
        self.last_update = now
        if rows is None or (not rows and self.generation is not None):
            if self.generation is not None:
                self.reason = "samples_unavailable"
            return
        if not _ordered_requests(rows):
            self.reason = "request_brackets_not_monotonic"
            return
        if self.last_seen is not None and rows and rows[-1]["monotonic_after_ms"] < self.last_seen:
            self.reason = "sample_file_rewound"
            return
        for row in rows:
            after = row["monotonic_after_ms"]
            if after < self.started or (self.last_seen is not None and after <= self.last_seen):
                continue
            self.last_seen = after
            if after > now:
                self.reason = "sample_clock_in_future"
                return
            try:
                anchor = _anchor(row)
                if anchor is None:
                    self.paired = []
                    if self.generation is not None:
                        self.reason = "gate_snapshot_unavailable"
                        return
                    continue
                if self.generation is None:
                    # 不从旧文件的过期行绑定代次。
                    if now - after > self.freshness:
                        continue
                    self.generation = anchor["observation_id"]
                if anchor["observation_id"] != self.generation:
                    self.reason = "generation_changed"
                    return
                if self.previous is not None and _decreased(self.previous, anchor):
                    self.reason = "counter_decreased"
                    return
                self.previous, self.latest = anchor, anchor
                device = row["device"]
                delivery, output = device.get("cosy_delivery", {}), device.get("voice_interruption", {})
                fallback = delivery.get("outcomes", {}).get("fallback")
                if not (delivery.get("requested_mode") == delivery.get("effective_mode") == "adaptive"
                        and delivery.get("failure_code") is None
                        and delivery.get("restart_required") is False and _count(fallback) and fallback == 0):
                    self.reason = "mode_not_adaptive_or_fallback"
                    return
                if delivery.get("state") == "not_observed" and not self.delivery_seen:
                    continue  # 尚未调用TTS的合法起始状态，不能当实答，也不误判回退。
                if delivery.get("state") != "configured":
                    self.reason = "delivery_observation_lost"
                    return
                self.delivery_seen = True
                counts = output.get("counts", {})
                answer, first = counts.get("answer_send_returned"), counts.get("first_answer_send_returned")
                live = [counts.get(key) for key in LIVE_PRODUCER_KEYS]
                if (type(output.get("active_output")) is not bool or not _count(answer) or not _count(first)
                        or not all(_count(value) for value in live)):
                    self.reason = "output_metadata_unknown_or_saturated"
                    return
                if anchor["pairs"] is None or anchor["pairs"]["valid"] == 0:
                    if self.paired:
                        self.reason = "paired_baseline_lost"
                        return
                    continue
                self.paired.append((anchor, output["active_output"], answer, first, sum(live) > 0))
                self.paired = self.paired[-2:]
            except (TypeError, AttributeError, KeyError):
                self.reason = "malformed_gate_sample"
                return
        if self.latest is None:
            return
        if now - self.latest["after"] > self.freshness:
            self.reason = "gate_sample_expired"
            return
        if len(self.paired) == 2:
            a, b = self.paired
            if a[2] > b[2] or a[3] > b[3]:
                self.reason = "output_counter_decreased"
                return
            self.ready = (all(0 <= now - item[0]["after"] <= self.freshness for item in (a, b))
                          and a[1] and b[1] and b[2] > a[2] and b[3] > 0)
            self.ready = self.ready and b[4]
        # 起键后不以output停止/答案包不再增长取消：可能正是成功打断。
        if not pre_start:
            self.ready = self.latest["pairs"] is not None


def record_gated(path, samples_path, *, timeout_seconds=90, freshness_ms=3000,
                 read_samples=None, read_key=_console_key, clock=_clock, wait=time.sleep, notify=print):
    """只消费既有采样；先H确认听到实答，再一次新Enter起键，终键后等外侧组。"""
    if not 0 < timeout_seconds <= 240 or not 0 < freshness_ms <= 30000:
        raise ValueError("invalid_gate_limits")
    if Path(path).resolve() == Path(samples_path).resolve():
        raise ValueError("marker_and_sample_paths_must_differ")
    read_samples = read_samples or (lambda: _live_samples(samples_path))
    started = clock()[0]
    gate = _Gate(started, freshness_ms)
    phase, end, announced = "waiting", None, None
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        def write(event):
            monotonic, unix = clock()
            stream.write(json.dumps(dict(version=1, event=event, monotonic_ms=monotonic, unix_ms=unix,
                timing_kind=TIMING_KIND), allow_nan=False) + "\n")
            stream.flush()
            return monotonic
        def cancel(reason):
            write("cancelled")
            message = {"operator": "操作者取消", "gate_timeout": "达到本轮总时限",
                "clock_invalid": "本机计时不可用", "samples_unavailable": "采样文件不可用或已清空",
                "gate_processing_gap_or_clock_rewound": "提示进程停顿过久或时钟倒退",
                "request_brackets_not_monotonic": "采样请求时间乱序", "sample_file_rewound": "采样文件倒退",
                "sample_clock_in_future": "采样时钟与本机不匹配", "gate_snapshot_unavailable": "就绪观测已丢失",
                "generation_changed": "观察代次已变化", "counter_decreased": "观测计数下降",
                "mode_not_adaptive_or_fallback": "测试模式变化或已发生回退",
                "delivery_observation_lost": "实答生成观测已丢失",
                "output_metadata_unknown_or_saturated": "正文输出观测未知或计数已饱和",
                "paired_baseline_lost": "成对观测基线已丢失", "malformed_gate_sample": "采样格式不符",
                "gate_sample_expired": "采样已过期", "output_counter_decreased": "正文输出计数下降",
                "console_input_unavailable": "当前控制台输入不可用，未回退到无门禁录制",
                "gate_lost_before_start": "起键前就绪条件已失效"}.get(reason, "诊断门禁条件不再满足")
            notify("已取消：" + message + "；不自动重试。")
            return "cancelled_" + reason
        try:
            while True:
                now = clock()[0]
                if not _milliseconds(now) or now < started:
                    return cancel("clock_invalid")
                if now - started >= timeout_seconds * 1000:
                    return cancel("gate_timeout")
                gate.update(read_samples(), now, pre_start=phase not in ("speaking", "outer"))
                keys, flooded = _keys(read_key)
                if "cancel" in keys:
                    return cancel("operator")
                if gate.reason:
                    return cancel(gate.reason)
                if phase == "waiting":
                    status = "等待圆屏连接与正文输出；此时按Enter/H不会开始记录。"
                    if gate.ready and not flooded:
                        # 同一轮已排空的按键全部丢弃，不能把门禁前按键转成确认。
                        phase = "heard"
                        status = "软件门禁满足（非声学证明）。确实听到设备正文后按英文H，无需回车。"
                elif phase in ("heard", "start"):
                    if not gate.ready:
                        return cancel("gate_lost_before_start")
                    status = "确实听到设备正文后按英文H，无需回车。" if phase == "heard" else "已确认听到；看到本提示后新按Enter，随后说一次口令。"
                    if not flooded and phase == "heard" and "heard" in keys:
                        write("ready")
                        phase = "start"
                        status = "已确认听到；看到本提示后新按Enter，随后说一次口令。"
                    elif not flooded and phase == "start" and "enter" in keys:
                        # 按键前再读取最新组，避免只靠旧门禁放行。
                        gate.update(read_samples(), clock()[0], pre_start=True)
                        if gate.reason or not gate.ready:
                            return cancel(gate.reason or "gate_lost_before_start")
                        write("speech_start")
                        phase, status = "speaking", "起键已记录。说完后立即新按Enter结束；Q取消。"
                elif phase == "speaking":
                    status = "说完后立即新按Enter结束；Q取消。"
                    if not flooded and "enter" in keys:
                        end = write("speech_end")
                        phase, status = "outer", "终键已记录，等待终键之后的一组完整采样。"
                else:
                    status = "等待终键之后的一组完整采样。"
                    if gate.latest is not None and gate.latest["before"] >= end:
                        notify("单次标记完成；不代表语音或实机验收通过。")
                        return "marked_not_audio_verified"
                if "enter" in keys and phase in ("waiting", "heard"):
                    notify("本次Enter过早，已丢弃；不会延后补记。")
                if status != announced:
                    notify(status)
                    announced = status
                wait(.1)
        except (KeyboardInterrupt, EOFError):
            return cancel("operator")
        except OSError:
            return cancel("console_input_unavailable")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    mark = modes.add_parser("record")
    mark.add_argument("--output", type=Path, required=True)
    mark.add_argument("--samples", type=Path, required=True)
    mark.add_argument("--timeout-seconds", type=float, default=90)
    mark.add_argument("--freshness-ms", type=int, default=3000)
    compare = modes.add_parser("align")
    compare.add_argument("--markers", type=Path, required=True)
    compare.add_argument("--samples", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.mode == "record":
        print(record_gated(args.output, args.samples, timeout_seconds=args.timeout_seconds,
                           freshness_ms=args.freshness_ms))
    else:
        value = align(_read(args.markers), _read(args.samples))
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, allow_nan=False, indent=2)
            stream.write("\n")
        print(value["state"])


if __name__ == "__main__":
    main()
