"""本机音色窄接口：固定进程、固定文本、单次请求、不自动重试。"""
import asyncio
import http.client
import json
import os
from pathlib import Path
import subprocess
from time import monotonic
import hashlib
import base64
import binascii
from aiohttp import web

from longmemory.adapters.tts import capabilities_for
from longmemory.application.voice_benchmark import CASES, case_by_id, measure_buffered_speech
from longmemory.infrastructure.config.tts_benchmark_history import TTSBenchmarkHistory
from longmemory.infrastructure.config.cosyvoice_profiles import profile_module

PROFILE_DEFAULT = {"version": 1, "reference": None, "style": "", "cfg_value": 2.0,
                   "quality": "balanced"}

# 只把可执行的故障类别交给页面，不返回子进程输出、路径或供应商正文。
SPEECH_FAILURES = {
    'busy': ('speech_busy', 409),
    'synthesis_failed': ('tts_service_unavailable', 503),
    'unsupported': ('tts_backend_unsupported', 409),
    'unavailable': ('voice_environment_unavailable', 503),
    'voice_operation_failed': ('tts_config_unavailable', 503),
}
LOCAL_TTS = {"voxcpm2": 18768, "sanotts": 18769, "cosyvoice3": 18770}


def speech_failure(error):
    return SPEECH_FAILURES.get(str(error), ('speech_failed', 409))


