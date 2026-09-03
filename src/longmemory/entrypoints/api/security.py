"""回环网页的最小会话防护：不是多用户认证，也不对抗本机恶意程序。"""

import secrets
import time
from collections import OrderedDict

from aiohttp import web

COOKIE = "lm_console_session"
MAX_AGE = 8 * 60 * 60


class Sessions:
    def __init__(self):
        self.values = OrderedDict()

    def create(self):
        # 有上限和有效期，避免无限保留会话；服务重启后全部失效。
        session, csrf = secrets.token_hex(32), secrets.token_hex(32)
        self.values[session] = (csrf, time.monotonic() + MAX_AGE)
        while len(self.values) > 32:
            self.values.popitem(last=False)
        return session, csrf

    def csrf(self, session):
        record = self.values.get(session)
        if record is None:
            return None
        if record[1] <= time.monotonic():
            self.values.pop(session, None)
            return None
        return record[0]


def security_middleware(authority: str, sessions: Sessions):
    origin = "http://" + authority

    @web.middleware
    async def protect(request, handler):
        response = None
        try:
            # Host 限定阻挡 DNS 重绑定；跨源网站不能借用本机浏览器管理设备。
            if (request.remote != "127.0.0.1" or request.host != authority
                    or request.headers.get("Origin") not in {None, origin}
                    or request.headers.get("Sec-Fetch-Site") not in {None, "none", "same-origin"}):
                response = web.json_response({"error": "origin_rejected"}, status=403)
            elif request.path.startswith("/api/") and request.path != "/api/session":
                csrf = sessions.csrf(request.cookies.get(COOKIE))
                if csrf is None:
                    response = web.json_response({"error": "session_required"}, status=401)
                elif request.method not in {"GET", "HEAD"} and (
                    request.headers.get("Origin") != origin
                    or not secrets.compare_digest(request.headers.get("X-Console-CSRF", "").encode(), csrf.encode())
                ):
                    response = web.json_response({"error": "csrf_rejected"}, status=403)
            if response is None:
                response = await handler(request)
        except web.HTTPException as error:
            response = web.json_response({"error": "request_rejected"}, status=error.status)
        except Exception:
            # 未预期异常也不回传路径、原始响应或配置内容；前端不能据此宣称未执行。
            response = web.json_response({"error": "console_internal_error"}, status=500)
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; "
                "img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        })
        return response

    return protect
