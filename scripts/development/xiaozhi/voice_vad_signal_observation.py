"""输入声学边界的数值观测；不保留音频、逐帧轨迹、文本或身份。

在所有现有包装和 voice_input_observation 之后安装。只委托原解码、AEC、
VAD 和 ONNX 调用一次；decode_return 可能已包含直连 v2 包装的 AEC。
"""

from array import array
from contextvars import ContextVar
import copy
import math
import secrets
import sys
import threading
import time


STATE = "_longmemory_voice_vad_signal_observation"
LIMIT = 2**31 - 1
PHASES = ("speaking", "not_speaking", "unknown")
STAGES = ("decode_return", "aec_input", "aec_output", "vad_input")
ENERGY_EDGES = (-90, -70, -50, -35, -20, -6)
PROBABILITY_EDGES = (.01, .1, .2, .5, .8, .95)
PAIR_RMS_FLOOR = 500
PAIR_RATIO_EDGES = (.1, .25, .5, .9, 1.1)
EXPORTED_COUNTS = ("decode_return", "aec_input", "aec_output", "vad_input", "vad_true", "vad_false",
                   "vad_none", "vad_other", "vad_raised", "inference_return", "inference_error",
                   "inference_contract_other", "inference_observation_error", "probability_invalid",
                   "probability_ge_high", "probability_le_low", "session_not_supported",
                   "decode_return_error", "aec_output_error", "aec_timestamp_nonzero_yes",
                   "aec_reference_present_yes")
_ACTIVE = ContextVar("voice_vad_signal_active", default=None)
_INSTALL_LOCK = threading.RLock()


def _phase(connection):
    value = getattr(connection, "client_is_speaking", None)
    return "speaking" if value is True else "not_speaking" if value is False else "unknown"


def _group():
    return {"counts": {}, "energy": {}, "probability": None}


def _increment(mapping, name):
    mapping[name] = min(LIMIT, mapping.get(name, 0) + 1)


def _bin(value, edges):
    return sum(value >= edge for edge in edges)


def _energy(pcm):
    if not isinstance(pcm, (bytes, bytearray)) or not pcm or len(pcm) % 2:
        return None
    samples = array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    return {"rms_pcm16": round(rms, 3), "dbfs": round(max(-120., 20 * math.log10(max(rms, .000001) / 32768)), 3),
            "peak_pcm16": max(abs(value) for value in samples),
            "zero_fraction": round(samples.count(0) / len(samples), 5),
            "clipped_fraction": round(sum(value in (-32768, 32767) for value in samples) / len(samples), 5)}


class _State:
    def __init__(self):
        self.lock = threading.RLock()
        self.groups = {phase: _group() for phase in PHASES}
        self.recent = []  # 最多三秒的合并桶，绝不保存逐帧数值。
        self.contract = None
        self.aec_reference = None
        self.window_positive_count = None
        self.failed = False
        self.pairs = None
        self.pairs_failed = False
        self.observation_id = secrets.token_hex(8)

    def record(self, phase, event, *, energy=None, probability=None):
        with self.lock:
            second = int(time.monotonic())
            self.recent = [item for item in self.recent if second - item[0] < 3]
            if not self.recent or self.recent[-1][0] != second:
                self.recent.append((second, {name: _group() for name in PHASES}))
                self.recent = self.recent[-3:]
            for group in (self.groups[phase], self.recent[-1][1][phase]):
                _increment(group["counts"], event)
                if energy is not None:
                    value = group["energy"].setdefault(event, {
                        "dbfs_bins": [0] * 7, "max_rms_pcm16": 0., "max_peak_pcm16": 0, "last": None})
                    index = _bin(energy["dbfs"], ENERGY_EDGES)
                    value["dbfs_bins"][index] = min(LIMIT, value["dbfs_bins"][index] + 1)
                    value["max_rms_pcm16"] = max(value["max_rms_pcm16"], energy["rms_pcm16"])
                    value["max_peak_pcm16"] = max(value["max_peak_pcm16"], energy["peak_pcm16"])
                    value["last"] = energy
                if probability is not None:
                    value = group["probability"]
                    if value is None:
                        value = group["probability"] = {"bins": [0] * 7, "min": probability, "max": probability}
                    index = _bin(probability, PROBABILITY_EDGES)
                    value["bins"][index] = min(LIMIT, value["bins"][index] + 1)
                    value["min"] = min(value["min"], probability)
                    value["max"] = max(value["max"], probability)


