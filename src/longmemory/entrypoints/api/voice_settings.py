"""本机音色窄接口：固定进程、固定文本、单次请求、不自动重试。"""
import asyncio
import http.client
import json
import os
from pathlib import Path
import subprocess
from time import monotonic
from aiohttp import web


class VoiceSettings:
    def __init__(self, server, database, project):
        self.server, self.database, self.project = Path(server).resolve(), database, Path(project)
        self.lock = asyncio.Lock()
        self.last_preview = float('-inf')

    @staticmethod
    def voxcpm_ready():
        """只读取固定环回健康端点；失败表示未就绪，不把底层异常返回页面。"""
        connection = http.client.HTTPConnection('127.0.0.1', 18768, timeout=0.5)
        try:
            connection.request('GET', '/health')
            response = connection.getresponse()
            body = json.loads(response.read(4096))
            return response.status == 200 and body.get('ready') is True and body.get('provider') == 'voxcpm2'
        except (OSError, http.client.HTTPException, json.JSONDecodeError):
            return False
        finally:
            connection.close()

    async def call(self, body):
        if self.lock.locked():
            raise ValueError('busy')
        async with self.lock:
            if body.get('action') == 'preview':
                if monotonic() - self.last_preview < 3:
                    raise ValueError('cooldown')
                self.last_preview = monotonic()
            python = self.server / '.venv/Scripts/python.exe'
            if not python.is_file() or not (self.server / 'app.py').is_file():
                raise ValueError('unavailable')
            payload = body | {'database': str(self.database), 'project': str(self.project)}
            try:
                result = await asyncio.to_thread(subprocess.run,
                    [str(python), str(self.project / 'scripts/development/xiaozhi/voice_settings.py'), str(self.server)],
                    input=json.dumps(payload).encode(), capture_output=True, timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            except (OSError, subprocess.TimeoutExpired):
                raise ValueError('voice_operation_unverified') from None
            if result.returncode or not result.stdout or len(result.stdout) > 2 * 1024 * 1024:
                raise ValueError('voice_operation_failed')
            if body['action'] == 'preview':
                return result.stdout
            value = json.loads(result.stdout)
            if body['action'] == 'check' and value.get('backend') == 'voxcpm2':
                value['service_ready'] = await asyncio.to_thread(self.voxcpm_ready)
            return value


def register_voice_routes(app, backend):
    async def settings(request):
        if backend is None:
            return web.json_response({'error': 'voice_not_enabled'}, status=403)
        try:
            if request.method == 'GET':
                return web.json_response(await backend.call({'action': 'check'}))
            body = await request.json()
            preview = request.path.endswith('/preview')
            required = {'voice'} if preview else {'voice', 'expected_digest'}
            if not isinstance(body, dict) or set(body) != required or any(not isinstance(v, str) for v in body.values()):
                raise ValueError('invalid_body')
            if len(body['voice']) > 80 or (not preview and len(body['expected_digest']) != 64):
                raise ValueError('invalid_body')
            result = await backend.call(body | {'action': 'preview' if preview else 'apply'})
            if preview:
                return web.Response(body=result, content_type='audio/mpeg')
            return web.json_response(result)
        except (ValueError, OSError):
            return web.json_response({'error': 'voice_operation_failed_recheck'}, status=409)
    app.router.add_get('/api/voice-settings', settings, allow_head=False)
    app.router.add_post('/api/voice-settings', settings)
    app.router.add_post('/api/voice-settings/preview', settings)
