import asyncio
import json
from datetime import datetime, timezone

import pytest

pytest.importorskip("aiohttp", reason="网页适配层测试需要 console extra")
from longmemory.adapters.device_control.xiaozhi import XiaozhiControlClient, BridgeError


class Response:
    def __init__(self, value, status=200):
        self.raw = json.dumps(value).encode()
        self.status = status
        self.content = self

    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    async def iter_chunked(self, size):
        # 模拟拆包，客户端不能只读第一段就解析 JSON。
        for offset in range(0, len(self.raw), 7):
            yield self.raw[offset:offset + 7]


class Session:
    def __init__(self, response): self.response, self.calls = response, []
    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response
    async def close(self): pass


def client_for(tmp_path, value, status=200):
    token = tmp_path / "synthetic-token"
    token.write_text("a" * 64)
    client = XiaozhiControlClient(token)
    client._session = Session(Response(value, status))
    return client


def round_skin():
    return {
        "skin_api": 1, "skin_id": "rose-night-v1", "manifest_sha256": "a" * 64,
        "background": 0x171B26, "foreground": 0xF7F4F8, "muted": 0xCBD1DC,
        "accent": 0xDF72A8, "listening": 0x69D5FF, "thinking": 0xF7C65A,
        "happy": 0x7DE2B8, "concerned": 0x8AA8FF, "error": 0xF16C73,
        "eye_width": 22, "eye_height": 36, "mouth_width": 38,
    }


def test_token_is_backend_only_and_volume_is_projected(tmp_path):
    client = client_for(tmp_path, {"volume": 25, "wifi_password": "synthetic-secret", "message": "<script>alert(1)</script>"})
    assert asyncio.run(client.read_volume()) == {"volume": 25}
    args, options = client._session.calls[0]
    assert args == ("GET", "http://127.0.0.1:8766/api/device/volume")
    assert options["allow_redirects"] is False
    assert options["headers"]["Authorization"] == "Bearer " + "a" * 64


@pytest.mark.parametrize("volume", [True, None, "30", -1, 101])
def test_invalid_readback_is_never_a_success(tmp_path, volume):
    client = client_for(tmp_path, {"volume": volume})
    with pytest.raises(BridgeError, match="bridge_invalid_response"):
        asyncio.run(client.read_volume())


def test_acknowledgement_without_readback_remains_unverified(tmp_path):
    value = {"requested_volume": 30, "previous_volume": 25, "acknowledged": True,
             "readback_volume": None, "verified": False, "reason": "device_timeout_outcome_unknown"}
    client = client_for(tmp_path, value)
    assert asyncio.run(client.set_volume(30)) == value
    assert len(client._session.calls) == 1


def test_inconsistent_verified_response_is_rejected(tmp_path):
    client = client_for(tmp_path, {"requested_volume": 30, "previous_volume": 25, "acknowledged": True,
                                  "readback_volume": 20, "verified": True})
    with pytest.raises(BridgeError): asyncio.run(client.set_volume(30))


@pytest.mark.parametrize("status, code", [(401, "bridge_auth_failed"), (302, "bridge_invalid_response"), (500, "bridge_error")])
def test_untrusted_error_text_is_not_forwarded(tmp_path, status, code):
    client = client_for(tmp_path, {"error": "<script>secret</script>"}, status)
    with pytest.raises(BridgeError) as error: asyncio.run(client.read_volume())
    assert error.value.code == code


def test_missing_token_does_not_create_or_contact_bridge(tmp_path):
    client = XiaozhiControlClient(tmp_path / "absent")
    with pytest.raises(BridgeError, match="bridge_not_configured"): asyncio.run(client.status())
    assert client._session is None