def _state(connection):
    with _INSTALL_LOCK:
        value = getattr(connection, STATE, None)
        if value is None:
            value = _State()
            setattr(connection, STATE, value)
    return value if isinstance(value, _State) else None


def _safe(action):
    try:
        return action()
    except Exception:
        return None


def _note(state, phase, event, **values):
    if state is not None:
        try:
            state.record(phase, event, **values)
        except Exception:
            state.failed = True


def _number(value, lower, upper):
    return float(value) if type(value) in (int, float) and math.isfinite(value) and lower <= value <= upper else None


def _measure(pcm):
    try:
        return _energy(pcm), False
    except Exception:
        return None, True


def _pair_counts():
    return {"valid": 0, "invalid": 0, "zero_input": 0, "below_floor": 0, "original_error": 0,
            "observer_error": 0, "ratio_bins": [0] * 6}


def _pair(state, before, after, *, same_size=True, raised=False):
    """局部值只来自同一次调用；完成后锁内一次提交，不保留帧或逐调用记录。"""
    if state is None:
        return
    try:
        input_energy, input_failed = before
        output_energy, output_failed = after
        event, subset, index = "valid", None, None
        if raised:
            event = "original_error"
        elif input_failed or output_failed:
            event = "observer_error"
        elif input_energy is None or output_energy is None or not same_size:
            event = "invalid"
        else:
            input_rms, output_rms = input_energy["rms_pcm16"], output_energy["rms_pcm16"]
            if input_rms == 0:
                subset = "zero_input"
            elif input_rms < PAIR_RMS_FLOOR:
                subset = "below_floor"
            else:
                index = _bin(output_rms / input_rms, PAIR_RATIO_EDGES)
        with state.lock:
            second = int(time.monotonic())
            if state.pairs is None:
                state.pairs = {"total": _pair_counts(), "buckets": []}
            pairs = state.pairs
            pairs["buckets"] = [item for item in pairs["buckets"] if second - item[0] < 3]
            if not pairs["buckets"] or pairs["buckets"][-1][0] != second:
                pairs["buckets"].append((second, _pair_counts()))
                pairs["buckets"] = pairs["buckets"][-3:]
            for counts in (pairs["total"], pairs["buckets"][-1][1]):
                _increment(counts, event)
                if subset is not None:
                    _increment(counts, subset)
                if index is not None:
                    counts["ratio_bins"][index] = min(LIMIT, counts["ratio_bins"][index] + 1)
    except Exception:
        # 新旁路失败只使新字段未知；旧字段及音频调用仍保持原行为。
        state.pairs_failed = True


def _pair_snapshot(state):
    if state.pairs is None or state.pairs_failed:
        return None
    recent = _pair_counts()
    second = int(time.monotonic())
    for at, counts in state.pairs["buckets"]:
        if second - at >= 3:
            continue
        for key in recent:
            if key == "ratio_bins":
                recent[key] = [min(LIMIT, a + b) for a, b in zip(recent[key], counts[key])]
            else:
                recent[key] = min(LIMIT, recent[key] + counts[key])
    return {"rms_floor_pcm16": PAIR_RMS_FLOOR, "ratio_edges": PAIR_RATIO_EDGES,
            "total": state.pairs["total"], "recent": recent}


def _clock_ms():
    try:
        value = time.monotonic_ns() // 1_000_000
        return value if type(value) is int and 0 <= value <= 2**63 - 1 else None
    except Exception:
        return None


class _Session:
    def __init__(self, original):
        self.original = original

    def __getattr__(self, name):
        return getattr(self.original, name)

    def run(self, *args, **kwargs):
        active = _ACTIVE.get()
        if active is None:
            return self.original.run(*args, **kwargs)
        state, phase, provider = active
        _note(state, phase, "inference_begin")
        try:
            result = self.original.run(*args, **kwargs)
        except BaseException:
            _note(state, phase, "inference_error")
            raise
        _note(state, phase, "inference_return")
        def observe():
            feed = args[1] if len(args) > 1 else kwargs.get("input_feed", {})
            valid = (tuple(feed["input"].shape) == (1, 576)
                     and tuple(feed["state"].shape) == (2, 1, 128) and feed["sr"].item() == 16000)
            _note(state, phase, "inference_contract_valid" if valid else "inference_contract_other")
            probability = float(result[0].item())
            if not math.isfinite(probability) or not 0 <= probability <= 1:
                _note(state, phase, "probability_invalid")
                return
            _note(state, phase, "probability_observed", probability=probability)
            high = _number(getattr(provider, "vad_threshold", None), 0, 1)
            low = _number(getattr(provider, "vad_threshold_low", None), 0, 1)
            if high is not None and probability >= high:
                _note(state, phase, "probability_ge_high")
            if low is not None and probability <= low:
                _note(state, phase, "probability_le_low")
        try:
            observe()
        except Exception:
            _note(state, phase, "inference_observation_error")
        return result


