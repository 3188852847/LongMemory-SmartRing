"""仅监听回环的 React 启动器；浏览器关闭后，受管服务继续运行。"""

from __future__ import annotations

import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import unquote, urlsplit
import webbrowser

from control import CONTROL_FILE_NAME, LauncherControl, request_control
from controller import ControllerError, LauncherController
from runtime import ROOT, Singleton

DISCOVERY_NAME = 'launcher-web.json'
MAX_BODY = 16384


class LauncherHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, controller, dist, *, token=None):
        self.controller = controller
        self.dist = Path(dist).resolve()
        self.token = token or secrets.token_urlsafe(32)
        self.shutdown_observed = threading.Event()
        try:
            manifest = json.loads((self.dist / '.vite/manifest.json').read_text(encoding='utf-8'))
            if not isinstance(manifest, dict):
                raise ValueError
            self.assets = set()
            for record in manifest.values():
                if not isinstance(record, dict):
                    raise ValueError
                for value in [record.get('file'), *record.get('css', []), *record.get('assets', [])]:
                    if isinstance(value, str) and value.startswith('assets/'):
                        candidate = Path(value)
                        if '\\' in value or ':' in value or '..' in candidate.parts:
                            raise ValueError
                        if candidate.suffix.lower() in {'.js', '.css', '.svg', '.png', '.jpg', '.webp', '.woff', '.woff2'}:
                            self.assets.add(value)
        except (OSError, TypeError, ValueError):
            raise ValueError('启动页面构建清单无效，请在 web/react-chat 重新执行 pnpm.cmd build。') from None
        super().__init__(('127.0.0.1', 0), LauncherHandler)
        self.origin = f'http://127.0.0.1:{self.server_port}'

    @property
    def browser_url(self):
        # fragment 不会传入 HTTP 请求、访问日志或 Referer。
        return self.origin + '/#token=' + self.token


class LauncherHandler(BaseHTTPRequestHandler):
    server: LauncherHTTPServer

    def log_message(self, format, *args):
        # 不记录请求头、token 或本机路径；状态可在启动页直接查看。
        pass

    def _send(self, status, body, content_type='application/json; charset=utf-8', *, nonce=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        style_nonce = f" 'nonce-{nonce}'" if nonce else ''
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'" + style_nonce + "; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, body):
        self._send(status, json.dumps(body, ensure_ascii=False).encode('utf-8'))

    def _error(self, status, code, message):
        self._json(status, {'error': code, 'message': message})

    def _local_request(self):
        hosts = self.headers.get_all('Host', [])
        origins = self.headers.get_all('Origin', [])
        if hosts != [urlsplit(self.server.origin).netloc] or (
                origins and origins != [self.server.origin]):
            self._error(403, 'foreign_origin', '仅允许从本机启动页面操作。')
            return False
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self._error(403, 'foreign_origin', '仅允许从本机启动页面操作。')
            return False
        return True

    def _authenticated(self):
        values = self.headers.get_all('Authorization', [])
        if len(values) != 1 or not secrets.compare_digest(values[0], 'Bearer ' + self.server.token):
            self._error(401, 'unauthorized', '此页面未取得启动器权限，请从日常入口重新打开。')
            return False
        return True

    def do_GET(self):
        if not self._local_request():
            return
        parsed = urlsplit(self.path)
        if parsed.query:
            return self._error(400, 'invalid_request', '此入口不接受查询参数。')
        if parsed.path == '/api/launcher/status':
            if self._authenticated():
                try:
                    snapshot = self.server.controller.snapshot()
                    self._json(200, snapshot)
                    if snapshot.get('shutdown_complete'):
                        self.server.shutdown_observed.set()
                except ControllerError as error:
                    self._error(error.status, 'settings_unavailable', str(error))
            return
        if parsed.path == '/':
            target = self.server.dist / 'launcher.html'
        elif parsed.path.startswith('/react-chat/assets/'):
            suffix = unquote(parsed.path[len('/react-chat/assets/'):])
            # URL 反斜杠和二次编码不能参与 Windows 路径解析。
            if not suffix or '\\' in suffix or '%' in suffix or ':' in suffix:
                return self._error(404, 'not_found', '资源不存在。')
            target = self.server.dist / 'assets' / suffix
            if 'assets/' + suffix not in self.server.assets:
                return self._error(404, 'not_found', '资源不存在。')
            if target.suffix.lower() not in {'.js', '.css', '.svg', '.png', '.jpg', '.webp', '.woff', '.woff2'}:
                return self._error(404, 'not_found', '资源不存在。')
        else:
            return self._error(404, 'not_found', '入口不存在。')
        # resolve 也检查联接/符号链接，不能从构建目录逃逸到源码或私有配置。
        resolved = target.resolve()
        required_parent = self.server.dist if parsed.path == '/' else self.server.dist / 'assets'
        if not resolved.is_relative_to(required_parent) or not resolved.is_file():
            return self._error(404, 'not_found', '资源不存在，请先构建前端。')
        try:
            body = resolved.read_bytes()
        except OSError:
            return self._error(404, 'not_found', '资源暂不可读取，请检查前端构建。')
        nonce = None
        if parsed.path == '/':
            if body.count(b'__LONGMEMORY_NONCE__') != 1:
                return self._error(404, 'build_invalid', '启动页构建不完整，请重新构建前端。')
            nonce = secrets.token_urlsafe(24)
            body = body.replace(b'__LONGMEMORY_NONCE__', nonce.encode('ascii'))
        self._send(200, body, mimetypes.guess_type(resolved.name)[0] or 'application/octet-stream', nonce=nonce)

    def do_POST(self):
        if not self._local_request() or not self._authenticated():
            return
        if self.path not in {'/api/launcher/settings', '/api/launcher/actions'}:
            return self._error(404, 'not_found', '入口不存在。')
        try:
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or self.headers.get('Transfer-Encoding'):
                raise ValueError
            length = int(lengths[0])
            if not 0 < length <= MAX_BODY or self.headers.get_content_type() != 'application/json':
                raise ValueError
            self.connection.settimeout(5)
            data = self.rfile.read(length)
            if len(data) != length:
                raise ValueError
            body = json.loads(data)
            if not isinstance(body, dict):
                raise ValueError
            if self.path.endswith('/settings'):
                if set(body) != {'settings', 'expected_revision'}:
                    raise ValueError
                result = self.server.controller.update_settings(body['settings'], body['expected_revision'])
            else:
                if set(body) != {'action'} or not isinstance(body['action'], str):
                    raise ValueError
                result = self.server.controller.action(body['action'])
        except ControllerError as error:
            return self._error(error.status, 'settings_conflict' if error.status == 409 else 'operation_rejected', str(error))
        except (ValueError, TypeError, OSError):
            return self._error(400, 'invalid_request', '请求格式无效。')
        self._json(200, result)


def create_server(controller, dist, *, token=None):
    """可注入合成控制器与临时构建目录，不需要日用服务才能验收 UI。"""
    return LauncherHTTPServer(controller, dist, token=token)


def publish_discovery(path, server, control):
    payload = {'schema_version': 1, 'origin': server.origin, 'token': server.token,
               'control_token_digest': hashlib.sha256(control.token.encode()).hexdigest()}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload), encoding='utf-8')
    temporary.replace(path)


