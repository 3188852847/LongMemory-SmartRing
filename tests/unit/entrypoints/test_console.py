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
                "allowed_volume": {"minimum": 5, "maximum": 60}}

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
async def console(database=None, allow_memory_delete=False, chat_backend=None,
                  allow_memory_correction=False, allow_scenario_management=False,
                  allow_persona_management=False,
                  xiaozhi_server=None, memory_runtime_token=None,
                  scenario_producer=None, scenario_model=None,
                  persona_producer=None, persona_model=None,
                  proactive_clock=None, model_profile_store=None, voice_model_profiles=None,
                  memory_backend_store=None, xiaozhi_memory_backends=None,
                  tts_backend_store=None,
                  round_skin_store=None, round_wallpaper_library=None,
                  round_wallpaper_delivery=None):
    # 先占用随机回环端口，再把精确 Host 交给应用，避免探测后抢占端口。
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    bridge = FakeBridge()
    runner = web.AppRunner(create_app(port=port, bridge=bridge, database=database,
                                     allow_memory_delete=allow_memory_delete, chat_backend=chat_backend,
                                     allow_memory_correction=allow_memory_correction,
                                     allow_scenario_management=allow_scenario_management,
                                     allow_persona_management=allow_persona_management,
                                     xiaozhi_server=xiaozhi_server,
                                     memory_runtime_token=memory_runtime_token,
                                     scenario_producer=scenario_producer,
                                     scenario_model=scenario_model,
                                     persona_producer=persona_producer,
                                     persona_model=persona_model,
                                     proactive_clock=proactive_clock,
                                     model_profile_store=model_profile_store,
                                     voice_model_profiles=voice_model_profiles,
                                     memory_backend_store=memory_backend_store,
                                     xiaozhi_memory_backends=xiaozhi_memory_backends,
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
            response = await client.post(base + "/api/device/volume", headers=headers, json={"volume": 30})
            assert response.status == 200
            assert (await response.json())["verified"] is True
            response = await client.post(base + "/api/device/speech/stop", headers=headers)
            assert response.status == 200
            assert (await response.json())["state"] == "stop_sent"
            assert bridge.calls == ["read", 30, "stop-speech"]
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


def test_companion_strategy_analysis_is_csrf_protected_and_never_activates(tmp_path):
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "companion-strategy-http.db"
    LongMemoryV1(database).close()

    async def run():
        async with console(database) as (client, base, _bridge):
            headers = await login(client, base)
            rejected = await client.post(
                base + "/api/companion-strategy-candidates/analyze", json={},
            )
            assert rejected.status == 403
            invalid = await client.post(
                base + "/api/companion-strategy-candidates/analyze",
                headers=headers, json={"activate": True},
            )
            assert invalid.status == 400
            analyzed = await client.post(
                base + "/api/companion-strategy-candidates/analyze",
                headers=headers, json={},
            )
            result = await analyzed.json()
            assert analyzed.status == 200
            assert result == {
                "outcome": "insufficient_cross_date_evidence",
                "eligible_observation_count": 0,
                "distinct_local_dates": 0,
                "candidate": None,
            }
            listed = await client.get(
                base + "/api/companion-strategy-candidates",
            )
            assert listed.status == 200
            assert await listed.json() == {"items": []}
            initiated = await client.get(
                base + "/api/companion-user-initiated-interactions?limit=10",
            )
            assert initiated.status == 200
            assert await initiated.json() == {"items": []}
            assert (await client.get(
                base + "/api/companion-user-initiated-interactions?limit=0",
            )).status == 400
            routine_rejected = await client.post(
                base + "/api/companion-routine-candidates/analyze", json={},
            )
            assert routine_rejected.status == 403
            routine = await client.post(
                base + "/api/companion-routine-candidates/analyze",
                headers=headers, json={},
            )
            assert routine.status == 200
            assert await routine.json() == {
                "outcome": "insufficient_cross_date_evidence",
                "eligible_observation_count": 0,
                "distinct_local_dates": 0,
                "candidate": None,
            }
            routine_list = await client.get(
                base + "/api/companion-routine-candidates",
            )
            assert routine_list.status == 200
            assert await routine_list.json() == {"items": []}
            versions = await client.get(
                base + "/api/companion-absence-strategy-versions",
            )
            assert versions.status == 200
            assert await versions.json() == {
                "items": [], "events": [],
                "selection": {"current_version_id": None, "revision": 0, "updated_at": None},
            }
            switch_without_csrf = await client.post(
                base + "/api/companion-absence-strategy-versions/activate",
                json={"version_id": "a" * 32, "expected_revision": 0},
            )
            assert switch_without_csrf.status == 403
            missing_version = await client.post(
                base + "/api/companion-absence-strategy-versions/activate",
                headers=headers,
                json={"version_id": "a" * 32, "expected_revision": 0},
            )
            assert missing_version.status == 404
            assert (await missing_version.json())["error"] == "companion_absence_version_missing"
            no_csrf = await client.post(
                base + "/api/companion-absence-strategy-versions/draft",
                json={"candidate_id": "a" * 32, "expected_candidate_revision": 1},
            )
            assert no_csrf.status == 403
            invalid = await client.post(
                base + "/api/companion-absence-strategy-versions/draft",
                headers=headers,
                json={"candidate_id": "../personal.db", "expected_candidate_revision": 1},
            )
            assert invalid.status == 400
            missing = await client.post(
                base + "/api/companion-absence-strategy-versions/draft",
                headers=headers,
                json={"candidate_id": "a" * 32, "expected_candidate_revision": 1},
            )
            assert missing.status == 409
            assert (await missing.json())["error"] == "companion_routine_candidate_conflict"

    asyncio.run(run())


def test_console_exposes_read_only_consolidation_status(tmp_path):
    from longmemory.bootstrap import build_application

    database = tmp_path / "consolidation-status.db"
    application = build_application(database_path=database)
    application.close()

    async def run():
        async with console(database) as (client, base, _bridge):
            assert (await client.get(base + "/api/consolidation-status")).status == 401
            await login(client, base)
            response = await client.get(base + "/api/consolidation-status")
            data = await response.json()
            assert response.status == 200
            assert data["background_enabled"] is False
            assert [item["stage"] for item in data["stages"]] == [
                "l1_to_l2", "l2_to_l3",
            ]
            assert all(item["pending_new_source_count"] == 0 for item in data["stages"])
            assert all(item["trigger_reason"] == "no_pending_evidence" for item in data["stages"])

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


@pytest.mark.parametrize("body", [{"volume": True}, {"volume": 4}, {"volume": 61}, {"volume": 30.1}, {"volume": "30"}, {}, [], {"volume": 30, "tool": "evil"}])
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


def test_memory_http_browse_sources_confirmed_delete_and_persistence(tmp_path):
    from longmemory.bootstrap import build_application
    database = tmp_path / "synthetic.db"
    app = build_application(database_path=database)
    result = app.chat("我养了一只叫豆包的猫。")
    memory_id = str(result.saved_memories[0].id)
    app.close()

    async def run():
        async with console(database, True) as (client, base, _bridge):
            assert (await client.get(base + "/memories")).status == 200
            assert (await client.get(base + "/api/memories")).status == 401
            headers = await login(client, base)
            config = await (await client.get(base + "/api/memory-config")).json()
            assert config["database"] == str(database.resolve())
            assert config["allow_delete"] is True
            assert config["allow_clear"] is True
            listed = await (await client.get(base + "/api/memories?q=豆包")).json()
            assert listed["total"] == 1
            assert "sources" not in listed["items"][0]
            url = base + "/api/memories/" + memory_id
            details = await (await client.get(url)).json()
            assert details["sources"][0]["message"]["content"] == "我养了一只叫豆包的猫。"
            day = details["recorded_at"][:10]
            daily_response = await client.get(
                base + f"/api/memories/daily-review?local_date={day}&utc_offset_minutes=0"
            )
            daily = await daily_response.json()
            assert daily_response.status == 200
            assert daily["total"] == 1 and daily["items"][0]["id"] == memory_id
            assert (await client.get(
                base + f"/api/memories/daily-review?local_date={day}&utc_offset_minutes=9999"
            )).status == 400
            source_id = details["sources"][0]["source_message_id"]
            l0 = await (await client.get(base + "/api/source-messages?link_state=linked")).json()
            assert l0["total"] >= 1 and any(item["id"] == source_id for item in l0["items"])
            dated_l0 = await (await client.get(
                base + f"/api/source-messages?role=user&local_date={day}&utc_offset_minutes=0"
            )).json()
            assert any(item["id"] == source_id for item in dated_l0["items"])
            l0_detail = await (await client.get(base + "/api/source-messages/" + source_id)).json()
            assert l0_detail["derived_memories"][0]["id"] == memory_id
            body = {"revision": details["revision"], "confirm_delete": True}
            assert (await client.delete(url, json=body)).status == 403
            assert (await client.delete(url, headers={**headers, "Origin": "https://evil.invalid"}, json=body)).status == 403
            assert (await client.delete(url, headers=headers, json={**body, "confirm_delete": False})).status == 400
            response = await client.delete(url, headers=headers, json=body)
            assert response.status == 200
            assert (await response.json())["l0_preserved"] is True
            assert (await client.get(url)).status == 404
            assert (await client.delete(url, headers=headers, json=body)).status == 404
    asyncio.run(run())
    reopened = build_application(database_path=database)
    assert reopened.get_memory(result.saved_memories[0].id) is None
    assert reopened.chat("我的猫叫什么？").retrieved_memories == ()
    reopened.close()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT content FROM conversation_messages WHERE id=?", (str(result.user_message.id),)).fetchone()[0] == "我养了一只叫豆包的猫。"


def test_memory_http_bulk_clear_requires_auth_confirmation_and_current_preview(tmp_path):
    from longmemory.bootstrap import build_application
    database = tmp_path / "bulk-clear.db"
    app = build_application(database_path=database)
    first = app.chat("我养了一只叫豆包的猫。")
    app.chat("我喜欢喝乌龙茶。")
    app.close()

    async def run():
        async with console(database, True) as (client, base, _bridge):
            # 静态清空路由必须优先于 /api/memories/{memory_id}，否则会被当作 ID。
            assert (await client.get(base + "/api/memories/clear-preview")).status == 401
            headers = await login(client, base)
            preview_response = await client.get(base + "/api/memories/clear-preview")
            preview = await preview_response.json()
            assert preview_response.status == 200 and preview["l1_total"] == 2
            body = {"revision": preview["revision"], "confirm_clear": True}
            assert (await client.post(base + "/api/memories/clear", json=body)).status == 403
            assert (await client.post(
                base + "/api/memories/clear", headers=headers,
                json={**body, "confirm_clear": False},
            )).status == 400
            response = await client.post(base + "/api/memories/clear", headers=headers, json=body)
            result = await response.json()
            assert response.status == 200 and result["deleted_l1"] == 2
            assert result["l0_preserved"] == 4
            assert (await (await client.get(base + "/api/memories?state=all")).json())["total"] == 0
            assert (await client.post(base + "/api/memories/clear", headers=headers, json=body)).status == 409

    asyncio.run(run())
    reopened = build_application(database_path=database)
    assert reopened.get_memory(first.saved_memories[0].id) is None
    reopened.close()


def test_memory_http_wipe_requires_auth_confirmation_and_current_preview(tmp_path):
    from longmemory.bootstrap import build_application
    database = tmp_path / "wipe.db"
    application = build_application(database_path=database)
    application.chat("我养了一只叫豆包的猫。")
    application.close()

    async def run():
        async with console(database, True) as (client, base, _bridge):
            assert (await client.get(base + "/api/memories/wipe-preview")).status == 401
            headers = await login(client, base)
            preview = await (await client.get(base + "/api/memories/wipe-preview")).json()
            assert preview["l0_total"] == 2 and preview["l1_total"] == 1
            body = {"revision": preview["revision"], "confirm_wipe": True}
            assert (await client.post(base + "/api/memories/wipe", json=body)).status == 403
            assert (await client.post(
                base + "/api/memories/wipe", headers=headers,
                json={**body, "confirm_wipe": False},
            )).status == 400
            response = await client.post(base + "/api/memories/wipe", headers=headers, json=body)
            result = await response.json()
            assert response.status == 200 and result["l0_total"] == 2
            assert len(result["backup"]["sha256"]) == 64
            assert (await (await client.get(base + "/api/source-messages")).json())["total"] == 0
            assert (await client.post(base + "/api/memories/wipe", headers=headers, json=body)).status == 409

    asyncio.run(run())


def test_memory_http_promotes_existing_l0_with_csrf_and_explicit_confirmation(tmp_path):
    from longmemory.bootstrap import build_application
    database = tmp_path / "promote-source.db"
    app = build_application(database_path=database)
    app.close()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO conversation_messages VALUES (?,?,?,?)",
            ("missed-l0", "user", "我最近开始晨跑。", "2026-09-09T08:00:00+00:00"),
        )

    async def run():
        async with console(database, allow_memory_correction=True) as (client, base, _bridge):
            headers = await login(client, base)
            detail = await (await client.get(base + "/api/source-messages/missed-l0")).json()
            body = {"content": "用户最近开始每天晨跑。", "revision": detail["revision"],
                    "confirm_promote": True}
            assert (await client.post(
                base + "/api/source-messages/missed-l0/promote", json=body,
            )).status == 403
            assert (await client.post(
                base + "/api/source-messages/missed-l0/promote", headers=headers,
                json={**body, "confirm_promote": False},
            )).status == 400
            response = await client.post(
                base + "/api/source-messages/missed-l0/promote", headers=headers, json=body,
            )
            result = await response.json()
            assert response.status == 200 and result["created_new_memory"] is True
            source = await (await client.get(base + "/api/source-messages/missed-l0")).json()
            assert source["derived_memories"][0]["content"] == "用户最近开始每天晨跑。"

    asyncio.run(run())


def test_memory_http_correction_requires_explicit_semantics_and_confirmation(tmp_path):
    from longmemory.bootstrap import build_application
    database = tmp_path / "correction.db"
    app = build_application(database_path=database)
    result = app.chat("我养了一只叫豆包的猫。")
    memory_id = str(result.saved_memories[0].id)
    app.close()

    async def run():
        async with console(database, allow_memory_correction=True) as (client, base, _bridge):
            headers = await login(client, base)
            url = base + "/api/memories/" + memory_id
            details = await (await client.get(url)).json()
            body = {"revision": details["revision"], "corrected_content": "用户的猫叫年糕。",
                    "correction_kind": "error", "confirm_correction": True}
            assert (await client.post(url + "/corrections", json=body)).status == 403
            assert (await client.post(url + "/corrections", headers=headers,
                                      json={**body, "correction_kind": "change"})).status == 400
            assert (await client.post(url + "/corrections", headers=headers,
                                      json={**body, "confirm_correction": False})).status == 400
            response = await client.post(url + "/corrections", headers=headers, json=body)
            assert response.status == 200
            written = await response.json()
            assert written["source_type"] == "user_corrected"
            old = await (await client.get(url)).json()
            new = await (await client.get(base + "/api/memories/" + written["new_memory_id"])).json()
            assert old["state"] == "retired" and old["superseded_by_id"] == new["id"]
            assert new["content"] == "用户的猫叫年糕。"

    asyncio.run(run())


def test_memory_http_fact_change_requires_explicit_semantics_and_time(tmp_path):
    from longmemory.bootstrap import build_application
    database = tmp_path / "fact-change.db"
    app = build_application(database_path=database)
    result = app.chat("我养了一只叫豆包的猫。")
    memory_id = str(result.saved_memories[0].id)
    app.close()

    async def run():
        async with console(database, allow_memory_correction=True) as (client, base, _bridge):
            headers = await login(client, base)
            url = base + "/api/memories/" + memory_id
            details = await (await client.get(url)).json()
            body = {
                "revision": details["revision"],
                "new_content": "用户现在养了一只叫年糕的猫。",
                "effective_at": "2026-09-03T12:00:00+00:00",
                "change_kind": "fact_changed",
                "confirm_change": True,
            }
            assert (await client.post(url + "/changes", json=body)).status == 403
            assert (await client.post(
                url + "/changes", headers=headers,
                json={**body, "change_kind": "error"},
            )).status == 400
            assert (await client.post(
                url + "/changes", headers=headers,
                json={**body, "effective_at": "2026-09-03T12:00:00"},
            )).status == 400
            response = await client.post(url + "/changes", headers=headers, json=body)
            assert response.status == 200
            written = await response.json()
            old = await (await client.get(url)).json()
            new = await (await client.get(
                base + "/api/memories/" + written["new_memory_id"]
            )).json()
            assert old["valid_to"] == body["effective_at"]
            assert new["valid_from"] == body["effective_at"]
            assert new["sources"][0]["source_type"] == "user_stated"

    asyncio.run(run())


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "offset=100001", "state=unknown", "database=other.db", "limit=1&limit=2", "limit=no", "q=" + "x" * 201])
def test_memory_query_validation(query):
    async def run():
        async with console() as (client, base, _bridge):
            await login(client, base)
            assert (await client.get(base + "/api/memories?" + query)).status == 400
    asyncio.run(run())