def _prepare(state, phase, provider):
    with _INSTALL_LOCK:
        session = getattr(provider, "session", None)
        supported = (callable(getattr(session, "run", None))
                     and hasattr(provider, "vad_threshold") and hasattr(provider, "vad_threshold_low"))
        if supported and not isinstance(session, _Session):
            provider.session = _Session(session)
        state.contract = {
            "session_observed": supported,
            "threshold": _number(getattr(provider, "vad_threshold", None), 0, 1),
            "threshold_low": _number(getattr(provider, "vad_threshold_low", None), 0, 1),
            "silence_threshold_ms": _number(getattr(provider, "silence_threshold_ms", None), 0, 60000),
            "frame_window_threshold": _number(getattr(provider, "frame_window_threshold", None), 0, 100),
            "runtime_model_hash": None,
        }
    if not supported:
        _note(state, phase, "session_not_supported")


def _reference(connection, timestamp):
    keys = getattr(connection, "aec_audio_cache", {})
    valid = type(timestamp) is int and 0 <= timestamp < 2**32
    distances = [abs((timestamp - key + 2**31) % 2**32 - 2**31)
                 for key in keys if valid and type(key) is int and 0 <= key < 2**32]
    return {"timestamp_nonzero": valid and timestamp > 0, "reference_present": bool(distances),
            "nearest_reference_abs_delta_ms": min(distances) if distances else None,
            "reference_count": min(LIMIT, len(keys))}


def install_voice_vad_signal_observation(connection_class, *, input_observation_module=None):
    """在最终包装后安装；已有连接亦可观测，不另开工作线程或推理。"""
    if connection_class.__dict__.get("_longmemory_vad_signal_installed", False):
        return {"installed": True, "already_installed": True}
    if input_observation_module is None:
        import voice_input_observation as input_observation_module
    if not getattr(connection_class, "_longmemory_input_observation_installed", False):
        raise ValueError("install_voice_input_observation_first")
    observed = input_observation_module._ObservedVAD
    previous_vad = observed.is_vad

    def vad(proxy, connection, frame):
        if not isinstance(connection, connection_class):
            return previous_vad(proxy, connection, frame)
        state, phase = _safe(lambda: _state(connection)), _phase(connection)
        _note(state, phase, "vad_input", energy=_safe(lambda: _energy(frame)))
        if state is not None:
            _safe(lambda: _prepare(state, phase, proxy.original))
        token = _ACTIVE.set((state, phase, proxy.original) if state is not None else None)
        try:
            result = previous_vad(proxy, connection, frame)
        except BaseException:
            _note(state, phase, "vad_raised")
            raise
        finally:
            _ACTIVE.reset(token)
        _note(state, phase, "vad_true" if result is True else "vad_false" if result is False else
              "vad_none" if result is None else "vad_other")
        def window():
            values = getattr(connection, "client_voice_window", ())
            state.window_positive_count = min(100, sum(value is True for value in values))
        if state is not None:
            _safe(window)
        return result

    observed.is_vad = vad
    for name, stage in (("_decode_opus_packet", "decode_return"), ("_apply_aec", "aec_output")):
        original = getattr(connection_class, name)
        def wrap(original, stage):
            def call(connection, *args, **kwargs):
                state, phase = _safe(lambda: _state(connection)), _phase(connection)
                before = (None, False)
                if stage == "aec_output":
                    timestamp = args[0] if args else kwargs.get("timestamp")
                    pcm = args[1] if len(args) > 1 else kwargs.get("pcm_frame")
                    before = _measure(pcm)
                    _note(state, phase, "aec_input", energy=before[0])
                    if state is not None:
                        reference = _safe(lambda: _reference(connection, timestamp))
                        with state.lock:
                            state.aec_reference = reference
                        if reference is not None:
                            for key in ("timestamp_nonzero", "reference_present"):
                                _note(state, phase, "aec_" + key + ("_yes" if reference[key] else "_no"))
                try:
                    result = original(connection, *args, **kwargs)
                except BaseException:
                    _note(state, phase, stage + "_error")
                    if stage == "aec_output":
                        _pair(state, before, (None, False), raised=True)
                    raise
                after = _measure(result)
                _note(state, phase, stage, energy=after[0])
                if stage == "aec_output":
                    same_size = (isinstance(pcm, (bytes, bytearray)) and isinstance(result, (bytes, bytearray))
                                 and len(pcm) == len(result))
                    _pair(state, before, after, same_size=same_size)
                return result
            return call
        setattr(connection_class, name, wrap(original, stage))
    connection_class._longmemory_vad_signal_installed = True
    connection_class._longmemory_voice_vad_signal_snapshot = staticmethod(voice_vad_signal_snapshot)
    return {"installed": True, "already_installed": False}


