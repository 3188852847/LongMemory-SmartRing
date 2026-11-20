"""真实回环 HTTP + 模拟控制桥，不读取个人记忆、不向物理设备发指令。"""

import asyncio
import socket
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

aiohttp = pytest.importorskip("aiohttp", reason="网页测试需要 uv sync --extra console")
pydantic = pytest.importorskip("pydantic", reason="网页契约测试需要 uv sync --extra console")
from aiohttp import web
from longmemory.entrypoints.api.server import create_app
from longmemory.adapters.device_control.xiaozhi import BridgeError

ROOT = Path(__file__).resolve().parents[3]


class FakeBridge:
    def __init__(self):
        self.calls = []
        self.error = None
        self.wait = None
        self.closed = False

    async def status(self):
        if self.error:
            raise self.error
        return {"connection_count": 1, "ready": True, "read_volume_supported": True,
                "set_volume_supported": True, "announcement_supported": True,
                "announcement_ready": True, "user_session_active": False,
                "allowed_volume": {"minimum": 5, "maximum": 100}}

    async def read_volume(self):
        self.calls.append("read")
        if self.wait:
            await self.wait.wait()
        if self.error:
            raise self.error
        return {"volume": 25}

    async def set_volume(self, volume):
        self.calls.append(volume)
        if self.error:
            raise self.error
        return {"requested_volume": volume, "previous_volume": 25,
                "acknowledged": True, "readback_volume": volume, "verified": True}

    async def announce(self, text, expires_at):
        self.calls.append(("announce", text, expires_at))
        if self.error:
            raise self.error
        return {"operation_id": "a" * 32, "state": "queued",
                "playback_acknowledgement": "unavailable",
                "expires_at_ms": int(expires_at.timestamp() * 1000)}

    async def stop_speech(self):
        self.calls.append("stop-speech")
        if self.error:
            raise self.error
        return {"operation_id": "c" * 32, "state": "stop_sent",
                "server_interrupted": True,
                "device_acknowledgement": "unavailable"}

    async def read_round_skin(self):
        self.calls.append("read-round-skin")
        if self.error:
            raise self.error
        return self.round_skin()

    async def set_round_skin(self, skin):
        self.calls.append(("set-round-skin", skin))
        if self.error:
            raise self.error
        return {"requested_skin_id": skin["skin_id"],
                "requested_manifest_sha256": skin["manifest_sha256"],
                "acknowledged": True, "verified": True, "device_skin": skin}

    async def stage_round_wallpaper(self, *, item_id, sha256, size_bytes, url):
        self.calls.append(("stage-round-wallpaper", item_id, sha256, size_bytes, url))
        if self.error:
            raise self.error
        return {"wallpaper_api": 1, "slot": "b", "wallpaper_id": item_id,
                "sha256": sha256, "size_bytes": size_bytes,
                "state": "staged_verified", "operation_id": "b" * 32}

    async def read_round_wallpaper(self):
        self.calls.append("read-round-wallpaper")
        if self.error:
            raise self.error
        return {"wallpaper_api": 1, "active_valid": True, "active_slot": "a",
                "active_wallpaper_id": "wallpaper-" + "a" * 20,
                "active_sha256": "d" * 64, "active_size_bytes": 1234,
                "rollback_available": True}

    async def activate_round_wallpaper(self, staged):
        self.calls.append(("activate-round-wallpaper", staged))
        if self.error:
            raise self.error
        return {**staged, "state": "activated_restarting", "operation_id": "c" * 32}

    async def rollback_round_wallpaper(self):
        self.calls.append("rollback-round-wallpaper")
        if self.error:
            raise self.error
        return {"wallpaper_api": 1, "slot": "a",
                "wallpaper_id": "wallpaper-" + "a" * 20, "sha256": "d" * 64,
                "size_bytes": 1234, "state": "rollback_restarting",
                "operation_id": "e" * 32}

    async def deactivate_round_wallpaper(self):
        self.calls.append("deactivate-round-wallpaper")
        if self.error:
            raise self.error
        return {"wallpaper_api": 1, "slot": "a",
                "wallpaper_id": "wallpaper-" + "a" * 20, "sha256": "d" * 64,
                "size_bytes": 1234, "state": "skin_mode_restarting",
                "operation_id": "f" * 32}

    @staticmethod
    def round_skin():
        return {
            "skin_api": 1, "skin_id": "rose-night-v1", "manifest_sha256": "a" * 64,
            "background": 0x171B26, "foreground": 0xF7F4F8, "muted": 0xCBD1DC,
            "accent": 0xDF72A8, "listening": 0x69D5FF, "thinking": 0xF7C65A,
            "happy": 0x7DE2B8, "concerned": 0x8AA8FF, "error": 0xF16C73,
            "eye_width": 22, "eye_height": 36, "mouth_width": 38,
        }

    async def close(self):
        self.closed = True


