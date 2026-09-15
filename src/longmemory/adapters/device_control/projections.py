"""把不可信设备桥响应投影为控制台允许读取的字段。"""

import re

from .protocol import (
    BridgeError,
    round_skin,
    safe_reason,
    voice_asr_prefetch,
    voice_latency,
    voice_prediction_shadow,
    volume_value,
)


def read_volume(data: dict) -> dict:
    if not volume_value(data.get("volume")):
        raise BridgeError("bridge_invalid_response", 502)
    return {"volume": data["volume"]}


def volume_update(data: dict, requested_volume: int) -> dict:
    if (
        type(data.get("requested_volume")) is not int
        or data["requested_volume"] != requested_volume
        or data.get("acknowledged") is not True
        or type(data.get("verified")) is not bool
        or not volume_value(data.get("previous_volume"))
        or (
            data.get("readback_volume") is not None
            and not volume_value(data["readback_volume"])
        )
    ):
        raise BridgeError("bridge_invalid_response", 502)
    if data["verified"] and data.get("readback_volume") != requested_volume:
        raise BridgeError("bridge_invalid_response", 502)
    result = {
        key: data.get(key)
        for key in (
            "requested_volume", "previous_volume", "acknowledged",
            "readback_volume", "verified",
        )
    }
    if "reason" in data:
        result["reason"] = safe_reason(data["reason"])
    return result