@pytest.mark.parametrize("query", [
    "limit=0", "limit=101", "offset=-1", "role=system", "link_state=unknown",
    "role=user&role=assistant", "q=" + "x" * 201, "local_date=2026-09-09",
    "utc_offset_minutes=480", "local_date=bad&utc_offset_minutes=480",
    "local_date=2026-99-99&utc_offset_minutes=480",
    "local_date=2026-09-09&utc_offset_minutes=9999",
])
def test_source_message_query_validation(query):
    async def run():
        async with console() as (client, base, _bridge):
            await login(client, base)
            assert (await client.get(base + "/api/source-messages?" + query)).status == 400
    asyncio.run(run())


def test_memory_without_config_is_not_a_fake_empty_database():
    async def run():
        async with console() as (client, base, _bridge):
            await login(client, base)
            config = await (await client.get(base + "/api/memory-config")).json()
            assert config == {"configured": False, "database": None, "allow_delete": False,
                              "allow_clear": False,
                              "allow_correction": False, "allow_change": False,
                              "allow_promote_source": False,
                              "allow_scenario_management": False,
                              "allow_persona_management": False,
                              "scenario_model_preview_available": False,
                              "scenario_model": None,
                              "persona_model_preview_available": False,
                              "persona_model": None}
            response = await client.get(base + "/api/memories")
            assert response.status == 503
            assert (await response.json())["error"] == "memory_not_configured"
            # 缺少记忆库时，设备页仍然工作，不制造两条链路之间的耦合。
            assert (await client.get(base + "/api/device")).status == 200
    asyncio.run(run())