def reopen_existing(root, *, opener=webbrowser.open):
    """只有旧 socket 活着且发现文件绑定其随机令牌，才打开既有网页实例。"""
    try:
        control_path = root / 'data/control' / CONTROL_FILE_NAME
        response = request_control(control_path, 'status', timeout=3)
        if not response.get('ok'):
            return False
        control = json.loads(control_path.read_text(encoding='utf-8'))
        discovery = json.loads((root / 'data/control' / DISCOVERY_NAME).read_text(encoding='utf-8'))
        parsed = urlsplit(discovery['origin'])
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not 1024 <= parsed.port <= 65535:
            return False
        if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            return False
        token = discovery['token']
        if not isinstance(token, str) or len(token) < 32 or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for char in token):
            return False
        if discovery['control_token_digest'] != hashlib.sha256(control['token'].encode()).hexdigest():
            return False
        connection = http.client.HTTPConnection('127.0.0.1', parsed.port, timeout=2)
        try:
            connection.request('GET', '/api/launcher/status', headers={'Authorization': 'Bearer ' + token})
            health = connection.getresponse()
            if health.status != 200:
                return False
            status = json.loads(health.read(32768))
            if status.get('state') not in {'stopped', 'starting', 'ready', 'stopping', 'failed'}:
                return False
        finally:
            connection.close()
        opener(discovery['origin'] + '/#token=' + token)
        return True
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, http.client.HTTPException):
        return False


def show_error(message):
    """pythonw 无控制台时也能看到明确错误；仅用 Tk 提示，不启动旧面板。"""
    import tkinter
    from tkinter import messagebox
    window = tkinter.Tk()
    window.withdraw()
    messagebox.showerror('智慧圆屏启动器', message, parent=window)
    window.destroy()


def main():
    try:
        lock = Singleton()
    except ValueError:
        if not reopen_existing(ROOT):
            show_error('已有旧启动面板或端口占用。请使用原面板；如需切换，先停止服务并退出原面板。未关闭任何外部程序。')
        return
    controller = server = control = None
    discovery_path = ROOT / 'data/control' / DISCOVERY_NAME
    try:
        dist = ROOT / 'web/react-chat/dist'
        if not (dist / 'launcher.html').is_file():
            show_error('启动页面尚未构建。请在 web/react-chat 执行 pnpm.cmd build 后重试；原面板 app.py 仍可作为回退入口。')
            return
        controller = LauncherController(ROOT)
        server = create_server(controller, dist)
        control = LauncherControl(lock.socket, ROOT / 'data/control' / CONTROL_FILE_NAME)
        controller.control = control
        publish_discovery(discovery_path, server, control)
        controller.start_worker()
        server.timeout = .25
        webbrowser.open(server.browser_url)
        shutdown_at = None
        while True:
            server.handle_request()
            if controller.shutdown_requested.is_set():
                shutdown_at = shutdown_at or time.monotonic()
                if server.shutdown_observed.is_set() or time.monotonic() - shutdown_at >= 5:
                    break
    except (OSError, ValueError):
        show_error('启动页面或本机控制接口无法建立。请检查前端构建与本机配置目录；未关闭外部程序。')
    finally:
        if controller:
            controller.close()
        if control:
            control.close()
        if server:
            server.server_close()
            try:
                saved = json.loads(discovery_path.read_text(encoding='utf-8'))
                if saved.get('token') == server.token:
                    discovery_path.unlink()
            except (OSError, ValueError):
                pass
        lock.close()


if __name__ == '__main__':
    main()