def test_status_projects_only_runtime_flags(tmp_path):
    client = client_for(tmp_path, {
        "connection_count": 1, "ready": True,
        "read_volume_supported": True, "set_volume_supported": True,
        "announcement_supported": True, "announcement_ready": False,
        "user_session_active": True, "announcement_reason": "device_busy",
        "stop_speech_supported": True,
        "natural_interruption": {
            "version": 1, "state": "blocked", "device_aec_advertised": False,
            "server_aec_active": False, "timestamped_audio_supported": False,
            "listen_mode": "auto", "reason": "device_aec_not_advertised",
        },
        "private_network": "must-not-escape",
    })
    value = asyncio.run(client.status())
    assert value["user_session_active"] is True
    assert value["announcement_ready"] is False
    assert value["announcement_reason"] == "device_busy"
    assert value["stop_speech_supported"] is True
    assert value["natural_interruption"]["reason"] == "device_aec_not_advertised"
    assert "private_network" not in value


def prefetch_snapshot():
    return {"version": 1, "enabled": True, "started": 2, "reused": 1,
            "invalidated": 1, "skipped_busy": 0, "failed": 0, "fallback": 1,
            "latest_status": "reused", "latest_prefetch_ms": 230,
            "latest_formal_wait_ms": 0, "latest_model_queue_ms": 0, "latest_overlap_ms": 230}


def status_with_prefetch(snapshot, **extra):
    return {"connection_count": 1, "ready": True,
            "read_volume_supported": True, "set_volume_supported": True,
            "announcement_supported": True, "announcement_ready": True,
            "user_session_active": False, "voice_asr_prefetch": snapshot, **extra}


@pytest.mark.parametrize("snapshot", [{"version": 1, "enabled": False}, prefetch_snapshot(),
                                      {**prefetch_snapshot(), "latest_overlap_ms": None}])
def test_status_accepts_strict_optional_asr_prefetch(tmp_path, snapshot):
    client = client_for(tmp_path, status_with_prefetch(snapshot))
    assert asyncio.run(client.status())["voice_asr_prefetch"] == snapshot


@pytest.mark.parametrize("change", [
    {"text": "synthetic-private-text"}, {"audio": "synthetic-base64"}, {"session_id": "private"},
    {"version": True}, {"version": 2}, {"enabled": 1}, {"enabled": False},
    {"latest_status": "candidate transcript"}, {"latest_status": []},
    {"started": True}, {"started": -1}, {"started": 1_000_001},
    {"reused": 1.5}, {"failed": None}, {"latest_prefetch_ms": "230"},
    {"latest_formal_wait_ms": -1}, {"latest_model_queue_ms": True},
    {"latest_overlap_ms": 3_600_001},
])
def test_status_rejects_extra_or_malformed_asr_prefetch_data(tmp_path, change):
    client = client_for(tmp_path, status_with_prefetch({**prefetch_snapshot(), **change}))
    with pytest.raises(BridgeError, match="bridge_invalid_response"):
        asyncio.run(client.status())


@pytest.mark.parametrize("snapshot", [None, [], {"version": 1}, {"version": 1, "enabled": True},
                                      {"version": 1, "enabled": False, "text": "private"}])
def test_status_rejects_missing_or_disabled_extra_asr_prefetch_fields(tmp_path, snapshot):
    client = client_for(tmp_path, status_with_prefetch(snapshot))
    with pytest.raises(BridgeError, match="bridge_invalid_response"):
        asyncio.run(client.status())


@pytest.mark.parametrize("mode", ["realtime", "original"])
def test_status_projects_actual_latency_mode_and_keeps_older_bridge_compatible(tmp_path, mode):
    data = status_with_prefetch({"version": 1, "enabled": False}, voice_latency_mode=mode)
    client = client_for(tmp_path, data)
    assert asyncio.run(client.status())["voice_latency_mode"] == mode
    data.pop("voice_asr_prefetch")
    data.pop("voice_latency_mode")
    older = asyncio.run(client_for(tmp_path, data).status())
    assert "voice_asr_prefetch" not in older
    assert "voice_latency_mode" not in older


@pytest.mark.parametrize("mode", ["fast", "private-transcript", None, True, []])
def test_status_rejects_unrecognized_latency_mode(tmp_path, mode):
    client = client_for(tmp_path, status_with_prefetch({"version": 1, "enabled": False}, voice_latency_mode=mode))
    with pytest.raises(BridgeError, match="bridge_invalid_response"):
        asyncio.run(client.status())


