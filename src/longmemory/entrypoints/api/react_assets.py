"""React 预览只开放构建清单内的 JS/CSS，不把整个目录挂到 HTTP。"""

import json
import secrets
from pathlib import Path

from aiohttp import web


def build_assets(root: Path) -> dict[str, Path]:
    """校验所有清单路径，拒绝越界及符号链接指向外部资源。"""
    root = root.resolve()
    manifest = json.loads((root / '.vite/manifest.json').read_text(encoding='utf-8'))
    result = {}
    for item in manifest.values():
        for name in [item['file'], *item.get('css', [])]:
            path = (root / name).resolve()
            if (not isinstance(name, str) or not name.startswith('assets/') or
                    '\\' in name or '..' in Path(name).parts or
                    not path.is_relative_to(root) or path.suffix not in {'.js', '.css'} or not path.is_file()):
                raise ValueError('invalid build asset')
            result['/react-chat/' + name] = path
    if not result or not (root / 'index.html').is_file():
        raise ValueError('missing build')
    return result


def register_react_routes(app, root: Path):
    async def page(request):
        try:
            build_assets(root)
            content = (root / 'index.html').read_text(encoding='utf-8')
            if content.count('__LONGMEMORY_NONCE__') != 1:
                raise ValueError('missing nonce placeholder')
        except (OSError, ValueError, KeyError, TypeError):
            return web.Response(status=503, text='React 页面尚未构建。请使用原版 /chat，或按 React 前端指南构建。')
        # 仅给此 HTML 响应增加随机样式许可；脚本仍只允许本机资源。
        nonce = secrets.token_hex(24)
        request['react_style_nonce'] = nonce
        return web.Response(text=content.replace('__LONGMEMORY_NONCE__', nonce), content_type='text/html')

    async def asset(request):
        try:
            path = build_assets(root).get(request.path)
            if path is None:
                raise web.HTTPNotFound()
            return web.Response(body=path.read_bytes(), content_type='text/javascript' if path.suffix == '.js' else 'text/css')
        except (OSError, ValueError, KeyError, TypeError):
            raise web.HTTPNotFound()

    app.router.add_get('/chat-react', page)
    app.router.add_get('/device', page)
    app.router.add_get('/memories', page)
    app.router.add_get('/react-chat/{path:.*}', asset)