class VoiceSettings:
    def __init__(self, server, database, project):
        self.server, self.database, self.project = Path(server).resolve(), database, Path(project)
        self.lock = asyncio.Lock()
        self.last_preview = float('-inf')
        self.audio_root = (self.project / 'data/audio').resolve()
        self.profile_path = self.audio_root / 'voxcpm-settings.json'
        self.cosy_profiles = profile_module().VoiceProfileStore(self.project)
        self.benchmark_history = TTSBenchmarkHistory(
            self.project / 'data/control/tts-benchmark-history.json'
        )

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
    def local_speech(backend, text, *, bypass_local_cache=False, speaking_rate=1.0, voice_profile=None):
        connection = http.client.HTTPConnection('127.0.0.1', LOCAL_TTS[backend], timeout=30)
        request = {'input': text, 'response_format': 'wav', 'stream': False}
        # VoxCPM2 日常链保留重复句缓存；只有固定测试台显式绕过它，防止把缓存读取
        # 误报为模型生成速度。sanoTTS 没有这一私有字段，保持其公开兼容契约。
        if backend in {'voxcpm2', 'cosyvoice3'} and bypass_local_cache:
            request['cache'] = False
        if backend == 'sanotts':
            request['speed'] = speaking_rate
        if backend == 'cosyvoice3' and voice_profile is not None:
            request['voice_profile'] = voice_profile
        payload = json.dumps(request).encode()
        try:
            connection.request('POST', '/v1/audio/speech', body=payload,
                               headers={'Content-Type': 'application/json'})
            response = connection.getresponse(); audio = response.read(8 * 1024 * 1024 + 1)
            if response.status != 200 or len(audio) > 8 * 1024 * 1024 or not audio.startswith(b'RIFF'):
                raise ValueError('synthesis_failed')
            if voice_profile is not None and response.getheader('X-LongMemory-Voice-Profile') != '1':
                raise ValueError('synthesis_failed')
            return audio
        except (OSError, http.client.HTTPException):
            raise ValueError('synthesis_failed') from None
        finally:
            connection.close()

    @staticmethod
    def local_ready(backend):
        """只读取固定环回健康端点；失败表示未就绪，不把底层异常返回页面。"""
        connection = http.client.HTTPConnection('127.0.0.1', LOCAL_TTS[backend], timeout=0.5)
        try:
            connection.request('GET', '/health')
            response = connection.getresponse()
            body = json.loads(response.read(4096))
            return response.status == 200 and body.get('ready') is True and body.get('provider') == backend
        except (OSError, http.client.HTTPException, json.JSONDecodeError):
            return False
        finally:
            connection.close()

    @staticmethod
    def voxcpm_ready():
        """兼容旧测试与调用方。"""
        return VoiceSettings.local_ready('voxcpm2')

    @staticmethod
    def cosy_profile_service_state():
        connection = http.client.HTTPConnection('127.0.0.1', LOCAL_TTS['cosyvoice3'], timeout=0.5)
        try:
            connection.request('GET', '/health')
            response = connection.getresponse()
            value = json.loads(response.read(16384))
            if response.status != 200 or not isinstance(value, dict) or value.get('provider') != 'cosyvoice3' or value.get('ready') is not True:
                return 'unavailable'
            return 'ready' if value.get('voice_profile_contract_version') == 1 else 'needs_restart'
        except (OSError, ValueError, http.client.HTTPException):
            return 'unavailable'
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
            if body['action'] == 'check' and value.get('backend') in LOCAL_TTS:
                value['service_ready'] = await asyncio.to_thread(self.local_ready, value['backend'])
            if body['action'] == 'check' and value.get('backend') == 'voxcpm2':
                profile, digest = self.profile()
                value.update(profile=profile, profile_digest=digest, references=self.references(), editable=True)
            capabilities = capabilities_for(value.get('backend'))
            if capabilities is not None:
                value['capabilities'] = capabilities.as_dict()
            return value

    async def speech(self, text, *, bypass_local_cache=False):
        if self.lock.locked():
            raise ValueError('busy')
        async with self.lock:
            python = self.server / '.venv/Scripts/python.exe'
            if not python.is_file():
                raise ValueError('unavailable')
            check = await self.call_without_lock({'action':'check'}, python)
            if check.get('backend') in LOCAL_TTS:
                return await asyncio.to_thread(
                    self.local_speech, check['backend'], text,
                    bypass_local_cache=bypass_local_cache,
                    speaking_rate=check.get('speed', 1.0),
                ), 'audio/wav'
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
    async def cosy_snapshot():
        result = backend.cosy_profiles.snapshot()
        result['service_state'] = await asyncio.to_thread(backend.cosy_profile_service_state)
        result['activation'] = 'next_synthesis' if result['service_state'] == 'ready' else 'after_service_start'
        return result
    async def limited_json(request, maximum):
        # 只为受控声音上传扩展单一路由，其他 API 保持原 1KiB 默认限制。
        if request.content_type != 'application/json' or (request.content_length is not None and request.content_length > maximum):
            raise ValueError('invalid_voice_request')
        chunks, total = [], 0
        async for chunk in request.content.iter_chunked(65536):
            total += len(chunk)
            if total > maximum:
                raise ValueError('invalid_voice_request')
            chunks.append(chunk)
        body = json.loads(b''.join(chunks))
        if not isinstance(body, dict):
            raise ValueError('invalid_voice_request')
        return body

    async def cosy_profile(request):
        if backend is None:
            return web.json_response({'error': 'voice_not_enabled'}, status=403)
        try:
            if request.method == 'GET':
                return web.json_response(await cosy_snapshot())
            body = await limited_json(request, 8192)
            if set(body) != {'profile', 'expected_profile_digest'}:
                raise ValueError('invalid_voice_request')
            async with backend.lock:
                backend.cosy_profiles.save(body['profile'], body['expected_profile_digest'])
                return web.json_response(await cosy_snapshot())
        except (ValueError, OSError, UnicodeError) as error:
            changed = str(error) == 'voice_profile_changed'
            return web.json_response({'error': 'voice_profile_changed' if changed else 'invalid_voice_profile'}, status=409 if changed else 400)

    async def upload_reference(request):
        if backend is None:
            return web.json_response({'error': 'voice_not_enabled'}, status=403)
        try:
            module = profile_module()
            body = await limited_json(request, ((module.MAX_AUDIO_BYTES + 2) // 3) * 4 + 8192)
            if set(body) != {'audio_base64', 'label', 'transcript'} or not isinstance(body['audio_base64'], str):
                raise ValueError('invalid_voice_request')
            data = base64.b64decode(body['audio_base64'], validate=True)
            async with backend.lock:
                item = backend.cosy_profiles.add_reference(data, body['label'], body['transcript'])
                return web.json_response({'item': item, 'references': backend.cosy_profiles.references()}, status=201)
        except (ValueError, OSError, UnicodeError, binascii.Error) as error:
            full = str(error) == 'voice_reference_library_full'
            return web.json_response({'error': 'voice_reference_library_full' if full else 'invalid_voice_reference'}, status=409 if full else 400)

    async def cosy_preview(request):
        if backend is None:
            return web.json_response({'error': 'voice_not_enabled'}, status=403)
        try:
            body = await limited_json(request, 8192)
            if set(body) != {'profile'}:
                raise ValueError('invalid_voice_request')
            profile = backend.cosy_profiles.validate_profile(body['profile'])
            if await asyncio.to_thread(backend.cosy_profile_service_state) != 'ready':
                return web.json_response({'error': 'voice_profile_service_restart_required'}, status=409)
            if backend.lock.locked() or monotonic() - backend.last_preview < 3:
                return web.json_response({'error': 'speech_busy'}, status=409)
            async with backend.lock:
                backend.last_preview = monotonic()
                audio = await asyncio.to_thread(backend.local_speech, 'cosyvoice3', profile_module().PREVIEW_TEXT,
                    bypass_local_cache=True, voice_profile=profile)
            return web.Response(body=audio, content_type='audio/wav', headers={'Cache-Control': 'no-store'})
        except (ValueError, OSError, UnicodeError):
            return web.json_response({'error': 'voice_preview_unavailable'}, status=409)

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
            if set(body) == {'speed', 'expected_digest'} and not preview:
                if (type(body['speed']) not in {int, float} or not 0.75 <= body['speed'] <= 1.5
                        or not isinstance(body['expected_digest'], str)
                        or len(body['expected_digest']) != 64):
                    raise ValueError('invalid_body')
                result = await backend.call(body | {'action':'apply_sanotts'})
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
        except ValueError as error:
            code, status = speech_failure(error)
            return web.json_response({'error':code}, status=status)
        except OSError:
            return web.json_response({'error':'voice_environment_unavailable'}, status=503)
    async def benchmark(request):
        if backend is None:
            return web.json_response({'error':'voice_not_enabled'}, status=403)
        if request.method == 'GET':
            try:
                settings = await backend.call({'action':'check'})
            except (ValueError, OSError):
                return web.json_response({'error':'tts_config_unavailable'}, status=503)
            try:
                history, history_state = backend.benchmark_history.list_runs(), 'available'
            except (OSError, ValueError):
                history, history_state = [], 'unavailable'
            return web.json_response({
                'schema_version': 1,
                'backend': settings.get('backend'),
                'capabilities': settings.get('capabilities'),
                'cases': [item.as_dict() for item in CASES],
                'execution': {'parallel': False, 'retries': 0, 'stores_chat_or_memory': False},
                'history': {'state': history_state, 'runs': history},
            })
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'case_id'} or not isinstance(body['case_id'], str):
                raise ValueError('invalid_body')
            case = case_by_id(body['case_id'])
            if case is None:
                raise ValueError('invalid_body')
            settings = await backend.call({'action':'check'})
            bypass_local_cache = settings.get('backend') in {'voxcpm2', 'cosyvoice3'}
            result = await measure_buffered_speech(
                backend, case, bypass_local_cache=bypass_local_cache,
            )
            result['cache_policy'] = (
                'bypass_local_cache' if bypass_local_cache else 'provider_default'
            )
            result['backend'] = settings.get('backend')
            # 实验条件必须随结果保存，否则不同语速会被错误聚合。
            result['speaking_rate'] = settings.get('speed', 1.0)
            result['capabilities'] = settings.get('capabilities')
            try:
                result['history_run_id'] = backend.benchmark_history.append(result)
                result['history_saved'] = True
            except (OSError, ValueError):
                # 测量已完成时，历史异常不能把真实结果伪装成测试失败。
                result['history_run_id'] = None
                result['history_saved'] = False
            return web.json_response(result)
        except ValueError as error:
            if str(error) == 'invalid_body':
                return web.json_response({'error':'invalid_tts_benchmark_case'}, status=400)
            code, status = speech_failure(error)
            return web.json_response({'error':code}, status=status)
        except OSError:
            return web.json_response({'error':'voice_environment_unavailable'}, status=503)
    app.router.add_get('/api/voice-settings', settings, allow_head=False)
    app.router.add_get('/api/voice-profile', cosy_profile, allow_head=False)
    app.router.add_post('/api/voice-profile', cosy_profile)
    app.router.add_post('/api/voice-profile/preview', cosy_preview)
    app.router.add_post('/api/voice-references', upload_reference)
    app.router.add_post('/api/voice-settings', settings)
    app.router.add_post('/api/voice-settings/preview', settings)
    app.router.add_post('/api/speech', speech)
    app.router.add_get('/api/tts-benchmark', benchmark, allow_head=False)
    app.router.add_post('/api/tts-benchmark', benchmark)