def test_internal_runtime_requires_token_and_is_immediately_shared_with_web(tmp_path):
    from longmemory.adapters.llm.fake import FakeAnswerGenerator
    from longmemory.entrypoints.api.chat_backend import ChatBackend
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "shared-runtime.db"
    LongMemoryV1(database).close()
    backend = ChatBackend(database, FakeAnswerGenerator())
    token = "a" * 64

    async def run():
        async with console(database, chat_backend=backend, memory_runtime_token=token) as (client, base, _bridge):
            endpoint = base + "/api/internal/memory/prepare"
            body = {"version": 1, "query": "我养了一只叫豆包的猫"}
            assert (await client.post(endpoint, json=body)).status == 401
            assert (await client.post(endpoint, headers={"Authorization": "Bearer wrong"}, json=body)).status == 401
            response = await client.post(endpoint, headers={"Authorization": "Bearer " + token}, json=body)
            assert response.status == 200
            written = await response.json()
            assert written["added"] == 1 and "豆包" in written["context"]
            assert set(written["timings_ms"]) == {
                "lock_wait_ms", "command_ms", "observe_ms", "recall_ms",
                "scenario_ms", "persona_ms", "total_ms",
            }
            assert all(value >= 0 for value in written["timings_ms"].values())
            assert written["memory_command"] is None
            assert written["command_reply"] is None
            assert written["round_screen_feedback"] is None
            assert len(written["retrieval_evidence"]) == written["retrieved"]
            assert written["retrieval_evidence"][0]["layer"] == "l1"
            assert "content" not in written["retrieval_evidence"][0]

            completion_endpoint = base + "/api/internal/memory/complete"
            completion = {
                "version": 1,
                "turn_id": written["turn_id"],
                "answer": "好的，我记得你养了一只猫。",
                "retrieved_counts": {"l1": written["retrieved"], "l2": 0, "l3": 0},
                "retrieval_evidence": written["retrieval_evidence"],
            }
            assert (await client.post(completion_endpoint, json=completion)).status == 401
            completed_response = await client.post(
                completion_endpoint,
                headers={"Authorization": "Bearer " + token}, json=completion,
            )
            assert completed_response.status == 200
            completed = await completed_response.json()
            assert completed["created"] is True
            assert completed["playback_acknowledgement"] == "unavailable"
            replay = await client.post(
                completion_endpoint,
                headers={"Authorization": "Bearer " + token}, json=completion,
            )
            assert replay.status == 200 and (await replay.json())["created"] is False
            conflict = await client.post(
                completion_endpoint,
                headers={"Authorization": "Bearer " + token},
                json={**completion, "answer": "不同的回答"},
            )
            assert conflict.status == 409

            feedback_response = await client.post(
                endpoint,
                headers={"Authorization": "Bearer " + token},
                json={"version": 1, "query": "你刚才没想起来我告诉过你的事情"},
            )
            assert feedback_response.status == 200
            feedback_payload = await feedback_response.json()
            assert feedback_payload["round_screen_feedback"]["recorded"] is True
            assert feedback_payload["round_screen_feedback"]["kind"] == "recall_miss"
            assert "尚未自动修改长期记忆" in feedback_payload["command_reply"]

            ambiguous_response = await client.post(
                endpoint,
                headers={"Authorization": "Bearer " + token},
                json={"version": 1, "query": "我刚才说错了"},
            )
            assert ambiguous_response.status == 200
            assert (await ambiguous_response.json())["round_screen_feedback"] is None
            with sqlite3.connect(database) as connection:
                answer_rows = connection.execute(
                    "SELECT role,content FROM conversation_messages WHERE role='assistant'"
                ).fetchall()
                turn_row = connection.execute(
                    "SELECT retrieved_l1_count,retrieved_l2_count,retrieved_l3_count "
                    "FROM round_screen_turns WHERE user_message_id=?",
                    (written["turn_id"],),
                ).fetchone()
                feedback_rows = connection.execute(
                    "SELECT target_user_message_id,event_kind FROM "
                    "round_screen_memory_feedback_events"
                ).fetchall()
            assert answer_rows == [("assistant", completion["answer"])]
            assert turn_row == (written["retrieved"], 0, 0)
            assert feedback_rows == [(written["turn_id"], "recall_miss")]

            console_headers = await login(client, base)
            quality = await client.get(
                base + "/api/chat-memory-feedback?kind=issues&offset=0&limit=25"
            )
            assert quality.status == 200
            quality_payload = await quality.json()
            round_item = next(
                item for item in quality_payload["items"]
                if item["source"] == "round_screen"
            )
            assert round_item["request_id"] == written["turn_id"]
            assert round_item["kind"] == "recall_miss"
            assert round_item["retrieval_evidence"] == written["retrieval_evidence"]
            assert round_item["retrieval_evidence_recorded"] is True
            assert "input" not in round_item and "answer" not in round_item
            detail_response = await client.get(
                base + "/api/round-screen-memory-feedback/"
                + round_item["feedback_event_id"]
            )
            assert detail_response.status == 200
            detail = await detail_response.json()
            assert detail["question"] == body["query"]
            assert detail["answer"] == completion["answer"]
            assert detail["feedback"] == "你刚才没想起来我告诉过你的事情"
            assert detail["retrieval_evidence"][0]["matches_receipt"] is True
            assert "豆包" in detail["retrieval_evidence"][0]["current_content"]

            review_response = await client.post(
                base + "/api/chat-memory-feedback/reviews",
                headers=console_headers,
                json={
                    "source": "round_screen",
                    "target_id": round_item["feedback_event_id"],
                    "feedback_revision": 1,
                    "action": "resolve",
                    "reason_code": "memory_corrected",
                    "expected_review_revision": 0,
                },
            )
            assert review_response.status == 200
            assert (await review_response.json())["state"] == "resolved"
            open_issues = await (await client.get(
                base + "/api/chat-memory-feedback?kind=issues&offset=0&limit=25"
            )).json()
            assert open_issues["review_counts"] == {
                "open": 0, "resolved": 1, "dismissed": 0,
            }
            assert not any(
                item["source"] == "round_screen" for item in open_issues["items"]
            )
            resolved_issues = await (await client.get(
                base + "/api/chat-memory-feedback?kind=resolved&offset=0&limit=25"
            )).json()
            assert resolved_issues["items"][0]["review"]["reason_code"] == "memory_corrected"

            corrected_response = await client.post(
                endpoint,
                headers={"Authorization": "Bearer " + token},
                json={"version": 1, "query": "不是豆包，是年糕"},
            )
            assert corrected_response.status == 200
            corrected = await corrected_response.json()
            assert corrected["memory_command"]["kind"] == "correct"
            assert corrected["memory_command"]["status"] == "applied"
            assert corrected["memory_command"]["writes"][0]["operation"] == "supersede"
            assert corrected["command_reply"] == corrected["memory_command"]["notice"]

            # 网页后端没有另开一套运行时；同一进程立刻读取圆屏刚写入的事实。
            recalled = await asyncio.to_thread(backend.run, "我的猫叫什么", ())
            assert recalled["status"] == "completed" and "年糕" in recalled["answer"]
            assert recalled["retrieved"][0]["source_event_ids"] == (corrected["turn_id"],)

    asyncio.run(run())


