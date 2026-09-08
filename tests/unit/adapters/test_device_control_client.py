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
        "private_network": "must-not-escape",
    })
    value = asyncio.run(client.status())
    assert value["user_session_active"] is True
    assert value["announcement_ready"] is False
    assert value["announcement_reason"] == "device_busy"
    assert "private_network" not in value


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
