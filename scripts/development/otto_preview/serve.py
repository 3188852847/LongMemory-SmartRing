"""独立只读 Otto 预览；标准库、回环随机端口、固定文件白名单。"""
from __future__ import annotations

import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import struct
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "firmware/smartring_plus/previews/otto"
UPSTREAM = json.loads((WEB / "upstream.json").read_text(encoding="utf-8"))
NAMES = "neutral happy laughing funny sad angry crying loving embarrassed surprised shocked thinking winking cool relaxed delicious kissy confident sleepy silly confused".split()
RECORDS = {f["path"]: f for f in UPSTREAM["files"]}


def gif_info(data: bytes) -> dict:
    """读取结构/帧延时，不解码像素；像素解码成功由浏览器另验。"""
    if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        raise ValueError("invalid GIF header")
    width, height = struct.unpack_from("<HH", data, 6)
    if (width, height) != (240, 240):
        raise ValueError("expected 240x240")
    pos = 13 + (3 * (2 << (data[10] & 7)) if data[10] & 128 else 0)
    delays, delay = [], 0

    def subblocks(offset):
        while True:
            if offset >= len(data):
                raise ValueError("truncated GIF blocks")
            size = data[offset]
            offset += 1
            if not size:
                return offset
            offset += size
            if offset > len(data):
                raise ValueError("truncated GIF block")

    while pos < len(data):
        marker = data[pos]
        pos += 1
        if marker == 0x3B:
            if not delays:
                raise ValueError("no image frames")
            return {"width": width, "height": height, "frames": len(delays),
                    "duration_ms": sum(delays), "delays_ms": sorted(set(delays))}
        if marker == 0x21:
            if pos >= len(data):
                raise ValueError("truncated extension")
            label = data[pos]
            pos += 1
            if label == 0xF9:
                if pos + 6 > len(data) or data[pos] != 4 or data[pos + 5] != 0:
                    raise ValueError("invalid frame control")
                delay = struct.unpack_from("<H", data, pos + 2)[0] * 10
            pos = subblocks(pos)
        elif marker == 0x2C:
            if pos + 9 > len(data):
                raise ValueError("truncated image descriptor")
            packed = data[pos + 8]
            pos += 9 + (3 * (2 << (packed & 7)) if packed & 128 else 0)
            pos += 1  # LZW code size; actual decode remains browser/device responsibility.
            pos = subblocks(pos)
            delays.append(delay)
            delay = 0
        else:
            raise ValueError("unexpected GIF marker")
    raise ValueError("missing GIF trailer")


def asset_bytes(assets: Path, name: str) -> bytes:
    if name not in NAMES:
        raise ValueError("unknown expression")
    path = assets / "gifs" / f"{name}.gif"
    # Resolve before reading: symlinks must never escape the explicit asset root.
    if not path.resolve().is_relative_to(assets.resolve()):
        raise ValueError("asset escapes resource directory")
    data = path.read_bytes()
    record = RECORDS[f"gifs/{name}.gif"]
    blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    if len(data) != record["bytes"] or blob != record["git_blob_sha1"]:
        raise ValueError("fixed upstream fingerprint mismatch")
    return data


def inventory(assets: Path) -> dict:
    items = []
    for name in NAMES:
        item = {"name": name, "expected_bytes": RECORDS[f"gifs/{name}.gif"]["bytes"]}
        try:
            data = asset_bytes(assets, name)
            item.update(gif_info(data), valid=True, sha256=hashlib.sha256(data).hexdigest())
        except (OSError, ValueError) as exc:
            item.update(valid=False, reason="未下载" if isinstance(exc, FileNotFoundError) else str(exc))
        items.append(item)
    return {"commit": UPSTREAM["commit"], "version": UPSTREAM["version"],
            "license": UPSTREAM["license"], "total_bytes": sum(i["expected_bytes"] for i in items),
            "valid_count": sum(i["valid"] for i in items), "items": items}


def make_handler(assets: Path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = urlsplit(self.path).path
            try:
                if route == "/api/assets":
                    body, mime = json.dumps(inventory(assets), ensure_ascii=False).encode(), "application/json"
                elif route in ("/", "/index.html", "/app.js", "/state.js", "/lifecycle.js", "/style.css", "/upstream.json"):
                    name = "index.html" if route == "/" else route[1:]
                    body = (WEB / name).read_bytes()
                    mime = {"html": "text/html", "js": "text/javascript", "css": "text/css", "json": "application/json"}[name.split(".")[-1]]
                elif route.startswith("/gifs/") and route.endswith(".gif"):
                    body, mime = asset_bytes(assets, route[6:-4]), "image/gif"
                else:
                    self.send_error(404)
                    return
            except (OSError, ValueError):
                self.send_error(404, "Missing or unverified asset")
                return
            self.send_response(200)
            self.send_header("Content-Type", mime + ("; charset=utf-8" if mime != "image/gif" else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass  # 本预览不记录请求正文、用户文本或设备信息。

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--check-assets", action="store_true")
    args = parser.parse_args()
    if args.port in (8000, 8003, 8767):
        parser.error("daily-service ports are reserved; use default random port")
    if args.check_assets:
        result = inventory(args.assets)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["valid_count"] == 21 else 2
    with ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.assets)) as server:
        print(f"Otto preview: http://127.0.0.1:{server.server_port}/", flush=True)
        print("Read-only, independent preview. Ctrl+C stops this server.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