def test_explicit_round_screen_follow_up_is_armed_without_web_confirmation(tmp_path):
    """圆屏用户说出的明确请求就是一次授权，固定回执不能再要求访问网页。"""

    from datetime import timedelta

    from longmemory.adapters.llm.fake import FakeAnswerGenerator
    from longmemory.adapters.storage.sqlite_proactive_policy_store import (
        SQLiteProactivePolicyStore,
    )
    from longmemory.core.proactive import OutreachPolicyConfig, ProactivePolicySettings
    from longmemory.entrypoints.api.chat_backend import ChatBackend
    from longmemory.infrastructure.database.connection import open_database
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "round-screen-follow-up.db"
    LongMemoryV1(database).close()
    connection = open_database(database)
    now = datetime.now(UTC)
    SQLiteProactivePolicyStore(connection).save(
        ProactivePolicySettings(
            "user:self",
            OutreachPolicyConfig(
                enabled=True, daily_limit=2,
                minimum_interval=timedelta(0),
            ),
            revision=1, updated_at=now,
        ),
        expected_revision=0,
    )
    connection.close()
    backend = ChatBackend(database, FakeAnswerGenerator())
    token = "f" * 64

    async def run():
        async with console(
            database, chat_backend=backend, memory_runtime_token=token,
        ) as (client, base, _bridge):
            response = await client.post(
                base + "/api/internal/memory/prepare",
                headers={"Authorization": "Bearer " + token},
                json={
                    "version": 1,
                    "query": "我明天下午三点要提交毕业设计汇报，到时候问我汇报进展",
                },
            )
            assert response.status == 200
            payload = await response.json()
            assert payload["follow_up_suggestion"]["status"] == "candidate_armed"
            assert payload["follow_up_suggestion"]["outreach_id"] is not None
            assert "已经按你说的时间安排" in payload["command_reply"]
            assert "控制台" not in payload["command_reply"]

    asyncio.run(run())


def test_memory_mode_http_controls_the_shared_web_and_voice_runtime(tmp_path):
    from longmemory.adapters.llm.fake import FakeAnswerGenerator
    from longmemory.entrypoints.api.chat_backend import ChatBackend
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "memory-mode.db"
    LongMemoryV1(database).close()
    backend = ChatBackend(database, FakeAnswerGenerator())
    token = "b" * 64

    async def run():
        async with console(database, chat_backend=backend, memory_runtime_token=token) as (client, base, _bridge):
            headers = await login(client, base)
            current = await client.get(base + "/api/memory-mode")
            assert current.status == 200
            assert await current.json() == {
                "write_enabled": True,
                "use_enabled": True,
                    "scenario_use_enabled": False,
                    "scenario_available": True,
                    "persona_use_enabled": False,
                    "persona_available": False,
                "persistent": False,
                "l0_archived_when_write_disabled": True,
            }

            # 修改状态属于受保护操作，必须来自本机已建立的控制台会话。
            body = {"write_enabled": False, "use_enabled": False,
                    "scenario_use_enabled": True}
            assert (await client.put(base + "/api/memory-mode", headers={"Origin": base}, json=body)).status == 403
            changed = await client.put(base + "/api/memory-mode", headers=headers, json=body)
            assert changed.status == 200
            assert (await changed.json())["persistent"] is False

            # 同一个 Runtime 立即影响内部小智接口，并清楚回报本轮未写、未召回。
            voice = await client.post(
                base + "/api/internal/memory/prepare",
                headers={"Authorization": "Bearer " + token},
                json={"version": 1, "query": "我喜欢暮雪饮料"},
            )
            assert voice.status == 200
            payload = await voice.json()
            assert payload["memory_write_enabled"] is False
            assert payload["memory_use_enabled"] is False
            assert payload["scenario_use_enabled"] is True
            assert payload["scenario_retrieved"] == []
            assert payload["added"] == 0 and payload["retrieved"] == 0
            assert payload["context"] == ""
            assert payload["retrieval_strategy"] == "disabled_by_user"

            web_result = await asyncio.to_thread(backend.run, "我喜欢青色", ())
            assert web_result["writes"] == []
            assert web_result["memory_context"] == ""

    asyncio.run(run())


