"""复用本机认证与 CSRF，只编辑助手表达，不允许修改模型目标或密钥。"""
import sqlite3
from aiohttp import web
from ..role_settings import PRESETS, RoleConflict, preset_prompt


def register_role_routes(app, backend, device_role=None):
    async def settings(request):
        if backend is None:
            return web.json_response({'error': 'chat_disabled'}, status=403)
        try:
            if request.method == 'GET':
                return web.json_response({'current': backend.roles.current(),
                    'history': backend.roles.history(),
                    'presets': [{'name': name, 'prompt': preset_prompt(name)} for name in PRESETS],
                    'web': 'next_turn' if backend.provider != 'fake' else 'fake_no_persona',
                    'device': 'check_required' if device_role else 'not_synced'})
            if request.content_type != 'application/json':
                raise ValueError('invalid_body')
            # 仅本接口允许较长提示词，其余接口的请求上限保持不变。
            body = await request.clone(client_max_size=80000).json()
            if not isinstance(body, dict) or set(body) != {'expected_revision', 'name', 'prompt'}:
                raise ValueError('invalid_body')
            current = backend.roles.save(**body)
            return web.json_response({'current': current, 'history': backend.roles.history(),
                'web': 'next_turn' if backend.provider != 'fake' else 'fake_no_persona', 'device': 'not_synced'})
        except RoleConflict:
            return web.json_response({'error': 'role_conflict'}, status=409)
        except ValueError:
            return web.json_response({'error': 'invalid_role'}, status=400)
        except (sqlite3.Error, OSError):
            return web.json_response({'error': 'role_storage_unavailable'}, status=503)

    app.router.add_get('/api/assistant-role', settings, allow_head=False)
    app.router.add_post('/api/assistant-role', settings)

    async def device(request):
        if device_role is None:
            return web.json_response({'error': 'device_sync_not_enabled'}, status=403)
        try:
            if request.method == 'GET':
                return web.json_response(await device_role.check())
            if request.content_type != 'application/json':
                raise ValueError('invalid_body')
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'token'} or not isinstance(body['token'], str) or len(body['token']) != 48:
                raise ValueError('invalid_body')
            return web.json_response(await device_role.apply(body['token']))
        except ValueError as error:
            # 仅允许本层定义的错误码；不将第三方异常原文回传。
            allowed = {'device_server_unavailable', 'device_sync_result_unknown', 'device_role_sync_failed',
                       'device_sync_busy', 'device_preview_expired', 'role_changed_recheck', 'invalid_body', 'invalid_memory_marker'}
            code = str(error) if str(error) in allowed else 'device_role_sync_failed'
            return web.json_response({'error': code}, status=409)
        except (sqlite3.Error, OSError):
            return web.json_response({'error': 'role_storage_unavailable'}, status=503)

    app.router.add_get('/api/assistant-role/device', device, allow_head=False)
    app.router.add_post('/api/assistant-role/device', device)
