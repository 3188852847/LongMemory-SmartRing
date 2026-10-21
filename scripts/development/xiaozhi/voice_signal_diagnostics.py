"""独立只读端点的固定数值投影；不创建观测、不读模型/音频或身份。"""

import json
import math

LIMIT = 2**31 - 1
MAX_BYTES = 6000
PHASES = {"speaking", "not_speaking", "unknown"}
STAGES = {"decode_return", "aec_input", "aec_output", "vad_input"}
COUNT_KEYS = ("decode_return", "aec_input", "aec_output", "vad_input", "vad_true", "vad_false",
              "vad_none", "vad_other", "vad_raised", "inference_return", "inference_error",
              "inference_contract_other", "inference_observation_error", "probability_invalid",
              "probability_ge_high", "probability_le_low", "session_not_supported",
              "decode_return_error", "aec_output_error", "aec_timestamp_nonzero_yes",
              "aec_reference_present_yes")
EDGES = (.01, .1, .2, .5, .8, .95)
VALUE_KIND = "bounded_numeric_signal_summary_not_speech_or_waveform"
FIELDS = {"version", "state", "groups", "recent_groups", "contract", "aec_reference",
          "window_positive_count", "count_keys", "probability_bin_edges", "value_kind"}


def missing(state):
    return dict(version=1, state=state, groups=None, recent_groups=None, contract=None,
                aec_reference=None, window_positive_count=None, count_keys=list(COUNT_KEYS),
                probability_bin_edges=list(EDGES), value_kind=VALUE_KIND)


def _number(value, maximum, minimum=0):
    return type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum


def _count(value):
    return type(value) is int and 0 <= value <= LIMIT


def _group(value, recent=False):
    if type(value) is not dict or set(value) != {"counts", "energy", "probability"}:
        return False
    counts, energy, probability = value["counts"], value["energy"], value["probability"]
    if (type(counts) is not list or len(counts) != len(COUNT_KEYS)
            or any(n is not None and not _count(n) for n in counts)
            or type(energy) is not dict or set(energy) - STAGES):
        return False
    for item in energy.values():
        fields = {"max_rms_pcm16"} if recent else {"max_rms_pcm16", "last_rms_pcm16", "max_peak_pcm16"}
        if type(item) is not dict or set(item) != fields or not _number(item["max_rms_pcm16"], 32768):
            return False
        if not recent and (not _number(item["last_rms_pcm16"], 32768)
                           or type(item["max_peak_pcm16"]) is not int or not 0 <= item["max_peak_pcm16"] <= 32768):
            return False
    if probability is not None:
        fields = {"min", "max", "count" if recent else "bins"}
        if (type(probability) is not dict or set(probability) != fields
                or not _number(probability["min"], 1) or not _number(probability["max"], 1)
                or probability["min"] > probability["max"]):
            return False
        if recent:
            if not _count(probability["count"]):
                return False
        elif (type(probability["bins"]) is not list or len(probability["bins"]) != 7
              or not all(_count(n) for n in probability["bins"])):
            return False
    return True


def project(value):
    """坏旁路只返回unavailable；不透传未知键或任意异常字符串。"""
    unavailable = missing("unavailable")
    try:
        if (type(value) is not dict or set(value) != FIELDS
                or type(value["version"]) is not int or value["version"] != 1
                or value["value_kind"] != VALUE_KIND
                or type(value["count_keys"]) not in (tuple, list) or tuple(value["count_keys"]) != COUNT_KEYS
                or type(value["probability_bin_edges"]) not in (tuple, list)
                or tuple(value["probability_bin_edges"]) != EDGES):
            return unavailable
        if value["state"] in ("no_connection", "not_observed", "unavailable"):
            return missing(value["state"]) if all(value[k] is None for k in (
                "groups", "recent_groups", "contract", "aec_reference", "window_positive_count")) else unavailable
        if value["state"] != "observed":
            return unavailable
        for key in ("groups", "recent_groups"):
            groups = value[key]
            if type(groups) is not dict or set(groups) != PHASES or not all(
                    _group(group, recent=key == "recent_groups") for group in groups.values()):
                return unavailable
        contract = value["contract"]
        if contract is not None:
            if (type(contract) is not dict or set(contract) != {"session_observed", "threshold", "threshold_low",
                    "silence_threshold_ms", "frame_window_threshold", "runtime_model_hash"}
                    or type(contract["session_observed"]) is not bool or contract["runtime_model_hash"] is not None):
                return unavailable
            for name, maximum in (("threshold", 1), ("threshold_low", 1),
                                  ("silence_threshold_ms", 60000), ("frame_window_threshold", 100)):
                if contract[name] is not None and not _number(contract[name], maximum):
                    return unavailable
        reference = value["aec_reference"]
        if reference is not None:
            if (type(reference) is not dict or set(reference) != {"timestamp_nonzero", "reference_present",
                    "nearest_reference_abs_delta_ms", "reference_count"}
                    or any(type(reference[k]) is not bool for k in ("timestamp_nonzero", "reference_present"))
                    or not _count(reference["reference_count"])):
                return unavailable
            delta = reference["nearest_reference_abs_delta_ms"]
            if ((delta is not None and (type(delta) is not int or not 0 <= delta <= 2**31))
                    or reference["reference_present"] != (delta is not None)):
                return unavailable
        window = value["window_positive_count"]
        if window is not None and (type(window) is not int or not 0 <= window <= 100):
            return unavailable
        # 输出自身有独立预算，绝不挤占/api/device的既有16 KiB契约。
        encoded = json.dumps(value, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_BYTES:
            return unavailable
        return json.loads(encoded)
    except Exception:
        return unavailable


def snapshot(connection=None):
    fallback = missing("no_connection" if connection is None else "not_observed")
    try:
        from voice_vad_signal_observation import voice_vad_signal_snapshot
        result = project(voice_vad_signal_snapshot(connection))
        if connection is None and result["state"] != "no_connection":
            return fallback
        return result
    except ImportError:
        return fallback
    except Exception:
        return missing("unavailable") if connection is not None else fallback