def test_round_screen_feedback_storage_failure_does_not_block_voice(tmp_path, monkeypatch):
    from longmemory.adapters.llm.fake import FakeAnswerGenerator
    from longmemory.adapters.storage.sqlite_round_screen_memory_feedback_store import (
        SQLiteRoundScreenMemoryFeedbackStore,
    )
    from longmemory.entrypoints.api.chat_backend import ChatBackend
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "feedback-unavailable.db"
    LongMemoryV1(database).close()
    backend = ChatBackend(database, FakeAnswerGenerator())
    token = "c" * 64

    def unavailable(_self, _event):
        raise sqlite3.OperationalError("synthetic lock")

    monkeypatch.setattr(
        SQLiteRoundScreenMemoryFeedbackStore, "record_if_explicit", unavailable,
    )

    async def run():
        async with console(
            database, chat_backend=backend, memory_runtime_token=token,
        ) as (client, base, _bridge):
            response = await client.post(
                base + "/api/internal/memory/prepare",
                headers={"Authorization": "Bearer " + token},
                json={"version": 1, "query": "你刚才记错了"},
            )
            assert response.status == 200
            payload = await response.json()
            assert payload["round_screen_feedback"] == {
                "kind": "wrong_memory", "recorded": False,
                "target_user_message_id": None, "reason": "storage_unavailable",
            }
            assert payload["command_reply"] is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"write_enabled": True},
        {"write_enabled": True, "use_enabled": True, "extra": False},
        {"write_enabled": 1, "use_enabled": True},
        {"write_enabled": True, "use_enabled": "false"},
        [],
    ],
)
def test_memory_mode_http_rejects_invalid_bodies(tmp_path, body):
    from longmemory.adapters.llm.fake import FakeAnswerGenerator
    from longmemory.entrypoints.api.chat_backend import ChatBackend
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "invalid-memory-mode.db"
    LongMemoryV1(database).close()
    backend = ChatBackend(database, FakeAnswerGenerator())

    async def run():
        async with console(database, chat_backend=backend) as (client, base, _bridge):
            headers = await login(client, base)
            response = await client.put(base + "/api/memory-mode", headers=headers, json=body)
            assert response.status == 400
            status = backend.memory_runtime().status()
            assert status["write_enabled"] is True and status["use_enabled"] is True

    asyncio.run(run())


def test_memory_mode_reports_chat_disabled_instead_of_fake_state():
    async def run():
        async with console() as (client, base, _bridge):
            await login(client, base)
            assert (await client.get(base + "/api/memory-mode")).status == 503

    asyncio.run(run())


def test_explicit_memory_http_reuses_shared_runtime_and_respects_write_pause(tmp_path):
    from longmemory.adapters.llm.fake import FakeAnswerGenerator
    from longmemory.entrypoints.api.chat_backend import ChatBackend
    from longmemory.entrypoints.api.memory_backend import MemoryBackend
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "explicit-memory.db"
    LongMemoryV1(database).close()
    backend = ChatBackend(database, FakeAnswerGenerator())

    async def run():
        async with console(database, chat_backend=backend) as (client, base, _bridge):
            headers = await login(client, base)
            endpoint = base + "/api/memory-commands/include"
            assert (await client.post(endpoint, json={"content": "我的猫叫豆包。"})).status == 403
            invalid = await client.post(endpoint, headers=headers, json={"content": "豆包"})
            assert invalid.status == 400

            saved = await client.post(endpoint, headers=headers, json={"content": "我的猫叫豆包。"})
            payload = await saved.json()
            assert saved.status == 200
            assert payload["kind"] == "include" and payload["status"] == "applied"
            assert payload["writes"][0]["operation"] == "add"
            memory_id = payload["target_memory_ids"][0]
            assert MemoryBackend(database).get(memory_id)["content"] == "用户的猫叫豆包。"
            duplicate = await client.post(endpoint, headers=headers, json={"content": "我的猫叫豆包。"})
            duplicate_payload = await duplicate.json()
            assert duplicate_payload["writes"][0]["operation"] == "noop"
            assert MemoryBackend(database).list_page(query="豆包")["total"] == 1
            assert len(MemoryBackend(database).get(memory_id)["sources"]) == 2

            runtime = backend.memory_runtime()
            runtime.configure(write_enabled=False, use_enabled=True)
            paused = await client.post(endpoint, headers=headers, json={"content": "我喜欢茉莉花茶。"})
            paused_payload = await paused.json()
            assert paused.status == 200 and paused_payload["status"] == "write_paused"
            assert MemoryBackend(database).list_page(query="茉莉花茶")["total"] == 0
            assert MemoryBackend(database).list_sources(query="请记住：我喜欢茉莉花茶")["total"] == 1

    asyncio.run(run())


def test_proactive_policy_http_persists_defaults_and_rejects_stale_page(tmp_path):
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "proactive-policy-http.db"
    LongMemoryV1(database).close()

    async def run():
        async with console(database) as (client, base, _bridge):
            headers = await login(client, base)
            current = await client.get(base + "/api/proactive-policy")
            defaults = await current.json()
            assert current.status == 200
            assert defaults["enabled"] is False and defaults["revision"] == 0
            body = {
                "expected_revision": 0,
                "enabled": True,
                "utc_offset_minutes": 480,
                "allowed_weekdays": [0, 1, 2, 3, 4],
                "allowed_start_minute": 720,
                "allowed_end_minute": 840,
                "daily_limit": 1,
                "minimum_interval_seconds": 21600,
                "maximum_lifetime_seconds": 300,
                "quiet_until": "2026-09-07T08:00:00+08:00",
                "automatic_enabled": True,
                "scheduled_minute": 780,
                "greeting_text": "下午好，今天过得怎么样？",
                "topic_enabled": False,
            }
            assert (await client.put(base + "/api/proactive-policy", json=body)).status == 403
            saved_response = await client.put(
                base + "/api/proactive-policy", headers=headers, json=body,
            )
            saved = await saved_response.json()
            assert saved_response.status == 200
            assert saved["enabled"] is True and saved["revision"] == 1
            assert saved["quiet_until"] == "2026-09-07T08:00:00+08:00"
            stale = await client.put(
                base + "/api/proactive-policy", headers=headers, json=body,
            )
            assert stale.status == 409
            assert (await stale.json())["error"] == "proactive_settings_conflict"

    asyncio.run(run())


def test_proactive_topic_seed_http_is_traceable_preview_only_and_disableable(tmp_path):
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "topic-seed-http.db"
    LongMemoryV1(database).close()
    now = datetime(2026, 9, 7, 6, 0, tzinfo=UTC)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO scenario_memories "
            "(id,subject_id,title,summary,generated_at,valid_from,valid_to,status,"
            "generator_name,generator_version,revision) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("scenario-1", "user:self", "毕业设计", "用户正在准备毕业设计汇报。",
             now.isoformat(), None, None, "active", "test", "1", 2),
        )

    body = {
        "scenario_id": "scenario-1", "expected_scenario_revision": 2,
        "prompt_text": "毕业设计准备得怎么样了？",
        "request_id": "6a4db801-6779-40fc-90b4-aab77f580c82",
    }

    async def run():
        async with console(database, proactive_clock=lambda: now) as (client, base, bridge):
            headers = await login(client, base)
            assert (await client.post(base + "/api/proactive-topic-seeds", json=body)).status == 403
            response = await client.post(
                base + "/api/proactive-topic-seeds", headers=headers, json=body,
            )
            created = await response.json()
            assert response.status == 200
            assert created["usable"] is True
            assert created["source"]["title"] == "毕业设计"
            assert bridge.calls == []
            listed = await (await client.get(base + "/api/proactive-topic-seeds")).json()
            assert listed["items"][0]["prompt_text"] == body["prompt_text"]
            disabled = await client.post(
                base + f"/api/proactive-topic-seeds/{created['id']}/disable",
                headers=headers, json={"expected_revision": 1},
            )
            assert disabled.status == 200
            assert (await disabled.json())["status"] == "disabled"
            assert bridge.calls == []

    asyncio.run(run())


