"""从隔离的 AstrBot 读取陪伴小屋状态。控制台只展示私聊窗口数量。"""
import asyncio
from pathlib import Path

import aiohttp
from aiohttp import web


def register_companion(app, directory: Path):
    async def status(request):
        try:
            key = (directory / 'console-plugin.key').read_text(encoding='utf-8').strip()
        except FileNotFoundError:
            return web.json_response({'state': 'not_configured'})
        except OSError:
            return web.json_response({'state': 'unavailable'})
        url = ('http://127.0.0.1:16185/api/v1/plugins/extensions/'
               'astrbot_plugin_private_companion/host/status')
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as client:
                async with client.get(url, headers={'Authorization': 'Bearer ' + key},
                                      allow_redirects=False) as response:
                    response.raise_for_status()
                    payload = await response.json()
            data = payload['data']
            private_count = sum(target.get('scope_kind') == 'private' for target in data['targets'])
            state = 'ready' if data['enabled'] and data['accepting'] and private_count else 'setup'
            return web.json_response({'state': state, 'private_targets': private_count})
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, KeyError, AttributeError):
            return web.json_response({'state': 'unavailable'})
    app.router.add_get('/api/companion/status', status, allow_head=False)
