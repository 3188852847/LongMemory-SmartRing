"""Xiaozhi 控制桥的纯协议校验。

这里只接受协议明确允许的字段和值，不执行网络请求。把不可信桥响应与 HTTP 传输
分离后，新增设备能力时可以单独测试数据契约，避免额外字段泄露到浏览器。
"""

import re
from datetime import datetime


class BridgeError(Exception):
    """只携带固定错误码；上游原文可能含设备数据，不能直接显示。"""

    def __init__(self, code: str, status: int = 503):
        super().__init__(code)
        self.code = code
        self.status = status


REASONS = frozenset({
    "ambiguous_device_connections", "tool_schema_unsupported", "device_rejected",
    "unexpected_device_result", "device_connection_changed", "tool_not_allowed",
    "device_timeout_outcome_unknown", "device_call_failed_outcome_unknown",
    "volume_readback_unavailable", "control_busy", "volume_outside_device_schema",
    "status_readback_unavailable", "value_outside_device_schema",
    "brightness_out_of_range", "theme_invalid",
    "round_skin_invalid", "round_skin_readback_invalid", "round_skin_readback_mismatch",
    "round_wallpaper_stage_invalid", "round_wallpaper_readback_invalid",
    "round_wallpaper_readback_mismatch", "round_wallpaper_delivery_unavailable",
    "round_wallpaper_restart_not_acknowledged",
    "set_not_acknowledged_outcome_unknown",
    "device_offline", "device_not_ready", "tools_not_ready", "readback_mismatch",
    "volume_out_of_range", "tool_unavailable",
    "invalid_announcement", "invalid_expiry", "announcement_expired",
    "tts_not_ready", "device_busy", "announcement_enqueue_failed",
})


def safe_reason(value: object) -> str:
    return value if isinstance(value, str) and value in REASONS else "bridge_error"


def volume_value(value: object) -> bool:
    return type(value) is int and 0 <= value <= 100


VOICE_TIMING_FIELDS = {
    "memory_ready_ms", "llm_requested_ms", "llm_first_output_ms",
    "tts_started_ms", "audio_ready_ms", "first_audio_sent_ms",
    "response_completed_ms",
}


def voice_latency(value: object) -> dict:
    """验证小智内存中的脱敏时序；开放字段不能直接穿透到浏览器。"""

    if not isinstance(value, dict) or value.get("version") not in {1, 2, 3}:
        raise BridgeError("bridge_invalid_response", 502)
    fields = {"version", "state", "started_at", "tts_backend", "timings_ms"}
    if value["version"] in {2, 3}:
        fields.add("tts_segments")
    if value["version"] == 3 and "failure" in value:
        fields.add("failure")
    if set(value) != fields:
        raise BridgeError("bridge_invalid_response", 502)
    if value.get("state") not in {
        "preparing_memory", "waiting_for_model", "waiting_for_sentence",
        "tts_running", "audio_ready", "first_audio_sent", "failed",
    } or value.get("tts_backend") not in {"edge", "voxcpm2", "sanotts", "cosyvoice3", "other"}:
        raise BridgeError("bridge_invalid_response", 502)
    if not isinstance(value.get("started_at"), str) or len(value["started_at"]) > 64:
        raise BridgeError("bridge_invalid_response", 502)
    try:
        started = datetime.fromisoformat(value["started_at"])
    except ValueError:
        raise BridgeError("bridge_invalid_response", 502) from None
    if started.tzinfo is None:
        raise BridgeError("bridge_invalid_response", 502)
    timings = value.get("timings_ms")
    if not isinstance(timings, dict) or set(timings) != VOICE_TIMING_FIELDS:
        raise BridgeError("bridge_invalid_response", 502)
    if any(
        item is not None
        and (type(item) is not int or not 0 <= item <= 3_600_000)
        for item in timings.values()
    ):
        raise BridgeError("bridge_invalid_response", 502)
    result = {**value, "timings_ms": dict(timings)}
    if value["version"] in {2, 3}:
        segments = value.get("tts_segments")
        segment_fields = {"index", "started_ms", "completed_ms", "duration_ms"}
        if not isinstance(segments, list) or len(segments) > 64:
            raise BridgeError("bridge_invalid_response", 502)
        for expected_index, segment in enumerate(segments, start=1):
            if not isinstance(segment, dict) or set(segment) != segment_fields:
                raise BridgeError("bridge_invalid_response", 502)
            if segment.get("index") != expected_index:
                raise BridgeError("bridge_invalid_response", 502)
            if type(segment.get("started_ms")) is not int or not 0 <= segment["started_ms"] <= 3_600_000:
                raise BridgeError("bridge_invalid_response", 502)
            for field in ("completed_ms", "duration_ms"):
                item = segment.get(field)
                if item is not None and (type(item) is not int or not 0 <= item <= 3_600_000):
                    raise BridgeError("bridge_invalid_response", 502)
            if (segment["completed_ms"] is None) != (segment["duration_ms"] is None):
                raise BridgeError("bridge_invalid_response", 502)
            if segment["completed_ms"] is not None and (
                segment["completed_ms"] < segment["started_ms"]
                or segment["duration_ms"] != segment["completed_ms"] - segment["started_ms"]
            ):
                raise BridgeError("bridge_invalid_response", 502)
        result["tts_segments"] = [dict(segment) for segment in segments]
    if value["version"] == 3 and "failure" in value:
        failure = value["failure"]
        if (
            value["state"] != "failed"
            or not isinstance(failure, dict)
            or set(failure) != {"stage", "code", "at_ms"}
            or failure.get("stage") != "model"
            or failure.get("code") not in {
                "model_http_404", "model_http_error", "model_connection_failed",
                "model_timeout", "model_request_failed",
            }
            or type(failure.get("at_ms")) is not int
            or not 0 <= failure["at_ms"] <= 3_600_000
        ):
            raise BridgeError("bridge_invalid_response", 502)
        result["failure"] = dict(failure)
    elif value.get("state") == "failed":
        raise BridgeError("bridge_invalid_response", 502)
    return result


def round_skin(value: object) -> dict:
    """验证圆屏皮肤清单；颜色和尺寸全部使用有限范围。"""

    fields = {
        "skin_api", "skin_id", "manifest_sha256", "background", "foreground",
        "muted", "accent", "listening", "thinking", "happy", "concerned",
        "error", "eye_width", "eye_height", "mouth_width",
    }
    colors = fields - {
        "skin_api", "skin_id", "manifest_sha256",
        "eye_width", "eye_height", "mouth_width",
    }
    if not isinstance(value, dict) or set(value) != fields or value.get("skin_api") != 1:
        raise BridgeError("bridge_invalid_response", 502)
    if (
        not isinstance(value.get("skin_id"), str)
        or re.fullmatch(r"[a-z0-9][a-z0-9-]{2,39}", value["skin_id"]) is None
        or not isinstance(value.get("manifest_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["manifest_sha256"]) is None
        or any(
            type(value.get(key)) is not int or not 0 <= value[key] <= 0xFFFFFF
            for key in colors
        )
    ):
        raise BridgeError("bridge_invalid_response", 502)
    for key, minimum, maximum in (
        ("eye_width", 12, 36),
        ("eye_height", 18, 48),
        ("mouth_width", 20, 64),
    ):
        if type(value.get(key)) is not int or not minimum <= value[key] <= maximum:
            raise BridgeError("bridge_invalid_response", 502)
    return value
