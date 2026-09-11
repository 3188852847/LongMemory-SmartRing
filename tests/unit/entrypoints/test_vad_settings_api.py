"""VAD 网页窄接口只允许三个预设和摘要化并发保护。"""

import asyncio

from test_console import console, login
from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.entrypoints.api import server
from longmemory.entrypoints.api.vad_settings import _public_status
from longmemory.entrypoints.api.chat_backend import ChatBackend
from longmemory.methods.longmemory_v1.method import LongMemoryV1


def test_vad_api_requires_xiaozhi_and_accepts_only_whitelisted_profile(tmp_path, monkeypatch):
    database = tmp_path / "synthetic.db"
    LongMemoryV1(database).close()
    chat = ChatBackend(database, FakeAnswerGenerator())
    calls = []

    class Fake:
        def __init__(self, *args):
            pass

        async def call(self, body):
            calls.append(body)
            return {
                "profile": body.get("profile", "normal"),
                "values": {"threshold": 0.5, "threshold_low": 0.3,
                           "min_silence_duration_ms": 600},
                "digest": "b" * 64,
                "runtime": "unverified",
            }

    monkeypatch.setattr(server, "VadSettings", Fake)

    async def run():
        async with console(chat_backend=chat) as (client, base, _):
            await login(client, base)
            assert (await client.get(base + "/api/vad-settings")).status == 403

        async with console(chat_backend=chat, xiaozhi_server=tmp_path) as (client, base, _):
            headers = await login(client, base)
            response = await client.get(base + "/api/vad-settings")
            assert response.status == 200
            assert (await response.json())["profile"] == "normal"
            assert (await client.put(
                base + "/api/vad-settings", headers=headers,
                json={"profile": "maximum", "expected_digest": "a" * 64},
            )).status == 409
            changed = await client.put(
                base + "/api/vad-settings", headers=headers,
                json={"profile": "noisy", "expected_digest": "a" * 64},
            )
            assert changed.status == 200
            assert (await changed.json())["profile"] == "noisy"

    asyncio.run(run())
    assert calls == [
        {"action": "status"},
        {"action": "apply", "profile": "noisy", "expected_digest": "a" * 64},
    ]


def test_vad_projection_drops_private_or_future_subprocess_fields():
    projected = _public_status({
        "profile": "noisy",
        "values": {"threshold": 0.7, "threshold_low": 0.45,
                   "min_silence_duration_ms": 650},
        "digest": "a" * 64,
        "runtime": "unverified",
        "backup": ".config.yaml.vad-private.bak",
        "future_private_field": "must-not-cross-http-boundary",
    })
    assert set(projected) == {
        "profile", "values", "digest", "runtime", "running_profile", "restart_required",
    }
    assert projected["running_profile"] is None
    assert projected["restart_required"] is False


def test_vad_projection_marks_saved_profile_waiting_for_restart():
    projected = _public_status({
        "profile": "close_talk",
        "values": {"threshold": 0.82, "threshold_low": 0.55,
                   "min_silence_duration_ms": 700},
        "digest": "a" * 64,
    }, running_profile="normal")
    assert projected["running_profile"] == "normal"
    assert projected["restart_required"] is True