@pytest.mark.parametrize("change", [
    {"state": "ready"},
    {"state": "trial_ready"},
    {"device_aec_advertised": 1},
    {"listen_mode": "duplex"},
    {"reason": "guessed_ready"},
    {"reason": "ready_for_controlled_trial"},
])
def test_status_rejects_malformed_natural_interruption_diagnostic(tmp_path, change):
    diagnostic = {
        "version": 1, "state": "blocked", "device_aec_advertised": False,
        "server_aec_active": False, "timestamped_audio_supported": False,
        "listen_mode": "auto", "reason": "device_aec_not_advertised", **change,
    }
    client = client_for(tmp_path, {
        "connection_count": 1, "ready": True,
        "read_volume_supported": True, "set_volume_supported": True,
        "announcement_supported": True, "announcement_ready": True,
        "user_session_active": False, "natural_interruption": diagnostic,
    })
    with pytest.raises(BridgeError, match="bridge_invalid_response"):
        asyncio.run(client.status())


def test_status_projects_only_strict_voice_latency_snapshot(tmp_path):
    latency = {
        "version": 1,
        "state": "first_audio_sent",
        "started_at": "2026-09-10T10:20:30+00:00",
        "tts_backend": "voxcpm2",
        "timings_ms": {
            "memory_ready_ms": 12,
            "llm_requested_ms": 14,
            "llm_first_output_ms": 214,
            "tts_started_ms": 280,
            "audio_ready_ms": 920,
            "first_audio_sent_ms": 925,
            "response_completed_ms": 630,
        },
    }
    client = client_for(tmp_path, {
        "connection_count": 1, "ready": True,
        "read_volume_supported": True, "set_volume_supported": True,
        "announcement_supported": True, "announcement_ready": True,
        "user_session_active": False, "voice_latency": latency,
    })
    value = asyncio.run(client.status())
    assert value["voice_latency"] == latency


def test_status_accepts_v2_voice_latency_segments(tmp_path):
    latency = {
        "version": 2,
        "state": "first_audio_sent",
        "started_at": "2026-09-13T01:00:00+00:00",
        "tts_backend": "cosyvoice3",
        "timings_ms": {
            "memory_ready_ms": 12,
            "llm_requested_ms": 13,
            "llm_first_output_ms": 1945,
            "tts_started_ms": 1997,
            "audio_ready_ms": 9107,
            "first_audio_sent_ms": 9108,
            "response_completed_ms": 2167,
        },
        "tts_segments": [
            {"index": 1, "started_ms": 1997, "completed_ms": 9107, "duration_ms": 7110},
            {"index": 2, "started_ms": 9110, "completed_ms": None, "duration_ms": None},
        ],
    }
    client = client_for(tmp_path, {"connection_count": 1, "ready": True,
        "read_volume_supported": True, "set_volume_supported": True,
        "read_status_supported": True, "set_brightness_supported": False,
        "set_theme_supported": False, "allowed_volume": {"minimum": 5, "maximum": 60},
        "announcement_supported": True, "announcement_ready": True,
        "user_session_active": False, "voice_latency": latency})
    assert asyncio.run(client.status())["voice_latency"] == latency


def test_status_accepts_sanitized_v3_model_failure(tmp_path):
    latency = {
        "version": 3, "state": "failed",
        "started_at": "2026-09-14T07:37:18+00:00", "tts_backend": "cosyvoice3",
        "timings_ms": {
            "memory_ready_ms": 2, "llm_requested_ms": 3,
            "llm_first_output_ms": None, "tts_started_ms": 1773,
            "audio_ready_ms": 5939, "first_audio_sent_ms": 5941,
            "response_completed_ms": 1770,
        },
        "tts_segments": [],
        "failure": {"stage": "model", "code": "model_http_404", "at_ms": 1768},
    }
    client = client_for(tmp_path, {
        "connection_count": 0, "ready": False,
        "read_volume_supported": False, "set_volume_supported": False,
        "announcement_supported": False, "announcement_ready": False,
        "user_session_active": False, "voice_latency": latency, "reason": "device_offline",
    })
    assert asyncio.run(client.status())["voice_latency"] == latency


