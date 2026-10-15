"""合成素材及显式只读固定资源输入；不接触日用配置、服务或设备。"""
import asyncio
import base64
import hashlib
import os
from pathlib import Path
import socket

import pytest
from aiohttp import ClientSession, web

from longmemory.entrypoints.api import otto_preview as otto
from longmemory.entrypoints.api.security import COOKIE, Sessions, security_middleware


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    data = bytearray(base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"))
    data[6:10] = b"\xf0\x00\xf0\x00"
    data = bytes(data)
    records = {}
    for relative, payload in (("LICENSE", b"synthetic license"), ("gifs/neutral.gif", data)):
        path = tmp_path / relative
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(payload)
        records[relative] = {"bytes": len(payload), "git_blob_sha1": hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()}
    monkeypatch.setattr(otto, "RECORDS", records)
    monkeypatch.setattr(otto, "NAMES", ("neutral",))
    return tmp_path, data


def test_structure_and_corruption(synthetic):
    root, data = synthetic
    preview = otto.OttoPreview(root)
    assert preview.read("neutral") == data
    assert otto.first_frame(data) == preview.read("neutral", True)
    assert preview.inventory()["valid_count"] == 1
    for cut in (0, 10, len(data)-1):
        with pytest.raises(ValueError):
            otto.first_frame(data[:cut])
    path = root / "gifs/neutral.gif"
    path.write_bytes(data.replace(b"GIF89a", b"GIF87a"))
    assert preview.inventory()["valid_count"] == 0
    with pytest.raises(ValueError):
        preview.read("neutral")
    with pytest.raises(ValueError):
        preview.read("../../LICENSE")


def test_missing_oversize_and_license(synthetic):
    root, data = synthetic
    preview = otto.OttoPreview(root)
    (root / "gifs/neutral.gif").write_bytes(data + b"x")
    assert preview.inventory()["valid_count"] == 0
    (root / "gifs/neutral.gif").write_bytes(data)
    (root / "LICENSE").unlink()
    assert preview.inventory()["valid_count"] == 0


def test_link_escape_rejected(synthetic, tmp_path):
    root, data = synthetic
    # 链接位置和目标都在本测试目录内，目标处于指定资源根之外。
    resource_root = root / "resources"
    (resource_root / "gifs").mkdir(parents=True)
    (resource_root / "LICENSE").write_bytes(b"synthetic license")
    try:
        (resource_root / "gifs/neutral.gif").symlink_to(root / "gifs/neutral.gif")
    except OSError:
        pytest.skip("当前 Windows 会话未允许创建测试符号链接")
    assert otto.OttoPreview(resource_root).inventory()["valid_count"] == 0


def test_authenticated_http_allowlist(synthetic):
    async def run():
        root, data = synthetic
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sessions = Sessions()
        session, csrf = sessions.create()
        app = web.Application(middlewares=[security_middleware(f"127.0.0.1:{port}", sessions)])
        otto.register_otto_preview(app, root)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        try:
            async with ClientSession(trust_env=False) as client:
                base = f"http://127.0.0.1:{port}"
                assert (await client.get(base + "/api/otto-preview")).status == 401
                headers = {"Cookie": f"{COOKIE}={session}"}
                response = await client.get(base + "/api/otto-preview", headers=headers)
                assert response.status == 200
                assert (await response.json())["valid_count"] == 1
                assert str(root) not in await response.text()
                policy = response.headers["Content-Security-Policy"]
                assert "img-src 'self'" in policy and "unsafe-inline" not in policy and "blob:" not in policy
                for kind in ("loop", "still"):
                    response = await client.get(base + f"/api/otto-preview/neutral/{kind}.gif", headers=headers)
                    assert response.status == 200 and response.content_type == "image/gif"
                    assert await response.read() == (data if kind == "loop" else otto.first_frame(data))
                for path in ("unknown/loop.gif", "LICENSE/loop.gif", "neutral/other.gif", "neutral/loop.gif/extra", "%2e%2e/LICENSE/loop.gif"):
                    response = await client.get(base + "/api/otto-preview/" + path, headers=headers)
                    assert response.status == 404
                    assert str(root) not in await response.text()
                for extra in ({"Origin":"https://example.invalid"}, {"Host":"attacker.invalid"}, {"Sec-Fetch-Site":"cross-site"}):
                    assert (await client.get(base + "/api/otto-preview", headers={**headers,**extra})).status == 403
                assert (await client.post(base + "/api/otto-preview", headers={**headers,"Origin":base})).status == 403
                assert (await client.post(base + "/api/otto-preview", headers={**headers,"Origin":base,"X-Console-CSRF":csrf})).status == 405
                (root / "gifs/neutral.gif").write_bytes(b"broken")
                assert (await client.get(base + "/api/otto-preview/neutral/loop.gif", headers=headers)).status == 404
        finally:
            await runner.cleanup()
    asyncio.run(run())


def test_explicit_fixed_input():
    value = os.environ.get("OTTO_TEST_ASSET_ROOT")
    if not value:
        pytest.skip("真实资源只在显式绑定允许的固定目录时检查")
    preview = otto.OttoPreview(Path(value))
    result = preview.inventory()
    assert result["commit"] == otto.COMMIT and result["valid_count"] == 21
    assert sum(item["bytes"] for item in result["items"]) == 1609459
    for name in otto.NAMES:
        still = preview.read(name, True)
        assert still.startswith(b"GIF") and still.endswith(b";")
        assert len(still) <= len(preview.read(name))