@asynccontextmanager
async def console(allow_memory_delete=False, chat_backend=None,
                  allow_memory_correction=False,
                  xiaozhi_server=None, memory_runtime_token=None,
                  model_profile_store=None, voice_model_profiles=None,
                  tts_backend_store=None,
                  round_skin_store=None, round_wallpaper_library=None,
                  round_wallpaper_delivery=None):
    # 先占用随机回环端口，再把精确 Host 交给应用，避免探测后抢占端口。
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    bridge = FakeBridge()
    runner = web.AppRunner(create_app(port=port, bridge=bridge,
                                     allow_memory_delete=allow_memory_delete, chat_backend=chat_backend,
                                     allow_memory_correction=allow_memory_correction,
                                     xiaozhi_server=xiaozhi_server,
                                     memory_runtime_token=memory_runtime_token,
                                     model_profile_store=model_profile_store,
                                     voice_model_profiles=voice_model_profiles,
                                     tts_backend_store=tts_backend_store,
                                     round_skin_store=round_skin_store,
                                     round_wallpaper_library=round_wallpaper_library,
                                     round_wallpaper_delivery=round_wallpaper_delivery), access_log=None)
    await runner.setup()
    await web.SockSite(runner, sock).start()
    try:
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True), trust_env=False) as client:
            yield client, f"http://127.0.0.1:{port}", bridge
    finally:
        await runner.cleanup()
    assert bridge.closed


async def login(client, base):
    response = await client.get(base + "/api/session", headers={"X-Console-Bootstrap": "1"})
    assert response.status == 200
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    return {"Origin": base, "X-Console-CSRF": (await response.json())["csrf"]}


class FakeWallpaperLibrary:
    def __init__(self, root):
        self.root = root
        self.root.mkdir()
        self.received = b""
        self.preview = self.root / "preview.gif"
        self.preview.write_bytes(b"GIF89a")

    def describe(self):
        return {"enabled": True, "tool_state": "ready", "max_upload_bytes": 768 * 1024 * 1024,
                "items": []}

    def create_staging(self):
        directory = self.root / "upload"
        directory.mkdir()
        return directory, directory / "source.media"

    def import_staging(self, directory, *, original_filename, spec):
        self.received = (directory / "source.media").read_bytes()
        assert original_filename == "wallpaper.mp4"
        assert spec.start_seconds == 2 and spec.duration_seconds == 3
        directory.rename(self.root / "committed")
        return {"id": "wallpaper-" + "a" * 20, "state": "ready"}

    def discard_staging(self, directory):
        if directory.exists():
            directory.rmdir()

    def preview_path(self, item_id):
        assert item_id == "wallpaper-" + "a" * 20
        return self.preview

    def delivery_spec(self, item_id):
        assert item_id == "wallpaper-" + "a" * 20
        return {"item_id": item_id, "path": self.preview,
                "sha256": "d" * 64, "size_bytes": self.preview.stat().st_size}


class FakeWallpaperDelivery:
    def __init__(self):
        self.revoked = []

    def issue(self, **values):
        from types import SimpleNamespace
        assert values["expected_sha256"] == "d" * 64
        ticket = SimpleNamespace(token="e" * 64)
        return ticket, "http://192.168.124.93:8768/wallpaper/" + ticket.token

    def revoke(self, token):
        self.revoked.append(token)

    def app(self):
        return web.Application()