def test_status_accepts_sanitized_v3_memory_failure(tmp_path):
    latency = {
        "version": 3, "state": "failed",
        "started_at": "2026-09-14T08:08:15+00:00", "tts_backend": "cosyvoice3",
        "timings_ms": {
            "memory_ready_ms": None, "llm_requested_ms": None,
            "llm_first_output_ms": None, "tts_started_ms": None,
            "audio_ready_ms": None, "first_audio_sent_ms": None,
            "response_completed_ms": 35,
        },
        "tts_segments": [],
        "failure": {
            "stage": "memory", "code": "memory_response_invalid", "at_ms": 34,
        },
    }
    client = client_for(tmp_path, {
        "connection_count": 1, "ready": True,
        "read_volume_supported": True, "set_volume_supported": True,
        "announcement_supported": True, "announcement_ready": True,
        "user_session_active": False, "voice_latency": latency,
    })
    assert asyncio.run(client.status())["voice_latency"] == latency


def test_status_accepts_v4_preset_timing_and_prediction_shadow(tmp_path):
    latency = {
        "version": 4, "state": "first_audio_sent", "response_path": "preset",
        "started_at": "2026-09-14T09:00:00+00:00", "tts_backend": "cosyvoice3",
        "timings_ms": {
            "memory_ready_ms": 40, "llm_requested_ms": None,
            "llm_first_output_ms": None, "tts_started_ms": 45,
            "audio_ready_ms": 70, "first_audio_sent_ms": 75,
            "response_completed_ms": 50,
        },
        "tts_segments": [
            {"index": 1, "started_ms": 45, "completed_ms": 70, "duration_ms": 25},
        ],
    }
    shadow = {
        "version": 1, "state": "observing", "opportunities": 3,
        "evaluated": 3, "hits": 2, "misses": 1,
        "last_result": "hit_affirmative",
    }
    client = client_for(tmp_path, {
        "connection_count": 1, "ready": True,
        "read_volume_supported": True, "set_volume_supported": True,
        "announcement_supported": True, "announcement_ready": True,
        "user_session_active": False, "voice_latency": latency,
        "voice_prediction_shadow": shadow,
    })
    result = asyncio.run(client.status())
    assert result["voice_latency"] == latency
    assert result["voice_prediction_shadow"] == shadow


def test_status_accepts_v5_bounded_input_timing(tmp_path):
    latency = {
        "version": 5, "state": "first_audio_sent", "response_path": "model",
        "started_at": "2026-09-14T10:00:00+00:00", "tts_backend": "cosyvoice3",
        "input_timings_ms": {"vad_endpoint_ms": 700, "asr_processing_ms": 320},
        "timings_ms": {
            "memory_ready_ms": 40, "llm_requested_ms": 45,
            "llm_first_output_ms": 900, "tts_started_ms": 950,
            "audio_ready_ms": 2300, "first_audio_sent_ms": 2310,
            "response_completed_ms": 1500,
        },
        "tts_segments": [
            {"index": 1, "started_ms": 950, "completed_ms": 2300, "duration_ms": 1350},
        ],
    }
    client = client_for(tmp_path, {
        "connection_count": 1, "ready": True,
        "read_volume_supported": True, "set_volume_supported": True,
        "announcement_supported": True, "announcement_ready": True,
        "user_session_active": False, "voice_latency": latency,
    })
    assert asyncio.run(client.status())["voice_latency"] == latency