def speech_stop(data: dict) -> dict:
    operation_id = data.get("operation_id")
    state = data.get("state")
    if (
        not isinstance(operation_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", operation_id) is None
        or state not in {"stop_sent", "already_idle"}
        or type(data.get("server_interrupted")) is not bool
        or data.get("device_acknowledgement")
        not in {"unavailable", "not_requested"}
    ):
        raise BridgeError("bridge_invalid_response", 502)
    if (
        state == "stop_sent"
        and (
            data["server_interrupted"] is not True
            or data["device_acknowledgement"] != "unavailable"
        )
    ) or (
        state == "already_idle"
        and (
            data["server_interrupted"] is not False
            or data["device_acknowledgement"] != "not_requested"
        )
    ):
        raise BridgeError("bridge_invalid_response", 502)
    return {
        "operation_id": operation_id,
        "state": state,
        "server_interrupted": data["server_interrupted"],
        "device_acknowledgement": data["device_acknowledgement"],
    }


def screen_update(data: dict, requested_value: object) -> dict:
    if (
        data.get("requested_value") != requested_value
        or data.get("acknowledged") is not True
        or type(data.get("verified")) is not bool
    ):
        raise BridgeError("bridge_invalid_response", 502)
    if data["verified"] and data.get("readback_value") != requested_value:
        raise BridgeError("bridge_invalid_response", 502)
    result = {
        key: data.get(key)
        for key in (
            "requested_value", "previous_value", "acknowledged",
            "readback_value", "verified",
        )
    }
    if "reason" in data:
        result["reason"] = safe_reason(data["reason"])
    return result


def round_skin_update(data: dict, requested: dict) -> dict:
    if (
        data.get("requested_skin_id") != requested["skin_id"]
        or data.get("requested_manifest_sha256") != requested["manifest_sha256"]
        or data.get("acknowledged") is not True
        or type(data.get("verified")) is not bool
    ):
        raise BridgeError("bridge_invalid_response", 502)
    result = {
        "requested_skin_id": data["requested_skin_id"],
        "requested_manifest_sha256": data["requested_manifest_sha256"],
        "acknowledged": True,
        "verified": data["verified"],
    }
    if "device_skin" in data:
        result["device_skin"] = round_skin(data["device_skin"])
    if result["verified"] and result.get("device_skin") != requested:
        raise BridgeError("bridge_invalid_response", 502)
    if "reason" in data:
        result["reason"] = safe_reason(data["reason"])
    return result


def staged_wallpaper(
    data: dict, *, item_id: str, sha256: str, size_bytes: int,
) -> dict:
    fields = {
        "wallpaper_api", "slot", "wallpaper_id", "sha256", "size_bytes",
        "state", "operation_id",
    }
    if (
        set(data) != fields
        or data.get("wallpaper_api") != 1
        or data.get("slot") not in {"a", "b"}
        or data.get("wallpaper_id") != item_id
        or data.get("sha256") != sha256
        or data.get("size_bytes") != size_bytes
        or data.get("state") != "staged_verified"
        or not re.fullmatch(r"[0-9a-f]{32}", str(data.get("operation_id", "")))
    ):
        raise BridgeError("bridge_invalid_response", 502)
    return data


def wallpaper_status(data: dict) -> dict:
    fields = {
        "wallpaper_api", "active_valid", "active_slot", "active_wallpaper_id",
        "active_sha256", "active_size_bytes", "rollback_available",
    }
    if (
        not isinstance(data, dict)
        or set(data) != fields
        or data.get("wallpaper_api") != 1
    ):
        raise BridgeError("bridge_invalid_response", 502)
    if (
        type(data.get("active_valid")) is not bool
        or type(data.get("rollback_available")) is not bool
    ):
        raise BridgeError("bridge_invalid_response", 502)
    if data["active_valid"]:
        valid = (
            data.get("active_slot") in {"a", "b"}
            and re.fullmatch(
                r"wallpaper-[0-9a-f]{20}",
                str(data.get("active_wallpaper_id", "")),
            )
            and re.fullmatch(
                r"[0-9a-f]{64}", str(data.get("active_sha256", "")),
            )
            and type(data.get("active_size_bytes")) is int
            and 0 < data["active_size_bytes"] <= 4 * 1024 * 1024
        )
    else:
        valid = (
            data.get("active_slot") == ""
            and data.get("active_wallpaper_id") == ""
            and data.get("active_sha256") == ""
            and data.get("active_size_bytes") == 0
        )
    if not valid:
        raise BridgeError("bridge_invalid_response", 502)
    return data


def activated_wallpaper(data: dict, staged: dict) -> dict:
    expected = {**staged, "state": "activated_restarting"}
    operation_id = data.get("operation_id")
    projected = {
        key: value for key, value in data.items() if key != "operation_id"
    }
    if (
        projected != expected
        or not re.fullmatch(r"[0-9a-f]{32}", str(operation_id or ""))
    ):
        raise BridgeError("bridge_invalid_response", 502)
    return {**projected, "operation_id": operation_id}


def rolled_back_wallpaper(data: dict) -> dict:
    fields = {
        "wallpaper_api", "slot", "wallpaper_id", "sha256", "size_bytes",
        "state", "operation_id",
    }
    if (
        set(data) != fields
        or data.get("wallpaper_api") != 1
        or data.get("slot") not in {"a", "b"}
        or data.get("state") != "rollback_restarting"
        or not re.fullmatch(
            r"wallpaper-[0-9a-f]{20}", str(data.get("wallpaper_id", "")),
        )
        or not re.fullmatch(r"[0-9a-f]{64}", str(data.get("sha256", "")))
        or type(data.get("size_bytes")) is not int
        or not 0 < data["size_bytes"] <= 4 * 1024 * 1024
        or not re.fullmatch(r"[0-9a-f]{32}", str(data.get("operation_id", "")))
    ):
        raise BridgeError("bridge_invalid_response", 502)
    return data


def deactivated_wallpaper(data: dict) -> dict:
    """验证“保留槽位但切回几何皮肤”的重启前回执。"""

    fields = {
        "wallpaper_api", "slot", "wallpaper_id", "sha256", "size_bytes",
        "state", "operation_id",
    }
    if (
        set(data) != fields
        or data.get("wallpaper_api") != 1
        or data.get("slot") not in {"a", "b"}
        or data.get("state") != "skin_mode_restarting"
        or not re.fullmatch(
            r"wallpaper-[0-9a-f]{20}", str(data.get("wallpaper_id", "")),
        )
        or not re.fullmatch(r"[0-9a-f]{64}", str(data.get("sha256", "")))
        or type(data.get("size_bytes")) is not int
        or not 0 < data["size_bytes"] <= 4 * 1024 * 1024
        or not re.fullmatch(r"[0-9a-f]{32}", str(data.get("operation_id", "")))
    ):
        raise BridgeError("bridge_invalid_response", 502)
    return data


def announcement_queued(data: dict, expires_at_ms: int) -> dict:
    operation_id = data.get("operation_id")
    if (
        not isinstance(operation_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", operation_id) is None
        or data.get("state") != "queued"
        or data.get("playback_acknowledgement") != "unavailable"
        or data.get("expires_at_ms") != expires_at_ms
    ):
        raise BridgeError("bridge_invalid_response", 502)
    # 只保留编排需要的非敏感字段；上游额外数据不向应用层扩散。
    return {
        "operation_id": operation_id,
        "state": "queued",
        "playback_acknowledgement": "unavailable",
        "expires_at_ms": expires_at_ms,
    }


def device_status(data: dict) -> dict:
    """投影连接及能力状态，丢弃桥内部或未来未知字段。"""

    count = data.get("connection_count")
    required_flags = (
        "ready", "read_volume_supported", "set_volume_supported",
        "announcement_supported", "announcement_ready", "user_session_active",
    )
    optional_flags = (
        "read_status_supported", "set_brightness_supported",
        "set_theme_supported", "aec_advertised", "stop_speech_supported",
    )
    if (
        type(count) is not int
        or count < 0
        or any(type(data.get(key)) is not bool for key in required_flags)
    ):
        raise BridgeError("bridge_invalid_response", 502)
    if any(
        key in data and type(data[key]) is not bool
        for key in optional_flags
    ):
        raise BridgeError("bridge_invalid_response", 502)
    if data["ready"] and count != 1:
        raise BridgeError("bridge_invalid_response", 502)
    result = {
        "connection_count": count,
        **{key: data[key] for key in required_flags},
        **{key: data.get(key, False) for key in optional_flags},
    }
    result["allowed_volume"] = {"minimum": 5, "maximum": 60}
    if "natural_interruption" in data:
        diagnostic = data["natural_interruption"]
        fields = {
            "version", "state", "device_aec_advertised", "server_aec_active",
            "timestamped_audio_supported", "listen_mode", "reason",
        }
        reasons = {
            "device_offline", "device_aec_not_advertised",
            "timestamp_transport_unavailable", "server_aec_inactive",
            "realtime_listening_inactive", "ready_for_controlled_trial",
        }
        reason_value = (
            diagnostic.get("reason") if isinstance(diagnostic, dict) else None
        )
        expected_state = (
            "unavailable" if reason_value == "device_offline"
            else "trial_ready" if reason_value == "ready_for_controlled_trial"
            else "blocked"
        )
        if (
            not isinstance(diagnostic, dict)
            or set(diagnostic) != fields
            or diagnostic.get("version") != 1
            or diagnostic.get("state")
            not in {"unavailable", "blocked", "trial_ready"}
            or any(
                type(diagnostic.get(key)) is not bool
                for key in (
                    "device_aec_advertised", "server_aec_active",
                    "timestamped_audio_supported",
                )
            )
            or diagnostic.get("listen_mode")
            not in {"auto", "manual", "realtime", "unknown"}
            or diagnostic.get("reason") not in reasons
            or diagnostic.get("state") != expected_state
        ):
            raise BridgeError("bridge_invalid_response", 502)
        result["natural_interruption"] = diagnostic
    if "voice_latency" in data:
        result["voice_latency"] = voice_latency(data["voice_latency"])
    if "voice_prediction_shadow" in data:
        result["voice_prediction_shadow"] = voice_prediction_shadow(
            data["voice_prediction_shadow"]
        )
    if "voice_asr_prefetch" in data:
        result["voice_asr_prefetch"] = voice_asr_prefetch(data["voice_asr_prefetch"])
    if "voice_latency_mode" in data:
        mode = data["voice_latency_mode"]
        if type(mode) is not str or mode not in {"realtime", "original"}:
            raise BridgeError("bridge_invalid_response", 502)
        result["voice_latency_mode"] = mode
    if "reason" in data:
        result["reason"] = safe_reason(data["reason"])
    if "announcement_reason" in data:
        result["announcement_reason"] = safe_reason(data["announcement_reason"])
    return result


def hardware_status(data: dict) -> dict:
    """校验设备读数；缺失代表设备不支持，未知字段一律拒绝。"""

    allowed = {"volume", "brightness", "theme", "battery", "network", "chip"}
    if not data or set(data) - allowed:
        raise BridgeError("bridge_invalid_response", 502)
    if "volume" in data and not volume_value(data["volume"]):
        raise BridgeError("bridge_invalid_response", 502)
    if "brightness" in data and not volume_value(data["brightness"]):
        raise BridgeError("bridge_invalid_response", 502)
    if "theme" in data and data["theme"] not in {"light", "dark"}:
        raise BridgeError("bridge_invalid_response", 502)
    battery = data.get("battery")
    if (
        battery is not None
        and (
            not isinstance(battery, dict)
            or set(battery) != {"level", "charging"}
            or not volume_value(battery.get("level"))
            or type(battery.get("charging")) is not bool
        )
    ):
        raise BridgeError("bridge_invalid_response", 502)
    network = data.get("network")
    if (
        network is not None
        and (
            not isinstance(network, dict)
            or set(network) != {"signal"}
            or network.get("signal") not in {"strong", "medium", "weak"}
        )
    ):
        raise BridgeError("bridge_invalid_response", 502)
    chip = data.get("chip")
    if (
        chip is not None
        and (
            not isinstance(chip, dict)
            or set(chip) != {"temperature"}
            or type(chip.get("temperature")) not in {int, float}
            or not -40 <= chip["temperature"] <= 125
        )
    ):
        raise BridgeError("bridge_invalid_response", 502)
    return data