def test_one_shot_schedule_override_can_be_armed_read_and_cancelled(tmp_path):
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "schedule-override-http.db"
    LongMemoryV1(database).close()
    now = datetime(2026, 9, 7, 4, 59, tzinfo=UTC)  # 北京时间周一 12:59。
    policy = {
        "expected_revision": 0, "enabled": True, "utc_offset_minutes": 480,
        "allowed_weekdays": [0, 1, 2, 3, 4, 5, 6],
        "allowed_start_minute": 540, "allowed_end_minute": 1260,
        "daily_limit": 3, "minimum_interval_seconds": 0,
        "maximum_lifetime_seconds": 300, "quiet_until": None,
        "automatic_enabled": True, "scheduled_minute": 780,
        "greeting_text": "下午好。", "topic_enabled": False,
    }

    async def run():
        async with console(database, proactive_clock=lambda: now) as (client, base, _bridge):
            headers = await login(client, base)
            assert (await client.put(
                base + "/api/proactive-policy", headers=headers, json=policy,
            )).status == 200
            body = {"expected_policy_revision": 1, "confirm_action": True}
            assert (await client.post(
                base + "/api/proactive-schedule-override/arm", json=body,
            )).status == 403
            assert (await client.post(
                base + "/api/proactive-schedule-override/arm", headers=headers,
                json={**body, "confirm_action": False},
            )).status == 400
            armed_response = await client.post(
                base + "/api/proactive-schedule-override/arm", headers=headers,
                json=body,
            )
            armed = await armed_response.json()
            assert armed_response.status == 200
            assert armed["status"] == "armed"
            assert armed["local_date"] == "2026-09-07"
            assert armed["scheduled_minute"] == 780
            status = await (
                await client.get(base + "/api/proactive-schedule-status")
            ).json()
            assert status["development_override"]["id"] == armed["id"]
            duplicate = await client.post(
                base + "/api/proactive-schedule-override/arm", headers=headers,
                json=body,
            )
            assert duplicate.status == 409
            cancelled = await client.post(
                base + f"/api/proactive-schedule-override/{armed['id']}/cancel",
                headers=headers, json={"expected_revision": 1},
            )
            assert cancelled.status == 200
            assert (await cancelled.json())["status"] == "cancelled"
            status = await (
                await client.get(base + "/api/proactive-schedule-status")
            ).json()
            assert status["development_override"] is None

    asyncio.run(run())


@pytest.mark.parametrize("change", [
    {"enabled": 1},
    {"allowed_weekdays": [0, 0]},
    {"allowed_start_minute": 720, "allowed_end_minute": 720},
    {"quiet_until": "2026-09-07T08:00:00"},
    {"greeting_text": " 前后空格"},
    {"automatic_enabled": True, "scheduled_minute": 60},
])
def test_proactive_policy_http_rejects_invalid_complete_settings(tmp_path, change):
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "invalid-proactive-policy.db"
    LongMemoryV1(database).close()
    body = {
        "expected_revision": 0, "enabled": False, "utc_offset_minutes": 480,
        "allowed_weekdays": [0, 1, 2, 3, 4, 5, 6],
        "allowed_start_minute": 540, "allowed_end_minute": 1260,
        "daily_limit": 1, "minimum_interval_seconds": 21600,
        "maximum_lifetime_seconds": 300, "quiet_until": None,
        "automatic_enabled": False, "scheduled_minute": 780,
        "greeting_text": "下午好，今天过得怎么样？",
        "topic_enabled": False,
    } | change

    async def run():
        async with console(database) as (client, base, _bridge):
            headers = await login(client, base)
            response = await client.put(
                base + "/api/proactive-policy", headers=headers, json=body,
            )
            assert response.status == 400
            assert (await client.get(base + "/api/proactive-policy")).status == 200

    asyncio.run(run())


def test_manual_proactive_test_is_csrf_protected_and_idempotent(tmp_path):
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "manual-proactive-test.db"
    LongMemoryV1(database).close()
    now = datetime(2026, 9, 7, 4, 0, tzinfo=UTC)  # 北京时间周一 12:00。
    policy = {
        "expected_revision": 0, "enabled": True, "utc_offset_minutes": 480,
        "allowed_weekdays": [0, 1, 2, 3, 4, 5, 6],
        "allowed_start_minute": 540, "allowed_end_minute": 1260,
        "daily_limit": 3, "minimum_interval_seconds": 0,
        "maximum_lifetime_seconds": 300, "quiet_until": None,
        "automatic_enabled": False, "scheduled_minute": 780,
        "greeting_text": "下午好，今天过得怎么样？",
        "topic_enabled": False,
    }
    body = {
        "text": "这是一条合成主动问候。",
        "request_id": "6a4db801-6779-40fc-90b4-aab77f580c82",
        "expected_policy_revision": 1,
    }

    async def run():
        async with console(database, proactive_clock=lambda: now) as (client, base, bridge):
            headers = await login(client, base)
            assert (await client.put(
                base + "/api/proactive-policy", headers=headers, json=policy,
            )).status == 200

            rejected = await client.post(base + "/api/proactive-outreach/test", json=body)
            assert rejected.status == 403 and bridge.calls == []
            invalid = await client.post(
                base + "/api/proactive-outreach/test", headers=headers,
                json={**body, "text": " 前后空格不会被静默修改"},
            )
            assert invalid.status == 400 and bridge.calls == []

            first = await client.post(
                base + "/api/proactive-outreach/test", headers=headers, json=body,
            )
            first_data = await first.json()
            assert first.status == 200
            assert first_data["state"] == "queued"
            assert first_data["replayed"] is False
            assert first_data["policy_reason"] == "ready"
            assert first_data["delivery_reason"] == "xiaozhi_queue_accepted"
            assert len(bridge.calls) == 1 and bridge.calls[0][0] == "announce"

            history = await client.get(base + "/api/proactive-outreach?limit=10")
            history_data = await history.json()
            assert history.status == 200
            assert history_data["items"] == [{
                "outreach_id": first_data["outreach_id"],
                "trigger": "manual_test",
                "content": body["text"],
                "created_at": now.isoformat(),
                "expires_at": (now.replace(minute=5)).isoformat(),
                "state": "queued",
                "revision": 2,
                "reason": "ready",
                "event_count": 2,
                "failure_reason": None,
                    "topic_seed_id": None,
                    "topic_seed_revision": None,
                    "follow_up_source": None,
                    "strategy_source": None,
                "outcome_observation_state": "not_applicable",
                "delivery_evidence_level": "server_queued",
                "subsequent_user_message": None,
                "explicit_feedback": None,
            }]
            assert (await client.get(
                base + "/api/proactive-outreach?limit=01"
            )).status == 400

            repeated = await client.post(
                base + "/api/proactive-outreach/test", headers=headers, json=body,
            )
            repeated_data = await repeated.json()
            assert repeated.status == 200
            assert repeated_data["outreach_id"] == first_data["outreach_id"]
            assert repeated_data["replayed"] is True
            assert len(bridge.calls) == 1

            confirm_path = (
                base + "/api/proactive-outreach/" + first_data["outreach_id"]
                + "/confirm-played"
            )
            assert (await client.post(
                confirm_path, json={"expected_revision": 2},
            )).status == 403
            confirmed = await client.post(
                confirm_path, headers=headers, json={"expected_revision": 2},
            )
            confirmed_data = await confirmed.json()
            assert confirmed.status == 200
            assert confirmed_data["state"] == "played"
            assert confirmed_data["revision"] == 3
            assert confirmed_data["replayed"] is False
            replayed_confirmation = await client.post(
                confirm_path, headers=headers, json={"expected_revision": 2},
            )
            assert (await replayed_confirmation.json())["replayed"] is True
            assert len(bridge.calls) == 1

            schedule_status = await (
                await client.get(base + "/api/proactive-schedule-status")
            ).json()
            assert schedule_status["awaiting_user_response"] is True
            assert schedule_status["user_chatted_today"] is False

            # 显式诊断不是后台追问：上一条仍在等待用户回应时也可再次验证，
            # 但仍会占用每日次数并保留完整账本。
            second = await client.post(
                base + "/api/proactive-outreach/test", headers=headers,
                json={**body, "request_id": "540780a2-48f3-4634-86c5-d62828e493f4"},
            )
            assert (await second.json())["state"] == "queued"
            assert len(bridge.calls) == 2

            stale = await client.post(
                base + "/api/proactive-outreach/test", headers=headers,
                json={**body, "request_id": "ac1da8a5-2ff6-4136-80ff-c52b0c98ab2f",
                      "expected_policy_revision": 0},
            )
            assert stale.status == 409
            assert (await stale.json())["error"] == "proactive_settings_conflict"

        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT count(*) FROM proactive_outreach").fetchone()[0] == 2
            assert connection.execute(
                "SELECT count(*) FROM proactive_outreach_events"
            ).fetchone()[0] == 5
            assert connection.execute(
                "SELECT count(*) FROM proactive_outreach_events "
                "WHERE new_state='queued' AND reason_code='ready' "
                "AND evidence_kind='server_queue'"
            ).fetchone()[0] == 2
            assert connection.execute(
                "SELECT count(*) FROM proactive_outreach_events "
                "WHERE new_state='played' AND evidence_kind='user_observed'"
            ).fetchone()[0] == 1

    asyncio.run(run())