def test_round_wallpaper_upload_and_preview_are_csrf_protected(tmp_path):
    async def run():
        library = FakeWallpaperLibrary(tmp_path / "wallpapers")
        async with console(round_wallpaper_library=library) as (client, base, _bridge):
            headers = await login(client, base)
            listing = await client.get(base + "/api/round-wallpapers")
            assert listing.status == 200 and (await listing.json())["tool_state"] == "ready"
            form = aiohttp.FormData()
            form.add_field("file", b"synthetic-video", filename="wallpaper.mp4",
                           content_type="video/mp4")
            rejected = await client.post(
                base + "/api/round-wallpapers?start_seconds=2&duration_seconds=3&frame_rate=8&colors=64",
                data=form,
            )
            assert rejected.status == 403

            form = aiohttp.FormData()
            form.add_field("file", b"synthetic-video", filename="wallpaper.mp4",
                           content_type="video/mp4")
            accepted = await client.post(
                base + "/api/round-wallpapers?start_seconds=2&duration_seconds=3&frame_rate=8&colors=64",
                data=form, headers=headers,
            )
            assert accepted.status == 201
            assert library.received == b"synthetic-video"
            preview = await client.get(base + "/api/round-wallpapers/wallpaper-" + "a" * 20 + "/preview")
            assert preview.status == 200 and preview.content_type == "image/gif"
            assert await preview.read() == b"GIF89a"
    asyncio.run(run())


def test_round_wallpaper_stage_is_csrf_protected_and_reports_staged_not_active(tmp_path):
    async def run():
        library = FakeWallpaperLibrary(tmp_path / "wallpapers")
        delivery = FakeWallpaperDelivery()
        # 该合成服务不需要真的监听第二端口，因此只把投递对象交给路由。
        async with console(round_wallpaper_library=library) as (client, base, bridge):
            headers = await login(client, base)
            item_id = "wallpaper-" + "a" * 20
            unavailable = await client.post(base + f"/api/round-wallpapers/{item_id}/stage",
                                            headers=headers)
            assert unavailable.status == 503

        # 直接构造应用以注入投递对象，同时清空其启动钩子，避免绑定 LAN。
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        bridge = FakeBridge()
        app = create_app(port=port, bridge=bridge, round_wallpaper_library=library,
                         round_wallpaper_delivery=delivery)
        app.on_startup.clear()
        app.on_cleanup.clear()
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        try:
            async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True), trust_env=False) as client:
                base = f"http://127.0.0.1:{port}"
                headers = await login(client, base)
                assert (await client.post(base + f"/api/round-wallpapers/{item_id}/stage")).status == 403
                response = await client.post(base + f"/api/round-wallpapers/{item_id}/stage", headers=headers)
                data = await response.json()
                assert response.status == 200 and data["state"] == "staged_verified"
                assert "active" not in data
                assert delivery.revoked == ["e" * 64]
                assert bridge.calls[-1][0] == "stage-round-wallpaper"
        finally:
            await runner.cleanup()

    asyncio.run(run())


def test_round_wallpaper_publish_stages_then_activates_and_revokes_ticket(tmp_path):
    async def run():
        library = FakeWallpaperLibrary(tmp_path / "wallpapers")
        delivery = FakeWallpaperDelivery()
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        bridge = FakeBridge()
        app = create_app(port=port, bridge=bridge, round_wallpaper_library=library,
                         round_wallpaper_delivery=delivery)
        app.on_startup.clear()
        app.on_cleanup.clear()
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        try:
            async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True), trust_env=False) as client:
                base = f"http://127.0.0.1:{port}"
                headers = await login(client, base)
                item_id = "wallpaper-" + "a" * 20
                response = await client.post(
                    base + f"/api/round-wallpapers/{item_id}/publish", headers=headers,
                )
                data = await response.json()
                assert response.status == 200 and data["state"] == "activated_restarting"
                assert [call[0] for call in bridge.calls[-2:]] == [
                    "stage-round-wallpaper", "activate-round-wallpaper",
                ]
                assert delivery.revoked == ["e" * 64]
        finally:
            await runner.cleanup()

    asyncio.run(run())


