"""用合成构建文件验证白名单与每次响应的样式 nonce，不访问个人库。"""
import asyncio
import json
import re

import pytest

pytest.importorskip('aiohttp')
from test_console import console
from longmemory.entrypoints.api import server
from longmemory.entrypoints.api.react_assets import build_assets


@pytest.fixture
def built(tmp_path, monkeypatch):
    root = tmp_path / 'web/react-chat/dist'
    (root / '.vite').mkdir(parents=True)
    (root / 'assets').mkdir()
    (root / 'assets/app.js').write_text('export {};', encoding='utf-8')
    (root / 'index.html').write_text('<meta name="style-nonce" content="__LONGMEMORY_NONCE__">', encoding='utf-8')
    (root / '.vite/manifest.json').write_text(json.dumps({'index.html': {'file': 'assets/app.js'}}), encoding='utf-8')
    (tmp_path / 'web/memories.html').write_text('<p>legacy memory fallback</p>', encoding='utf-8')
    monkeypatch.setattr(server, 'ROOT', tmp_path)
    return root


def test_react_nonce_and_resource_whitelist(built):
    async def run():
        async with console() as (client, base, _):
            nonces = []
            for route in ('/chat-react', '/device', '/memories', '/settings', '/experiments-react'):
                response = await client.get(base + route)
                assert response.status == 200
                content = await response.text()
                nonce = re.search('content="([a-f0-9]+)"', content).group(1)
                nonces.append(nonce)
                csp = response.headers['Content-Security-Policy']
                assert "script-src 'self'" in csp and f"'nonce-{nonce}'" in csp
                assert 'unsafe-inline' not in csp and 'unsafe-eval' not in csp
            assert nonces[0] != nonces[1]
            response = await client.get(base + '/react-chat/assets/app.js')
            assert response.status == 200
            assert 'nonce-' not in response.headers['Content-Security-Policy']
            for path in ['/react-chat/.vite/manifest.json', '/react-chat/index.html', '/react-chat/src/main.tsx', '/react-chat/assets/no.js']:
                assert (await client.get(base + path)).status == 404
            assert (await client.get(base + '/chat-react', headers={'Origin': 'https://evil.invalid'})).status == 403
            assert (await client.get(base + '/memories-legacy')).status == 200
    asyncio.run(run())


@pytest.mark.parametrize('name', ['../secret.js', 'assets/../../secret.js', 'assets/x.txt', 'C:/secret.js'])
def test_react_rejects_unsafe_manifest(built, name):
    (built / '.vite/manifest.json').write_text(json.dumps({'x': {'file': name}}), encoding='utf-8')
    with pytest.raises(ValueError):
        build_assets(built)


def test_react_missing_build_is_explicit(built):
    (built / '.vite/manifest.json').write_text('{}', encoding='utf-8')
    async def run():
        async with console() as (client, base, _):
            response = await client.get(base + '/chat-react')
            assert response.status == 503
            assert '/chat' in await response.text()
            assert 'nonce-' not in response.headers['Content-Security-Policy']
    asyncio.run(run())