def test_status_accepts_v6_segment_audio_duration(tmp_path):
    latency = {
        "version": 6, "state": "first_audio_sent", "response_path": "model",
        "started_at": "2026-09-14T11:00:00+00:00", "tts_backend": "cosyvoice3",
        "input_timings_ms": {"vad_endpoint_ms": 700, "asr_processing_ms": 320},
        "timings_ms": {
            "memory_ready_ms": 40, "llm_requested_ms": 45,
            "llm_first_output_ms": 900, "tts_started_ms": 950,
            "audio_ready_ms": 2300, "first_audio_sent_ms": 2310,
            "response_completed_ms": 1500,
        },
        "tts_segments": [{
            "index": 1, "started_ms": 950, "completed_ms": 2300,
            "duration_ms": 1350, "opus_packets": 24, "audio_duration_ms": 1440,
        }],
    }
    client = client_for(tmp_path, {
        "connection_count": 1, "ready": True,
        "read_volume_supported": True, "set_volume_supported": True,
        "announcement_supported": True, "announcement_ready": True,
        "user_session_active": False, "voice_latency": latency,
    })
    assert asyncio.run(client.status())["voice_latency"] == latency


@pytest.mark.parametrize("shadow", [
    {"version": 1, "state": "observing", "opportunities": 1, "evaluated": 1,
     "hits": 1, "misses": 0, "last_result": "hit_affirmative",
     "candidate_text": "must-not-escape"},
    {"version": 1, "state": "observing", "opportunities": 2, "evaluated": 1,
     "hits": 1, "misses": 1, "last_result": "miss"},
])
def test_status_rejects_private_or_inconsistent_prediction_shadow(tmp_path, shadow):
    client = client_for(tmp_path, {
        "connection_count": 1, "ready": True,
        "read_volume_supported": True, "set_volume_supported": True,
        "announcement_supported": True, "announcement_ready": True,
        "user_session_active": False, "voice_prediction_shadow": shadow,
    })
    with pytest.raises(BridgeError, match="bridge_invalid_response"):
        asyncio.run(client.status())


def test_status_rejects_inconsistent_v2_voice_latency_segment(tmp_path):
    latency = {
        "version": 2, "state": "tts_running",
        "started_at": "2026-09-13T01:00:00+00:00", "tts_backend": "cosyvoice3",
        "timings_ms": {field: None for field in (
            "memory_ready_ms", "llm_requested_ms", "llm_first_output_ms",
            "tts_started_ms", "audio_ready_ms", "first_audio_sent_ms",
            "response_completed_ms",
        )},
        # duration 必须等于 completed-started，不能让桥接服务注入伪造指标。
        "tts_segments": [
            {"index": 1, "started_ms": 100, "completed_ms": 200, "duration_ms": 99},
        ],
    }
    client = client_for(tmp_path, {
        "connection_count": 1, "ready": True,
        "read_volume_supported": True, "set_volume_supported": True,
        "announcement_supported": True, "announcement_ready": True,
        "user_session_active": False, "voice_latency": latency,
    })
    with pytest.raises(BridgeError, match="bridge_invalid_response"):
        asyncio.run(client.status())


@pytest.mark.parametrize("change", [
    {"private_text": "must-not-escape"},
    {"tts_backend": "unknown-provider"},
    {"started_at": "not-a-time"},
    {"timings_ms": {"first_audio_sent_ms": 10}},
])
def test_status_rejects_malformed_voice_latency_snapshot(tmp_path, change):
    latency = {
        "version": 1,
        "state": "waiting_for_model",
        "started_at": "2026-09-10T10:20:30+00:00",
        "tts_backend": "edge",
        "timings_ms": {
            "memory_ready_ms": None,
            "llm_requested_ms": 8,
            "llm_first_output_ms": None,
            "tts_started_ms": None,
            "audio_ready_ms": None,
            "first_audio_sent_ms": None,
            "response_completed_ms": None,
        },
        **change,
    }
    client = client_for(tmp_path, {
        "connection_count": 1, "ready": True,
        "read_volume_supported": True, "set_volume_supported": True,
        "announcement_supported": True, "announcement_ready": True,
        "user_session_active": False, "voice_latency": latency,
    })
    with pytest.raises(BridgeError, match="bridge_invalid_response"):
        asyncio.run(client.status())


def test_oversized_response_rejected(tmp_path):
    client = client_for(tmp_path, {"volume": 25, "extra": "x" * 20000})
    with pytest.raises(BridgeError, match="bridge_invalid_response"): asyncio.run(client.read_volume())