def test_round_wallpaper_deactivate_is_csrf_protected_and_keeps_slot_metadata(tmp_path):
    async def run():
        library = FakeWallpaperLibrary(tmp_path / "wallpapers")
        async with console(round_wallpaper_library=library) as (client, base, bridge):
            headers = await login(client, base)
            assert (await client.post(base + "/api/round-wallpapers/deactivate")).status == 403
            response = await client.post(
                base + "/api/round-wallpapers/deactivate", headers=headers,
            )
            data = await response.json()
            assert response.status == 200
            assert data["state"] == "skin_mode_restarting"
            assert data["wallpaper_id"] == "wallpaper-" + "a" * 20
            assert bridge.calls[-1] == "deactivate-round-wallpaper"

    asyncio.run(run())


def test_console_serves_only_local_assets_and_protected_device_actions():
    async def run():
        async with console() as (client, base, bridge):
            for path in ("/", "/assets/console.css", "/assets/app.js", "/assets/state.mjs", "/assets/favicon.svg"):
                response = await client.get(base + path)
                assert response.status == 200
                assert "default-src 'none'" in response.headers["Content-Security-Policy"]
                assert response.headers["Cache-Control"] == "no-store"
                assert response.headers["X-Frame-Options"] == "DENY"
            for path in ("/.env", "/data/control/device-control.token", "/assets/README.md", "/api/arbitrary-tool"):
                assert (await client.get(base + path)).status in {401, 404}
            assert (await client.get(base + "/api/session")).status == 403
            assert (await client.get(base + "/api/device")).status == 401
            assert (await client.get(base + "/api/runtime-status")).status == 401
            headers = await login(client, base)
            runtime_status = await (await client.get(base + "/api/runtime-status")).json()
            assert runtime_status["state"] == "launcher_unavailable"
            assert runtime_status["services"] == {}
            response = await client.get(base + "/api/device")
            assert (await response.json())["ready"] is True
            assert bridge.calls == []  # 连接轮询不发设备命令。
            assert (await (await client.get(base + "/api/device/volume")).json()) == {"volume": 25}
            response = await client.post(base + "/api/device/volume", headers=headers, json={"volume": 100})
            assert response.status == 200
            assert (await response.json())["verified"] is True
            response = await client.post(base + "/api/device/speech/stop", headers=headers)
            assert response.status == 200
            assert (await response.json())["state"] == "stop_sent"
            assert bridge.calls == ["read", 100, "stop-speech"]
    asyncio.run(run())


def test_round_skin_api_is_csrf_protected_and_does_not_claim_device_apply(tmp_path):
    from longmemory.infrastructure.config.round_skins import RoundSkinStore

    skin_root = tmp_path / "firmware/smartring_plus/skins"
    skin_root.mkdir(parents=True)
    source = ROOT / "firmware/smartring_plus/skins/rose-night-v1.skin.json"
    (skin_root / source.name).write_bytes(source.read_bytes())

    async def run():
        store = RoundSkinStore(tmp_path)
        async with console(round_skin_store=store) as (client, base, _bridge):
            headers = await login(client, base)
            response = await client.get(base + "/api/round-skins")
            data = await response.json()
            assert response.status == 200
            assert data["delivery"]["device_apply_supported"] is False
            assert (await client.put(base + "/api/round-skins/selection", json={"skin_id": "rose-night-v1"})).status == 403
            response = await client.put(base + "/api/round-skins/selection", headers=headers, json={"skin_id": "rose-night-v1"})
            assert response.status == 200
            assert (await response.json())["selected_skin"] == "rose-night-v1"
            readback = await client.get(base + "/api/round-skins/device")
            assert readback.status == 200
            assert (await readback.json())["skin_id"] == "rose-night-v1"
            assert (await client.post(base + "/api/round-skins/device", json={"skin_id": "rose-night-v1"})).status == 403
            applied = await client.post(base + "/api/round-skins/device", headers=headers, json={"skin_id": "rose-night-v1"})
            assert applied.status == 200
            assert (await applied.json())["verified"] is True
            custom_body = {
                "base_skin_id": "rose-night-v1",
                "expected_manifest_sha256": None,
                "palette": {key: "#335577" for key in (
                    "background", "foreground", "muted", "accent", "listening",
                    "thinking", "happy", "concerned", "error",
                )},
                "face": {"eye_width": 24, "eye_height": 38, "mouth_width": 44},
            }
            assert (await client.put(base + "/api/round-skins/custom", json=custom_body)).status == 403
            custom_response = await client.put(base + "/api/round-skins/custom", headers=headers, json=custom_body)
            assert custom_response.status == 200
            custom_data = await custom_response.json()
            custom = next(item for item in custom_data["skins"] if item["id"] == "local-custom-v1")
            assert custom["face"]["mouth_width"] == 44
            assert custom["palette"]["background"] == "#335577"
            assert (await client.put(base + "/api/round-skins/custom", headers=headers, json=custom_body)).status == 409

    asyncio.run(run())