def test_manual_proactive_test_records_stable_delivery_failure(tmp_path):
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "manual-proactive-failure.db"
    LongMemoryV1(database).close()
    now = datetime(2026, 9, 7, 4, 0, tzinfo=UTC)

    async def run():
        async with console(database, proactive_clock=lambda: now) as (client, base, bridge):
            headers = await login(client, base)
            policy = {
                "expected_revision": 0, "enabled": True, "utc_offset_minutes": 480,
                "allowed_weekdays": [0, 1, 2, 3, 4, 5, 6],
                "allowed_start_minute": 540, "allowed_end_minute": 1260,
                "daily_limit": 1, "minimum_interval_seconds": 21600,
                "maximum_lifetime_seconds": 300, "quiet_until": None,
                "automatic_enabled": False, "scheduled_minute": 780,
                "greeting_text": "下午好，今天过得怎么样？",
                "topic_enabled": False,
            }
            assert (await client.put(
                base + "/api/proactive-policy", headers=headers, json=policy,
            )).status == 200
            bridge.error = BridgeError("announcement_enqueue_failed")
            response = await client.post(
                base + "/api/proactive-outreach/test", headers=headers,
                json={"text": "这是一条失败路径测试。",
                      "request_id": "60536c47-ad24-401f-9b89-d72349cc0aa8",
                      "expected_policy_revision": 1},
            )
            result = await response.json()
            assert response.status == 200
            assert result["state"] == "failed"
            assert result["delivery_reason"] == "announcement_enqueue_failed"
            assert result["device"]["ready"] is False
            history = await client.get(base + "/api/proactive-outreach?limit=1")
            failed_item = (await history.json())["items"][0]
            invalid_confirmation = await client.post(
                base + "/api/proactive-outreach/" + failed_item["outreach_id"]
                + "/confirm-played",
                headers=headers,
                json={"expected_revision": failed_item["revision"]},
            )
            assert invalid_confirmation.status == 409
            assert (await invalid_confirmation.json())["error"] == (
                "proactive_playback_confirmation_invalid_state"
            )

    asyncio.run(run())


def test_scenario_http_requires_csrf_and_explicit_capability(tmp_path):
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "scenario-http.db"
    LongMemoryV1(database).close()
    with sqlite3.connect(database) as connection:
        for suffix, content in (("a", "用户周五答辩。"), ("b", "用户正在修改 PPT。")):
            connection.execute(
                "INSERT INTO conversation_messages VALUES (?,?,?,?)",
                (f"l0-{suffix}", "user", content, "2026-09-06T10:00:00+00:00"),
            )
            connection.execute(
                "INSERT INTO atomic_memories VALUES (?,?,?,?,NULL,NULL,NULL,NULL)",
                (f"l1-{suffix}", "user:self", content, "2026-09-06T10:00:00+00:00"),
            )
            connection.execute(
                "INSERT INTO memory_evidence VALUES (?,?,?,?)",
                (f"l1-{suffix}", f"l0-{suffix}", "user_stated", "2026-09-06T10:00:00+00:00"),
            )

    class ProposalProducer:
        calls = 0

        def propose(self, *, sources):
            self.calls += 1
            return ('{"schema_version":1,"candidate":{"title":"准备答辩",'
                    '"summary":"用户最近正在准备答辩并修改 PPT。",'
                    '"source_memory_ids":["l1-a","l1-b"]}}')

    producer = ProposalProducer()

    async def run():
        async with console(database, allow_scenario_management=True,
                           scenario_producer=producer, scenario_model="synthetic-model") as (client, base, _bridge):
            headers = await login(client, base)
            proposal_body = {"source_memory_ids": ["l1-a", "l1-b"],
                             "confirm_model_call": True}
            assert (await client.post(base + "/api/scenario-proposals", json=proposal_body)).status == 403
            proposal_response = await client.post(
                base + "/api/scenario-proposals", headers=headers, json=proposal_body
            )
            proposal = await proposal_response.json()
            assert proposal_response.status == 200
            assert proposal["persisted"] is False and proposal["model"] == "synthetic-model"
            assert producer.calls == 1
            assert (await (await client.get(base + "/api/scenarios?state=all")).json())["total"] == 0
            inbox_before = await (
                await client.get(base + "/api/scenario-source-inbox")
            ).json()
            assert inbox_before["total"] == 2
            assert inbox_before["selection_is_semantic"] is False
            body = {"title": "准备答辩", "summary": "用户最近正在准备答辩。",
                    "source_memory_ids": ["l1-a", "l1-b"], "creation_kind": "manual",
                    "confirm_candidate": True,
                    "valid_from": "2026-09-06T08:00:00+00:00",
                    "valid_to": "2026-09-13T08:00:00+00:00"}
            assert (await client.post(base + "/api/scenarios", json=body)).status == 403
            created_response = await client.post(base + "/api/scenarios", headers=headers, json=body)
            assert created_response.status == 200
            created = await created_response.json()
            assert (await (
                await client.get(base + "/api/scenario-source-inbox")
            ).json())["total"] == 0
            listed = await (await client.get(base + "/api/scenarios?state=candidate")).json()
            assert listed["total"] == 1
            detail = await (await client.get(base + "/api/scenarios/" + created["id"])).json()
            assert detail["valid_from"] == "2026-09-06T08:00:00+00:00"
            assert detail["valid_to"] == "2026-09-13T08:00:00+00:00"
            assert {source["l0_sources"][0]["content"] for source in detail["sources"]} == {
                "用户周五答辩。", "用户正在修改 PPT。",
            }
            reviewed = await client.post(
                base + "/api/scenarios/" + created["id"] + "/reviews",
                headers=headers,
                json={"decision": "accepted", "expected_revision": detail["revision"],
                      "confirm_review": True},
            )
            assert reviewed.status == 200 and (await reviewed.json())["status"] == "active"
            lifecycle_url = base + "/api/scenarios/" + created["id"] + "/lifecycle"
            lifecycle_body = {
                "action": "manual_end", "expected_revision": 2, "confirm_action": True,
            }
            assert (await client.post(lifecycle_url, json=lifecycle_body)).status == 403
            ended_response = await client.post(
                lifecycle_url, headers=headers, json=lifecycle_body,
            )
            ended = await ended_response.json()
            assert ended_response.status == 200
            assert ended["status"] == "stale" and ended["revision"] == 3
            ended_detail = await (
                await client.get(base + "/api/scenarios/" + created["id"])
            ).json()
            assert ended_detail["lifecycle_events"][0]["action"] == "manual_end"
            assert len(ended_detail["sources"]) == 2

    asyncio.run(run())


