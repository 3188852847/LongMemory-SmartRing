"""智能圆屏壁纸的短时、单文件局域网投递入口。

这个模块不负责选择素材，也不把任意目录暴露成静态站点。控制层先通过
``RoundWallpaperLibrary.preview_path`` 得到已经过哈希复核的 GIF，再签发一个
短时票据。圆屏只能用不可猜测的 URL 读取这一个文件一次；失败重试必须重新
签发票据，避免长期 URL 变成局域网中的素材下载入口。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import asyncio
import base64
import hashlib
from pathlib import Path
import re
import secrets
from typing import Callable

from aiohttp import web


DEFAULT_DELIVERY_PORT = 8768
DEFAULT_TTL_SECONDS = 180
MAX_DELIVERY_BYTES = 4 * 1024 * 1024
_TOKEN = re.compile(r"[0-9a-f]{64}")
_ITEM_ID = re.compile(r"wallpaper-[0-9a-f]{20}")


class DeliveryError(ValueError):
    """只包含稳定错误码，不携带本机路径或素材内容。"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class DeliveryTicket:
    token: str
    item_id: str
    path: Path
    sha256: str
    size_bytes: int
    expires_at: datetime


class RoundWallpaperDeliveryRegistry:
    """保存仅存在于当前进程内存中的一次性下载票据。"""

    def __init__(self, *, clock: Callable[[], datetime] | None = None):
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._tickets: dict[str, DeliveryTicket] = {}

    def issue(
        self,
        *,
        item_id: str,
        path: Path,
        expected_sha256: str,
        expected_size: int,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> DeliveryTicket:
        """在签发前重新检查磁盘文件，不能只相信素材清单。"""

        resolved = Path(path).resolve()
        if not _ITEM_ID.fullmatch(item_id):
            raise DeliveryError("invalid_wallpaper_id")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise DeliveryError("invalid_wallpaper_sha256")
        if type(expected_size) is not int or not 0 < expected_size <= MAX_DELIVERY_BYTES:
            raise DeliveryError("invalid_wallpaper_size")
        if type(ttl_seconds) is not int or not 10 <= ttl_seconds <= 300:
            raise DeliveryError("invalid_delivery_ttl")
        if not resolved.is_file() or resolved.stat().st_size != expected_size:
            raise DeliveryError("wallpaper_delivery_integrity_failed")
        if _sha256(resolved) != expected_sha256:
            raise DeliveryError("wallpaper_delivery_integrity_failed")

        self._discard_expired()
        token = secrets.token_hex(32)
        ticket = DeliveryTicket(
            token=token,
            item_id=item_id,
            path=resolved,
            sha256=expected_sha256,
            size_bytes=expected_size,
            expires_at=self._clock() + timedelta(seconds=ttl_seconds),
        )
        self._tickets[token] = ticket
        return ticket

    def take(self, token: str) -> DeliveryTicket:
        """原子取走票据；同一 URL 的第二次读取必然失败。"""

        if not _TOKEN.fullmatch(token):
            raise DeliveryError("delivery_ticket_not_found")
        ticket = self._tickets.pop(token, None)
        if ticket is None or ticket.expires_at <= self._clock():
            raise DeliveryError("delivery_ticket_not_found")
        # 签发后到实际读取之间文件仍可能被替换，因此读取前再核对一次。
        if (not ticket.path.is_file()
                or ticket.path.stat().st_size != ticket.size_bytes
                or _sha256(ticket.path) != ticket.sha256):
            raise DeliveryError("wallpaper_delivery_integrity_failed")
        return ticket

    def revoke(self, token: str) -> None:
        self._tickets.pop(token, None)

    def _discard_expired(self) -> None:
        now = self._clock()
        for token, ticket in list(self._tickets.items()):
            if ticket.expires_at <= now:
                self._tickets.pop(token, None)


class RoundWallpaperDeliveryService:
    """持有票据注册表和局域网 URL 身份；监听生命周期由控制台管理。"""

    def __init__(
        self,
        listen_address: str,
        *,
        port: int = DEFAULT_DELIVERY_PORT,
        registry: RoundWallpaperDeliveryRegistry | None = None,
    ):
        self.listen_address = listen_address
        self.port = port
        self.registry = registry or RoundWallpaperDeliveryRegistry()

    def issue(self, **values) -> tuple[DeliveryTicket, str]:
        ticket = self.registry.issue(**values)
        return ticket, f"http://{self.listen_address}:{self.port}/wallpaper/{ticket.token}"

    def revoke(self, token: str) -> None:
        self.registry.revoke(token)

    def app(self) -> web.Application:
        return create_round_wallpaper_delivery_app(
            self.registry, listen_address=self.listen_address, port=self.port,
        )


def create_round_wallpaper_delivery_app(
    registry: RoundWallpaperDeliveryRegistry,
    *,
    listen_address: str,
    port: int = DEFAULT_DELIVERY_PORT,
) -> web.Application:
    """创建只服务票据 URL 的独立应用，不复用控制台会话或静态路由。"""

    expected_host = f"{listen_address}:{port}"

    @web.middleware
    async def guard(request: web.Request, handler):
        if (request.headers.get("Host") != expected_host
                or "Origin" in request.headers
                or "Sec-Fetch-Site" in request.headers):
            response = web.json_response({"error": "delivery_request_rejected"}, status=403)
        else:
            response = await handler(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    async def download(request: web.Request):
        try:
            ticket = registry.take(request.match_info["token"])
        except DeliveryError as error:
            status = 409 if str(error) == "wallpaper_delivery_integrity_failed" else 404
            return web.json_response({"error": str(error)}, status=status)
        # 最多 4 MiB，先读入不可变响应体再做最后一次校验，避免校验后到
        # FileResponse 实际打开文件之间被替换的时间窗口。
        payload = await asyncio.to_thread(ticket.path.read_bytes)
        if len(payload) != ticket.size_bytes or hashlib.sha256(payload).hexdigest() != ticket.sha256:
            return web.json_response({"error": "wallpaper_delivery_integrity_failed"}, status=409)
        digest = base64.b64encode(bytes.fromhex(ticket.sha256)).decode("ascii")
        response = web.Response(body=payload, content_type="image/gif")
        response.headers["Content-Disposition"] = "attachment; filename=round-wallpaper.gif"
        response.headers["Digest"] = f"sha-256={digest}"
        response.headers["X-Wallpaper-Id"] = ticket.item_id
        return response

    app = web.Application(client_max_size=1024, middlewares=[guard])
    app.router.add_get("/wallpaper/{token}", download, allow_head=False)
    return app