@pytest.mark.parametrize("attack", ["no_csrf", "no_origin", "other_origin", "other_host", "cross_site", "same_site", "wrong_cookie"])
def test_console_rejects_browser_attacks_without_calling_device(attack):
    async def run():
        async with console() as (client, base, bridge):
            headers = await login(client, base)
            if attack == "no_csrf": headers.pop("X-Console-CSRF")
            if attack == "no_origin": headers.pop("Origin")
            if attack == "other_origin": headers["Origin"] = "https://evil.invalid"
            if attack == "other_host": headers["Host"] = "evil.invalid"
            if attack == "cross_site": headers["Sec-Fetch-Site"] = "cross-site"
            if attack == "same_site": headers["Sec-Fetch-Site"] = "same-site"
            if attack == "wrong_cookie": client.cookie_jar.clear()
            response = await client.post(base + "/api/device/volume", headers=headers, json={"volume": 30})
            assert response.status in {401, 403}
            assert bridge.calls == []
            assert "Access-Control-Allow-Origin" not in response.headers
    asyncio.run(run())


@pytest.mark.parametrize("body", [{"volume": True}, {"volume": 4}, {"volume": 101}, {"volume": 30.1}, {"volume": "30"}, {}, [], {"volume": 30, "tool": "evil"}])
def test_console_rejects_invalid_volume(body):
    async def run():
        async with console() as (client, base, bridge):
            headers = await login(client, base)
            response = await client.post(base + "/api/device/volume", headers=headers, json=body)
            assert response.status == 400
            assert bridge.calls == []
    asyncio.run(run())


def test_console_limits_body_and_does_not_retry_uncertain_write():
    async def run():
        async with console() as (client, base, bridge):
            headers = await login(client, base)
            response = await client.post(base + "/api/device/volume", headers=headers, data="volume=30")
            assert response.status == 400
            response = await client.post(base + "/api/device/volume", headers=headers, json={"volume": "x" * 2000})
            assert response.status == 413
            assert bridge.calls == []
            bridge.error = BridgeError("device_timeout_outcome_unknown", 504)
            response = await client.post(base + "/api/device/volume", headers=headers, json={"volume": 30})
            assert response.status == 504
            assert (await response.json())["error"] == "device_timeout_outcome_unknown"
            assert bridge.calls == [30]
    asyncio.run(run())


def test_console_serializes_device_operations():
    async def run():
        async with console() as (client, base, bridge):
            headers = await login(client, base)
            bridge.wait = asyncio.Event()
            first = asyncio.create_task(client.get(base + "/api/device/volume"))
            for _ in range(100):
                if bridge.calls: break
                await asyncio.sleep(0.005)
            assert bridge.calls == ["read"]
            response = await client.post(base + "/api/device/volume", headers=headers, json={"volume": 30})
            assert response.status == 409
            assert bridge.calls == ["read"]
            bridge.wait.set()
            assert (await first).status == 200
    asyncio.run(run())


def test_memory_mode_reports_chat_disabled_instead_of_fake_state():
    async def run():
        async with console() as (client, base, _bridge):
            await login(client, base)
            assert (await client.get(base + "/api/memory-mode")).status == 503

    asyncio.run(run())