def test_announcement_is_strictly_projected_without_claiming_playback(tmp_path):
    expires_at = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    expires_at_ms = int(expires_at.timestamp() * 1000)
    value = {
        "operation_id": "b" * 32,
        "state": "queued",
        "playback_acknowledgement": "unavailable",
        "expires_at_ms": expires_at_ms,
        "private_device_state": "must-not-escape",
    }
    client = client_for(tmp_path, value)
    assert asyncio.run(client.announce("合成问候。", expires_at)) == {
        key: value[key] for key in (
            "operation_id", "state", "playback_acknowledgement", "expires_at_ms",
        )
    }
    args, options = client._session.calls[0]
    assert args == ("POST", "http://127.0.0.1:8766/api/device/announcement")
    assert options["json"] == {"text": "合成问候。", "expires_at_ms": expires_at_ms}


def test_stop_speech_is_strictly_projected_without_claiming_device_ack(tmp_path):
    value = {
        "operation_id": "c" * 32,
        "state": "stop_sent",
        "server_interrupted": True,
        "device_acknowledgement": "unavailable",
        "private_state": "must-not-escape",
    }
    client = client_for(tmp_path, value)
    assert asyncio.run(client.stop_speech()) == {
        key: value[key] for key in (
            "operation_id", "state", "server_interrupted", "device_acknowledgement",
        )
    }
    args, options = client._session.calls[0]
    assert args == ("POST", "http://127.0.0.1:8766/api/device/speech/stop")
    assert options["json"] is None


@pytest.mark.parametrize("change", [
    {"operation_id": "bad"},
    {"state": "played"},
    {"server_interrupted": False},
    {"device_acknowledgement": "confirmed"},
])
def test_stop_speech_rejects_unproven_or_inconsistent_response(tmp_path, change):
    value = {
        "operation_id": "c" * 32,
        "state": "stop_sent",
        "server_interrupted": True,
        "device_acknowledgement": "unavailable",
        **change,
    }
    client = client_for(tmp_path, value)
    with pytest.raises(BridgeError, match="bridge_invalid_response"):
        asyncio.run(client.stop_speech())


@pytest.mark.parametrize("change", [
    {"operation_id": "not-hex"},
    {"state": "played"},
    {"playback_acknowledgement": "available"},
    {"expires_at_ms": 1},
])
def test_announcement_rejects_unproven_or_mismatched_response(tmp_path, change):
    expires_at = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    value = {
        "operation_id": "b" * 32,
        "state": "queued",
        "playback_acknowledgement": "unavailable",
        "expires_at_ms": int(expires_at.timestamp() * 1000),
        **change,
    }
    client = client_for(tmp_path, value)
    with pytest.raises(BridgeError, match="bridge_invalid_response"):
        asyncio.run(client.announce("合成问候。", expires_at))


def test_round_skin_read_and_verified_write_are_strictly_projected(tmp_path):
    skin = round_skin()
    client = client_for(tmp_path, skin)
    assert asyncio.run(client.read_round_skin()) == skin
    assert client._session.calls[0][0] == (
        "GET", "http://127.0.0.1:8766/api/device/round-skin",
    )

    response = {
        "requested_skin_id": skin["skin_id"],
        "requested_manifest_sha256": skin["manifest_sha256"],
        "acknowledged": True, "verified": True, "device_skin": skin,
        "private": "must-not-escape",
    }
    client = client_for(tmp_path, response)
    result = asyncio.run(client.set_round_skin(skin))
    assert result["verified"] is True and "private" not in result
    assert client._session.calls[0][1]["json"] == skin


def test_round_skin_rejects_false_verified_mismatch(tmp_path):
    skin = round_skin()
    changed = {**skin, "accent": 0}
    response = {
        "requested_skin_id": skin["skin_id"],
        "requested_manifest_sha256": skin["manifest_sha256"],
        "acknowledged": True, "verified": True, "device_skin": changed,
    }
    client = client_for(tmp_path, response)
    with pytest.raises(BridgeError, match="bridge_invalid_response"):
        asyncio.run(client.set_round_skin(skin))


