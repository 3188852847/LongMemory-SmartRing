"""TTS 选择只修改下次启动指针，不执行热切换。"""

import asyncio

from test_console import console, login
from longmemory.infrastructure.config.tts_backends import TTSBackendStore


def test_tts_backend_selection_is_csrf_protected_and_deferred(tmp_path):
    store = TTSBackendStore(tmp_path, current_backend="edge")

    async def run():
        async with console(tts_backend_store=store) as (client, base, _):
            headers = await login(client, base)
            listing = await client.get(base + "/api/tts-backends")
            assert listing.status == 200
            assert (await listing.json())["next_start_backend"] == "edge"
            url = base + "/api/tts-backends/selection"
            assert (await client.put(url, json={"backend": "sanotts"})).status == 403
            changed = await client.put(url, headers=headers, json={"backend": "sanotts"})
            assert changed.status == 200
            assert (await changed.json())["next_start_backend"] == "sanotts"
            assert (await client.put(url, headers=headers, json={"backend": "unknown"})).status == 400

    asyncio.run(run())
