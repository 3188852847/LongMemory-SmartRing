"""本机音色窄接口：固定进程、固定文本、单次请求、不自动重试。"""
import asyncio
import http.client
import json
import os
from pathlib import Path
import subprocess
from time import monotonic
import hashlib
from aiohttp import web

PROFILE_DEFAULT = {"version": 1, "reference": None, "style": "", "cfg_value": 2.0,
                   "quality": "balanced"}


class VoiceSettings:
    def __init__(self, server, database, project):
        self.server, self.database, self.project = Path(server).resolve(), database, Path(project)
        self.lock = asyncio.Lock()
        self.last_preview = float('-inf')
        self.audio_root = (self.project / 'data/audio').resolve()
        self.profile_path = self.audio_root / 'voxcpm-settings.json'

    def references(self):
        items = [{"id": None, "label": "模型默认声线"}]
        if self.audio_root.is_dir():
            for path in sorted(self.audio_root.glob('**/*.wav')):
                if path.is_file() and not path.is_symlink() and path.stat().st_size <= 20 * 1024 * 1024:
                    items.append({"id": path.relative_to(self.audio_root).as_posix(),
                                  "label": path.stem})
        return items

    def profile(self):
        try:
            value = json.loads(self.profile_path.read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeError):
            value = dict(PROFILE_DEFAULT)
        valid_refs = {item['id'] for item in self.references()}
        if (not isinstance(value, dict) or set(value) != set(PROFILE_DEFAULT)
                or value.get('version') != 1 or value.get('reference') not in valid_refs
                or not isinstance(value.get('style'), str) or len(value['style']) > 100
                or any(ord(char) < 32 for char in value['style'])
                or type(value.get('cfg_value')) not in {int, float}
                or not 1 <= value['cfg_value'] <= 3
                or value.get('quality') not in {'fast', 'balanced', 'quality'}):
            value = dict(PROFILE_DEFAULT)
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
        return value, hashlib.sha256(raw).hexdigest()

    def save_profile(self, body):
        current, digest = self.profile()
        if body.get('expected_profile_digest') != digest:
            raise ValueError('profile_changed')
        candidate = {"version": 1, "reference": body.get('reference'),
                     "style": body.get('style'), "cfg_value": body.get('cfg_value'),
                     "quality": body.get('quality')}
        valid_refs = {item['id'] for item in self.references()}
        if (candidate['reference'] not in valid_refs or not isinstance(candidate['style'], str)
                or len(candidate['style']) > 100 or any(ord(char) < 32 for char in candidate['style'])
                or type(candidate['cfg_value']) not in {int, float} or not 1 <= candidate['cfg_value'] <= 3
                or candidate['quality'] not in {'fast', 'balanced', 'quality'}):
            raise ValueError('invalid_profile')
        self.audio_root.mkdir(parents=True, exist_ok=True)
        temporary = self.profile_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, self.profile_path)
        return self.profile()

    @staticmethod
    def voxcpm_speech(text):
        connection = http.client.HTTPConnection('127.0.0.1', 18768, timeout=30)
        payload = json.dumps({'input': text, 'response_format': 'wav', 'stream': False}).encode()
        try:
            connection.request('POST', '/v1/audio/speech', body=payload,
                               headers={'Content-Type': 'application/json'})
            response = connection.getresponse(); audio = response.read(8 * 1024 * 1024 + 1)
            if response.status != 200 or len(audio) > 8 * 1024 * 1024 or not audio.startswith(b'RIFF'):
                raise ValueError('synthesis_failed')
            return audio
        except (OSError, http.client.HTTPException):
            raise ValueError('synthesis_failed') from None
        finally:
            connection.close()

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
            if body.get('action') == 'apply_voxcpm':
                profile, digest = self.save_profile(body)
                return {'profile': profile, 'profile_digest': digest, 'references': self.references()}
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
                profile, digest = self.profile()
                value.update(profile=profile, profile_digest=digest, references=self.references(), editable=True)
            return value

    async def speech(self, text):
        if self.lock.locked():
            raise ValueError('busy')
        async with self.lock:
            python = self.server / '.venv/Scripts/python.exe'
            if not python.is_file():
                raise ValueError('unavailable')
            check = await self.call_without_lock({'action':'check'}, python)
            if check.get('backend') == 'voxcpm2':
                return await asyncio.to_thread(self.voxcpm_speech, text), 'audio/wav'
            if check.get('backend') != 'edge':
                raise ValueError('unsupported')
            audio = await self.call_without_lock({'action':'preview', 'voice':check['voice'], 'text':text}, python)
            return audio, 'audio/mpeg'

    async def call_without_lock(self, body, python):
        payload = body | {'database': str(self.database), 'project': str(self.project)}
        result = await asyncio.to_thread(subprocess.run,
            [str(python), str(self.project / 'scripts/development/xiaozhi/voice_settings.py'), str(self.server)],
            input=json.dumps(payload).encode(), capture_output=True, timeout=35,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode or not result.stdout or len(result.stdout) > 8 * 1024 * 1024:
            raise ValueError('voice_operation_failed')
        return result.stdout if body['action'] == 'preview' else json.loads(result.stdout)


def register_voice_routes(app, backend):
    async def settings(request):
        if backend is None:
            return web.json_response({'error': 'voice_not_enabled'}, status=403)
        try:
            if request.method == 'GET':
                return web.json_response(await backend.call({'action': 'check'}))
            body = await request.json()
            preview = request.path.endswith('/preview')
            if not isinstance(body, dict): raise ValueError('invalid_body')
            if set(body) == {'reference','style','cfg_value','quality','expected_profile_digest'} and not preview:
                result = await backend.call(body | {'action':'apply_voxcpm'})
                return web.json_response(result)
            required = {'voice'} if preview else {'voice', 'expected_digest'}
            if set(body) != required or any(not isinstance(v, str) for v in body.values()): raise ValueError('invalid_body')
            if len(body['voice']) > 80 or (not preview and len(body['expected_digest']) != 64): raise ValueError('invalid_body')
            result = await backend.call(body | {'action': 'preview' if preview else 'apply'})
            if preview:
                return web.Response(body=result, content_type='audio/mpeg')
            return web.json_response(result)
        except (ValueError, OSError):
            return web.json_response({'error': 'voice_operation_failed_recheck'}, status=409)
    async def speech(request):
        if backend is None:
            return web.json_response({'error':'voice_not_enabled'}, status=403)
        try:
            body = await request.json()
            if (not isinstance(body, dict) or set(body) != {'text'} or not isinstance(body['text'], str)
                    or not body['text'].strip() or len(body['text']) > 600):
                raise ValueError('invalid_body')
            audio, content_type = await backend.speech(body['text'].strip())
            return web.Response(body=audio, content_type=content_type,
                                headers={'Cache-Control':'no-store'})
        except (ValueError, OSError):
            return web.json_response({'error':'speech_failed'}, status=409)
    app.router.add_get('/api/voice-settings', settings, allow_head=False)
    app.router.add_post('/api/voice-settings', settings)
    app.router.add_post('/api/voice-settings/preview', settings)
    app.router.add_post('/api/speech', speech)