def _recent_summary(buckets):
    result = {phase: _group() for phase in PHASES}
    for bucket in buckets:
        for phase, source in bucket.items():
            target = result[phase]
            for name, count in source["counts"].items():
                target["counts"][name] = min(LIMIT, target["counts"].get(name, 0) + count)
            for stage, energy in source["energy"].items():
                value = target["energy"].setdefault(stage, {"max_rms_pcm16": 0., "max_peak_pcm16": 0})
                for name in value:
                    value[name] = max(value[name], energy[name])
            probability = source["probability"]
            if probability is not None:
                value = target["probability"]
                if value is None:
                    target["probability"] = dict(probability, bins=list(probability["bins"]))
                else:
                    value["min"], value["max"] = min(value["min"], probability["min"]), max(value["max"], probability["max"])
                    value["bins"] = [min(LIMIT, a + b) for a, b in zip(value["bins"], probability["bins"])]
    return result


def _project_group(group, *, recent=False):
    # 设备响应整体有 16 KiB 上限：计数按公开固定顺序输出，避免重复长键。
    # None 表示该阶段/事件尚未被观察，不能当作零能量或模型返回 False。
    energy = {}
    for stage, value in group["energy"].items():
        energy[stage] = {"max_rms_pcm16": value["max_rms_pcm16"]}
        if not recent:
            energy[stage]["last_rms_pcm16"] = value["last"]["rms_pcm16"]
            energy[stage]["max_peak_pcm16"] = value["max_peak_pcm16"]
    probability = group["probability"]
    if recent and probability is not None:
        probability = {"min": probability["min"], "max": probability["max"],
                       "count": min(LIMIT, sum(probability["bins"]))}
    return {"counts": [group["counts"].get(key) for key in EXPORTED_COUNTS],
            "energy": energy, "probability": probability}


def voice_vad_signal_snapshot(connection, *, include_aec_pairs=False):
    """未观测值为 null；近期桶最多包含当前秒和前两秒，无逐帧轨迹。"""
    missing = {"version": 2 if include_aec_pairs else 1, "state": "no_connection" if connection is None else "not_observed",
               "groups": None, "recent_groups": None, "contract": None, "aec_reference": None,
               "window_positive_count": None, "count_keys": EXPORTED_COUNTS,
               "probability_bin_edges": PROBABILITY_EDGES,
               "value_kind": "bounded_numeric_signal_summary_not_speech_or_waveform"}
    if include_aec_pairs:
        missing["aec_pairs"] = None
        missing["clock_ms"] = _clock_ms()
        missing["observation_id"] = None
    try:
        state = getattr(connection, STATE, None)
        if state is None:
            return missing
        if not isinstance(state, _State) or state.failed:
            return dict(missing, state="unavailable")
        with state.lock:
            recent = [groups for second, groups in state.recent if int(time.monotonic()) - second < 3]
            recent_groups = _recent_summary(recent)
            value = {"version": 2 if include_aec_pairs else 1, "state": "observed",
                "groups": {phase: _project_group(group) for phase, group in state.groups.items()},
                "recent_groups": {phase: _project_group(group, recent=True) for phase, group in recent_groups.items()},
                "count_keys": EXPORTED_COUNTS, "contract": state.contract, "aec_reference": state.aec_reference,
                "window_positive_count": state.window_positive_count,
                "probability_bin_edges": PROBABILITY_EDGES,
                "value_kind": "bounded_numeric_signal_summary_not_speech_or_waveform"}
            if include_aec_pairs:
                value["aec_pairs"] = _safe(lambda: _pair_snapshot(state))
                value["clock_ms"] = _clock_ms()
                value["observation_id"] = state.observation_id
            return copy.deepcopy(value)
    except Exception:
        return dict(missing, state="unavailable")