def test_persona_http_requires_csrf_and_explicit_capability(tmp_path):
    """L3 网页写入必须同时经过显式能力开关、同源会话和人工确认。"""

    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "persona-http.db"
    LongMemoryV1(database).close()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO conversation_messages VALUES (?,?,?,?)",
            ("l0-tea", "user", "我平时喜欢喝乌龙茶。", "2026-09-06T10:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO atomic_memories VALUES (?,?,?,?,NULL,NULL,NULL,NULL)",
            ("l1-tea", "user:self", "此人平时喜欢喝乌龙茶。", "2026-09-06T10:00:01+00:00"),
        )
        connection.execute(
            "INSERT INTO memory_evidence VALUES (?,?,?,?)",
            ("l1-tea", "l0-tea", "user_stated", "2026-09-06T10:00:01+00:00"),
        )

    body = {
        "kind": "preference",
        "basis": "user_declared",
        "label": "饮品偏好",
        "statement": "用户平时喜欢喝乌龙茶。",
        "sources": [{"layer": "l1", "id": "l1-tea"}],
        "valid_from": None,
        "valid_to": None,
        "confirm_candidate": True,
    }

    class ProposalProducer:
        calls = 0

        def propose(self, *, basis, sources):
            self.calls += 1
            return ('{"schema_version":1,"candidate":{"kind":"preference",'
                    '"label":"饮品偏好","statement":"用户平时喜欢喝乌龙茶。",'
                    '"sources":[{"layer":"l1","id":"l1-tea"}]}}')

        def propose_consolidation(self, *, basis, sources, active_personas):
            self.calls += 1
            assert active_personas == ()
            return ('{"schema_version":1,"operation":"ADD","candidate":{'
                    '"kind":"preference","label":"饮品偏好",'
                    '"statement":"用户平时喜欢喝乌龙茶。",'
                    '"sources":[{"layer":"l1","id":"l1-tea"}]},"replaces":[]}')

    producer = ProposalProducer()

    async def run():
        # 未开放 L3 管理时，即使请求合法也只能读取，不能落库。
        async with console(database) as (client, base, _bridge):
            headers = await login(client, base)
            denied = await client.post(base + "/api/personas", headers=headers, json=body)
            assert denied.status == 403

        async with console(
            database, allow_persona_management=True,
            persona_producer=producer, persona_model="synthetic-model",
        ) as (client, base, _bridge):
            headers = await login(client, base)
            config = await (await client.get(base + "/api/memory-config")).json()
            assert config["persona_model_preview_available"] is True
            assert config["persona_model"] == "synthetic-model"
            options = await (await client.get(base + "/api/persona-source-options")).json()
            assert options["l1"][0]["id"] == "l1-tea"
            assert options["selection_is_semantic"] is False

            proposal_body = {
                "basis": "user_declared",
                "sources": [{"layer": "l1", "id": "l1-tea"}],
                "confirm_model_call": True,
            }
            assert (
                await client.post(base + "/api/persona-proposals", json=proposal_body)
            ).status == 403
            proposal_response = await client.post(
                base + "/api/persona-proposals", headers=headers, json=proposal_body,
            )
            proposal = await proposal_response.json()
            assert proposal_response.status == 200
            assert proposal["persisted"] is False
            assert proposal["sources"] == [{"layer": "l1", "id": "l1-tea"}]
            assert producer.calls == 1

            consolidation_response = await client.post(
                base + "/api/persona-consolidation-proposals",
                headers=headers, json=proposal_body,
            )
            consolidation = await consolidation_response.json()
            assert consolidation_response.status == 200
            assert consolidation["operation"] == "ADD"
            assert consolidation["candidate"]["sources"] == [
                {"layer": "l1", "id": "l1-tea"}
            ]
            assert consolidation["replaces"] == []
            assert consolidation["persisted"] is False
            assert producer.calls == 2

            assert (await client.post(base + "/api/personas", json=body)).status == 403
            created_response = await client.post(
                base + "/api/personas", headers=headers,
                json=body | {"creation_kind": "model_assisted"},
            )
            created = await created_response.json()
            assert created_response.status == 200 and created["status"] == "candidate"

            detail = await (
                await client.get(base + "/api/personas/" + created["id"])
            ).json()
            assert detail["basis"] == "user_declared"
            assert detail["generator_name"] == "model_assisted_console"
            assert detail["audit"] == {
                "source_count": 1,
                "source_message_count": 1,
                "observation_day_count": 1,
            }
            assert detail["sources"][0]["l0_sources"][0]["content"] == "我平时喜欢喝乌龙茶。"

            review_body = {
                "decision": "accepted",
                "expected_revision": detail["revision"],
                "confirm_review": True,
            }
            assert (
                await client.post(
                    base + f"/api/personas/{created['id']}/reviews", json=review_body,
                )
            ).status == 403
            reviewed = await client.post(
                base + f"/api/personas/{created['id']}/reviews",
                headers=headers,
                json=review_body,
            )
            assert reviewed.status == 200
            assert (await reviewed.json())["status"] == "active"

            profile_response = await client.get(base + "/api/persona-profile")
            profile = await profile_response.json()
            assert profile_response.status == 200
            assert profile["representation"] == "aggregated_active_assertions_v1"
            assert profile["active_assertion_count"] == 1
            assert profile["status_counts"]["active"] == 1
            assert profile["sections"][0]["kind"] == "preference"
            assert profile["sections"][0]["items"][0]["id"] == created["id"]

            replacement_response = await client.post(
                base + "/api/personas", headers=headers,
                json=body | {
                    "label": "更新后的饮品偏好",
                    "statement": "用户现在偏好清淡乌龙茶。",
                    "replaces": [created["id"]],
                },
            )
            replacement = await replacement_response.json()
            assert replacement_response.status == 200
            replacement_detail = await (
                await client.get(base + "/api/personas/" + replacement["id"])
            ).json()
            assert replacement_detail["replaces"][0]["replaced_persona_id"] == created["id"]
            assert replacement_detail["replaces"][0]["applied_at"] is None

            accepted_replacement = await client.post(
                base + f"/api/personas/{replacement['id']}/reviews", headers=headers,
                json={"decision": "accepted", "expected_revision": 1, "confirm_review": True},
            )
            assert accepted_replacement.status == 200
            old_detail = await (
                await client.get(base + "/api/personas/" + created["id"])
            ).json()
            assert old_detail["status"] == "stale"
            assert old_detail["replaced_by"][0]["candidate_persona_id"] == replacement["id"]
            updated_profile = await (
                await client.get(base + "/api/persona-profile")
            ).json()
            assert updated_profile["active_assertion_count"] == 1
            assert updated_profile["sections"][0]["items"][0]["id"] == replacement["id"]

    asyncio.run(run())