def test_round_wallpaper_stage_projects_only_verified_slot_result(tmp_path):
    item_id, digest = "wallpaper-" + "a" * 20, "b" * 64
    response = {"wallpaper_api": 1, "slot": "b", "wallpaper_id": item_id,
                "sha256": digest, "size_bytes": 2321851,
                "state": "staged_verified", "operation_id": "c" * 32}
    client = client_for(tmp_path, response)
    result = asyncio.run(client.stage_round_wallpaper(
        item_id=item_id, sha256=digest, size_bytes=2321851,
        url="http://192.168.124.93:8768/wallpaper/" + "d" * 64,
    ))
    assert result == response
    args, options = client._session.calls[0]
    assert args == ("POST", "http://127.0.0.1:8766/api/device/round-wallpaper/stage")
    assert options["json"]["item_id"] == item_id
    assert options["timeout"].total == 150


def test_round_wallpaper_activation_and_rollback_require_exact_restart_results(tmp_path):
    item_id, digest = "wallpaper-" + "a" * 20, "b" * 64
    staged = {"wallpaper_api": 1, "slot": "b", "wallpaper_id": item_id,
              "sha256": digest, "size_bytes": 2321851, "state": "staged_verified"}
    activated = {**staged, "state": "activated_restarting", "operation_id": "c" * 32}
    client = client_for(tmp_path, activated)
    assert asyncio.run(client.activate_round_wallpaper(staged)) == activated
    assert client._session.calls[0][1]["timeout"].total == 120

    deactivated = {**activated, "slot": "a", "state": "skin_mode_restarting"}
    client = client_for(tmp_path, deactivated)
    assert asyncio.run(client.deactivate_round_wallpaper()) == deactivated
    assert client._session.calls[0][0] == (
        "POST", "http://127.0.0.1:8766/api/device/round-wallpaper/deactivate",
    )
    assert client._session.calls[0][1]["timeout"].total == 120

    rollback = {**activated, "slot": "a", "state": "rollback_restarting"}
    client = client_for(tmp_path, rollback)
    assert asyncio.run(client.rollback_round_wallpaper()) == rollback
    assert client._session.calls[0][1]["timeout"].total == 120


def test_round_wallpaper_status_requires_verified_active_record(tmp_path):
    response = {
        "wallpaper_api": 1, "active_valid": True, "active_slot": "a",
        "active_wallpaper_id": "wallpaper-" + "a" * 20,
        "active_sha256": "b" * 64, "active_size_bytes": 2321851,
        "rollback_available": True,
    }
    client = client_for(tmp_path, response)
    assert asyncio.run(client.read_round_wallpaper()) == response

    skin_mode = {
        "wallpaper_api": 1, "active_valid": False, "active_slot": "",
        "active_wallpaper_id": "", "active_sha256": "", "active_size_bytes": 0,
        "rollback_available": True,
    }
    client = client_for(tmp_path, skin_mode)
    assert asyncio.run(client.read_round_wallpaper()) == skin_mode


@pytest.mark.parametrize("change", [
    {"state": "active_verified"}, {"slot": "c"}, {"sha256": "e" * 64},
    {"size_bytes": 1}, {"operation_id": "not-hex"},
])
def test_round_wallpaper_stage_rejects_unproven_or_mismatched_response(tmp_path, change):
    item_id, digest = "wallpaper-" + "a" * 20, "b" * 64
    response = {"wallpaper_api": 1, "slot": "b", "wallpaper_id": item_id,
                "sha256": digest, "size_bytes": 2321851,
                "state": "staged_verified", "operation_id": "c" * 32,
                **change}
    client = client_for(tmp_path, response)
    with pytest.raises(BridgeError, match="bridge_invalid_response"):
        asyncio.run(client.stage_round_wallpaper(
            item_id=item_id, sha256=digest, size_bytes=2321851,
            url="http://192.168.124.93:8768/wallpaper/" + "d" * 64,
        ))
