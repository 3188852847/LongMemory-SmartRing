from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import socket

import pytest

aiohttp = pytest.importorskip("aiohttp", reason="局域网投递测试需要 console extra")
from aiohttp import web

from longmemory.infrastructure.media.round_wallpaper_delivery import (
    DeliveryError,
    RoundWallpaperDeliveryRegistry,
    create_round_wallpaper_delivery_app,
)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 10, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def prepared(tmp_path: Path, clock: Clock):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "preview.gif"
    path.write_bytes(b"GIF89a" + bytes(range(32)))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    registry = RoundWallpaperDeliveryRegistry(clock=clock)
    ticket = registry.issue(
        item_id="wallpaper-" + "a" * 20,
        path=path,
        expected_sha256=digest,
        expected_size=path.stat().st_size,
    )
    return registry, ticket, path


def test_ticket_is_short_lived_single_use_and_rechecks_file(tmp_path):
    clock = Clock()
    registry, ticket, path = prepared(tmp_path, clock)
    assert registry.take(ticket.token).item_id == "wallpaper-" + "a" * 20
    with pytest.raises(DeliveryError, match="delivery_ticket_not_found"):
        registry.take(ticket.token)

    registry, ticket, path = prepared(tmp_path / "changed", clock)
    path.write_bytes(b"GIF89a-replaced")
    with pytest.raises(DeliveryError, match="wallpaper_delivery_integrity_failed"):
        registry.take(ticket.token)

    registry, ticket, _ = prepared(tmp_path / "expired", clock)
    clock.now += timedelta(seconds=181)
    with pytest.raises(DeliveryError, match="delivery_ticket_not_found"):
        registry.take(ticket.token)


@pytest.mark.parametrize("change,code", [
    ({"item_id": "../wallpaper"}, "invalid_wallpaper_id"),
    ({"expected_sha256": "not-a-hash"}, "invalid_wallpaper_sha256"),
    ({"expected_size": 0}, "invalid_wallpaper_size"),
    ({"ttl_seconds": 301}, "invalid_delivery_ttl"),
])
def test_ticket_rejects_open_or_invalid_metadata(tmp_path, change, code):
    path = tmp_path / "preview.gif"
    path.write_bytes(b"GIF89a")
    values = {
        "item_id": "wallpaper-" + "a" * 20,
        "path": path,
        "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "expected_size": path.stat().st_size,
        "ttl_seconds": 180,
    }
    values.update(change)
    with pytest.raises(DeliveryError, match=code):
        RoundWallpaperDeliveryRegistry().issue(**values)


def test_delivery_http_has_one_route_no_browser_access_and_no_second_read(tmp_path):
    async def run():
        clock = Clock()
        registry, ticket, path = prepared(tmp_path, clock)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        app = create_round_wallpaper_delivery_app(
            registry, listen_address="127.0.0.1", port=port,
        )
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        try:
            url = f"http://127.0.0.1:{port}/wallpaper/{ticket.token}"
            async with aiohttp.ClientSession(trust_env=False) as client:
                rejected = await client.get(url, headers={"Origin": "http://attacker.invalid"})
                assert rejected.status == 403
                accepted = await client.get(url)
                assert accepted.status == 200
                assert accepted.content_type == "image/gif"
                assert accepted.headers["Cache-Control"] == "no-store"
                assert accepted.headers["X-Wallpaper-Id"] == ticket.item_id
                assert await accepted.read() == path.read_bytes()
                repeated = await client.get(url)
                assert repeated.status == 404
                assert (await repeated.json())["error"] == "delivery_ticket_not_found"
                assert (await client.get(f"http://127.0.0.1:{port}/manifest.json")).status == 404
        finally:
            await runner.cleanup()

    import asyncio
    asyncio.run(run())
