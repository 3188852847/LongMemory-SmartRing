"""固定 Otto 资源的只读预览；不提供设备控制或任意路径访问。"""

import asyncio
import hashlib
import json
from pathlib import Path
import struct

from aiohttp import web

ROOT = Path(__file__).resolve().parents[4]
COMMIT = "970cf66906d7c30059faa2704e7002f06b8c3619"
UPSTREAM = json.loads((ROOT / "firmware/smartring_plus/previews/otto/upstream.json").read_text(encoding="utf-8"))
assert UPSTREAM["commit"] == COMMIT
RECORDS = {item["path"]: item for item in UPSTREAM["files"]}
NAMES = tuple(item[5:-4] for item in RECORDS if item.startswith("gifs/") and item.endswith(".gif"))
assert len(NAMES) == 21 and all(name.isalpha() for name in NAMES)


def verified_bytes(root: Path, relative: str) -> bytes:
    record = RECORDS[relative]
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or path.stat().st_size != record["bytes"]:
        raise ValueError("unverified resource")
    # 大小先校验，读取也有界；不缓存可在启动后变化的磁盘内容。
    with path.open("rb") as stream:
        data = stream.read(record["bytes"] + 1)
    digest = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    if len(data) != record["bytes"] or digest != record["git_blob_sha1"]:
        raise ValueError("unverified resource")
    return data


def first_frame(data: bytes) -> bytes:
    """保留原调色板与首帧压缩像素，输出无循环扩展的单帧 GIF。"""
    if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a") or struct.unpack_from("<HH", data, 6) != (240, 240):
        raise ValueError("invalid GIF")
    pos = 13 + (3 * (2 << (data[10] & 7)) if data[10] & 128 else 0)
    header, control, image = data[:pos], b"", b""
    frames = 0

    def blocks(offset):
        while offset < len(data):
            size = data[offset]
            offset += 1
            if not size:
                return offset
            offset += size
        raise ValueError("truncated GIF")

    while pos < len(data):
        start, marker = pos, data[pos]
        pos += 1
        if marker == 0x3B:
            if not frames or pos != len(data):
                raise ValueError("invalid GIF trailer")
            return header + control + image + b";"
        if marker == 0x21:
            if pos >= len(data):
                raise ValueError("truncated GIF")
            label = data[pos]
            pos = blocks(pos + 1)
            if label == 0xF9 and not frames:
                control = data[start:pos]
        elif marker == 0x2C:
            if pos + 9 > len(data):
                raise ValueError("truncated GIF")
            packed = data[pos + 8]
            pos = blocks(pos + 10 + (3 * (2 << (packed & 7)) if packed & 128 else 0))
            if not frames:
                image = data[start:pos]
            frames += 1
        else:
            raise ValueError("invalid GIF marker")
    raise ValueError("missing GIF trailer")


class OttoPreview:
    def __init__(self, root: Path):
        self.root = root

    def read(self, name: str, still=False) -> bytes:
        if name not in NAMES:
            raise ValueError("unknown expression")
        verified_bytes(self.root, "LICENSE")
        data = verified_bytes(self.root, f"gifs/{name}.gif")
        frame = first_frame(data)
        return frame if still else data

    def inventory(self):
        items = []
        for name in NAMES:
            item = {"name": name, "bytes": RECORDS[f"gifs/{name}.gif"]["bytes"], "valid": False}
            try:
                data = self.read(name)
                item.update(valid=True, sha256=hashlib.sha256(data).hexdigest())
            except (OSError, ValueError):
                pass
            items.append(item)
        return {"commit": COMMIT, "version": UPSTREAM["version"], "license": UPSTREAM["license"],
                "valid_count": sum(item["valid"] for item in items), "items": items}


def register_otto_preview(app, root=None):
    preview = OttoPreview(Path(root) if root is not None else ROOT / "local/runtime/otto-emoji" / COMMIT)

    async def manifest(request):
        return web.json_response(await asyncio.to_thread(preview.inventory))

    async def asset(request):
        name = request.match_info["name"]
        try:
            data = await asyncio.to_thread(preview.read, name, request.match_info["kind"] == "still")
        except (OSError, ValueError):
            return web.json_response({"error": "otto_resource_unavailable"}, status=404)
        return web.Response(body=data, content_type="image/gif")

    # /api/ 前缀沿用控制台 Cookie、Host、Origin 与 CSP；不另挂静态目录。
    app.router.add_get("/api/otto-preview", manifest, allow_head=False)
    app.router.add_get(r"/api/otto-preview/{name:[a-z]+}/{kind:loop|still}.gif", asset, allow_head=False)
