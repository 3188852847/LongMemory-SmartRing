"""固定SDK＋真实Runtime/HTTP；模型禁网替身、合成非空库，不触达日用。"""

import asyncio
from hashlib import sha256
import os
from pathlib import Path
import socket
from types import SimpleNamespace

from aiohttp import ClientSession, web
import pytest

from longmemory.bootstrap import build_backend_runtime
from longmemory.entrypoints.api.routes.memory_engine import register_memory_engine_routes

import test_hy_semantic_sdk as sdk_fixture


SDK = Path(os.environ.get("LONGMEMORY_TEST_HY_PYTHON", "missing-owner-sdk"))
pytestmark = pytest.mark.skipif(not SDK.is_file(), reason="explicit owner-installed fixed SDK required")


@pytest.mark.parametrize("scenario,expected_hit", [("projection", True), ("normal", False)])
def test_actual_sdk_nonempty_candidate_formal_context_claim_and_native_http_errors(tmp_path, scenario, expected_hit):
    # projection含非空画像/事实/意图；normal另含历史链，正式召回会展开历史而
    # 候选明确latest-only，此时必须回退。不能为制造命中删掉正式上下文或来源。
    assembly = sdk_fixture.open_backend(tmp_path, scenario=scenario)
    runtime = build_backend_runtime(assembly)
    engine = assembly.method.engine
    runtime._model_service = SimpleNamespace(gateway=SimpleNamespace(encoder=SimpleNamespace(identity="synthetic"),
        embed=lambda *_args: {"data": [{"embedding": [1.0]+[0.0]*7}]}),
        close=lambda: None, pause_notice=lambda: None, status=lambda: {"state": "available"})
    try:
        before = engine.sdk_call("diagnostics")
        source_digest = sha256((tmp_path / "sources.db").read_bytes()).hexdigest()
        receipt = runtime.candidate_memory_snapshot("检查资料")
        assert receipt["engine"]["read_status"] == "readable" and receipt["engine"]["items"]
        assert sha256((tmp_path / "sources.db").read_bytes()).hexdigest() == source_digest
        assert engine.sdk_call("diagnostics")["simulated_model_requests"] == before["simulated_model_requests"]
        assert engine.sdk_call("semantic_status")["task_counts"] == {}
        prepared, _ = runtime.prepare_round_screen("检查资料", client_round_id="b"*32, session_id="a"*32)
        same_context = "\n".join(row["content"] for row in receipt["engine"]["items"]) == prepared.support.context
        assert same_context is expected_hit
        assert runtime._proposal_formal[prepared.event.event_id]["eligible"], (
            prepared.memory_command, prepared.follow_up_suggestion)
        assert engine.candidate_validate(snapshot_token=receipt["engine"]["snapshot_token"],
            memory_digest=receipt["engine"]["memory_digest"])["valid"]
        claimed = runtime.claim_candidate_memory(receipt, query="检查资料", formal_turn_id=prepared.event.event_id,
            client_round_id="b"*32, session_id="a"*32, claim=lambda: "合成候选命中")
        assert claimed == ("合成候选命中" if expected_hit else None)
        assert engine.sdk_call("diagnostics")["external_http_attempts"] == 0

        async def http():
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            app = web.Application()
            register_memory_engine_routes(app, lambda: (_ for _ in ()).throw(AssertionError("lazy startup forbidden")),
                snapshot_runtime=lambda: runtime, allow_correction=True)
            runner = web.AppRunner(app)
            await runner.setup()
            await web.SockSite(runner, sock).start()
            try:
                async with ClientSession() as client:
                    path = f"http://127.0.0.1:{port}/api/memory-engine/hy/semantic"
                    async with client.get(path+"/status") as response:
                        body = await response.json()
                        assert response.status == 200 and body["protocol"] == 2
                        assert body["graph_available"] and body["runtime"]["write_enabled"]
                        assert body["execution_authorized"] is False
                    async with client.get(path+"/tasks/management:does-not-exist") as response:
                        assert response.status == 404
                        assert (await response.json())["error"] == "hy_semantic_task_not_found"
                    runtime.configure(write_enabled=False, use_enabled=True)
                    async with client.post(path+"/tasks", json={"task_id":"manual:blocked","kind":"evolve","max_batches":1}) as response:
                        assert response.status == 403
                    assert engine.sdk_call("semantic_status")["paused"]
            finally:
                await runner.cleanup()
        asyncio.run(http())
    finally:
        runtime.close()
