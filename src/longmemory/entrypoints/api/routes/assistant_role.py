"""复用本机认证与 CSRF，只编辑助手表达，不允许修改模型目标或密钥。"""
import sqlite3
from aiohttp import web
from ..role_settings import PRESETS, RoleConflict, preset_prompt


def register_role_routes(app, backend):
    async def settings(request):
        if backend is None:
            return web.json_response({'error': 'chat_disabled'}, status=403)
        try:
            if request.method == 'GET':
                return web.json_response({'current': backend.roles.current(),
                    'presets': [{'name': name, 'prompt': preset_prompt(name)} for name in PRESETS],
                    'web': 'next_turn' if backend.provider != 'fake' else 'fake_no_persona',
                    'device': 'not_synced'})
            if request.content_type != 'application/json':
                raise ValueError('invalid_body')
            # 仅本接口允许较长提示词，其余接口的请求上限保持不变。
            body = await request.clone(client_max_size=80000).json()
            if not isinstance(body, dict) or set(body) != {'expected_revision', 'name', 'prompt'}:
                raise ValueError('invalid_body')
            return web.json_response({'current': backend.roles.save(**body), 'web': 'next_turn' if backend.provider != 'fake' else 'fake_no_persona', 'device': 'not_synced'})
        except RoleConflict:
            return web.json_response({'error': 'role_conflict'}, status=409)
        except ValueError:
            return web.json_response({'error': 'invalid_role'}, status=400)
        except (sqlite3.Error, OSError):
            return web.json_response({'error': 'role_storage_unavailable'}, status=503)

    app.router.add_get('/api/assistant-role', settings, allow_head=False)
    app.router.add_post('/api/assistant-role', settings)
