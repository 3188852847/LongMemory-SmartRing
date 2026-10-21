"""可选输入计数的有限投影；失效仅标为unavailable，不阻断原设备状态。"""

LIMIT = 2 ** 31 - 1
KINDS = ("route", "handle", "receive", "formal", "speech", "abort")
COUNTERS = frozenset(("queue_put", "queue_get", "vad_check", "vad_speech", "vad_error",
    "route_no_enqueue", "just_woken_skipped", "stop_flag_receive", "stop_without_formal",
    "endpoint_length_rejected", "result_empty", "result_nonempty", "result_unknown", "observer_error")
    + tuple(kind + suffix for kind in KINDS for suffix in ("_begin", "_return", "_error", "_timeout", "_cancel")))
FIELDS = frozenset(("version", "state", "counts", "inflight", "queue_depth", "current_flags",
    "last_handle_flags", "endpoint_packet_count", "endpoint_pcm_bytes", "buffer_frames_before_receive",
    "formal_audio_frames", "formal_pcm_bytes", "counter_saturated", "value_kind"))
FLAGS = frozenset(("client_aec", "client_is_speaking", "just_woken_up", "client_have_voice", "client_voice_stop", "listen_mode"))
VALUE_KIND = "connection_counters_not_audio_or_cpu_time"


def _integer(value):
    return type(value) is int and 0 <= value <= LIMIT


def _flags(value):
    return (type(value) is dict and set(value) == FLAGS
            and value["listen_mode"] in {"auto", "manual", "realtime", "unknown"}
            and all(value[name] is None or type(value[name]) is bool for name in FLAGS - {"listen_mode"}))


def voice_input_observation(value):
    """接收固定schema，不把PCM端点帧数叫网络包数；无正文/音频透传。"""
    unavailable = dict.fromkeys(FIELDS)
    unavailable.update(version=1, state="unavailable", value_kind=VALUE_KIND)
    try:
        if (type(value) is not dict or set(value) != FIELDS or type(value["version"]) is not int
                or value["version"] != 1 or value["value_kind"] != VALUE_KIND):
            return unavailable
        if value["state"] in {"no_connection", "not_observed", "unavailable"}:
            if any(value[name] is not None for name in FIELDS - {"version", "state", "value_kind"}):
                return unavailable
            return dict(value)
        if value["state"] not in {"observed", "closed"}:
            return unavailable
        if (type(value["counts"]) is not dict or set(value["counts"]) != COUNTERS
                or not all(_integer(n) for n in value["counts"].values())
                or type(value["inflight"]) is not dict or set(value["inflight"]) != set(KINDS)
                or not all(_integer(n) for n in value["inflight"].values())
                or type(value["counter_saturated"]) is not bool or not _flags(value["current_flags"])
                or (value["last_handle_flags"] is not None and not _flags(value["last_handle_flags"]))):
            return unavailable
        for name in ("queue_depth", "endpoint_packet_count", "endpoint_pcm_bytes", "buffer_frames_before_receive",
                     "formal_audio_frames", "formal_pcm_bytes"):
            if value[name] is not None and not _integer(value[name]):
                return unavailable
        return {**value, "counts": dict(value["counts"]), "inflight": dict(value["inflight"]),
                "current_flags": dict(value["current_flags"]),
                "last_handle_flags": None if value["last_handle_flags"] is None else dict(value["last_handle_flags"])}
    except Exception:
        return unavailable
