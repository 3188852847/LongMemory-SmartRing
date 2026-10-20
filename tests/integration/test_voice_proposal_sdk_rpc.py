"""实际SDK/Managed/Runtime/AF网关/正式鉴权路由/3.10 RPC组合；仅合成回环。"""

import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

from aiohttp import web
import pytest

from longmemory.bootstrap import build_backend_runtime
from longmemory.bootstrap_hy_daily import OwnedHyModels
from longmemory.application.voice_proposals import VoiceProposalHost
from longmemory.entrypoints.api.routes.voice_proposals import register_voice_proposal_routes
from longmemory.entrypoints.api.routes.memory_runtime import register_memory_runtime_routes
from longmemory.entrypoints.api.security import Sessions, security_middleware
import test_hy_semantic_sdk as sdk_fixture

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tests/unit/methods"))
from test_hy_candidate_response import gateway, complete_wire

PY310 = Path(os.environ.get("LONGMEMORY_TEST_PY310", "missing-owner-python"))
SDK = Path(os.environ.get("LONGMEMORY_TEST_HY_PYTHON", "missing-owner-sdk"))
pytestmark = pytest.mark.skipif(not SDK.is_file() or not PY310.is_file(), reason="explicit fixed SDK and owner voice 3.10 required")


@pytest.mark.parametrize("scenario,policy_change,expected_hit", [
    ("projection", False, True), ("normal", False, False), ("projection", True, False)])
def test_actual_sdk_and_cross_python_rpc_adopts_only_same_formal_memory_and_policy(tmp_path, scenario, policy_change, expected_hit):
    assembly = sdk_fixture.open_backend(tmp_path, scenario=scenario)
    runtime = build_backend_runtime(assembly)
    engine = assembly.method.engine
    with gateway(tmp_path, [{"body":complete_wire()}]) as (model, ledger, received, _, release):
        model.encoder = SimpleNamespace(identity="synthetic-eight-dimension",
            encode_query=lambda _text: [1.0]+[0.0]*7)
        runtime._model_service = OwnedHyModels(model, ledger)
        try:
            async def run():
                sock = socket.socket()
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
                assert port not in {8766,8767,8768,8000,8003,18000,18003,18767,18768,18769,18770}
                token = "e"*64
                app = web.Application(middlewares=[security_middleware(f"127.0.0.1:{port}", Sessions(), token)])
                host = VoiceProposalHost(lambda:runtime, enabled=True)
                register_voice_proposal_routes(app, host)
                register_memory_runtime_routes(app, SimpleNamespace(memory_runtime=lambda:runtime,
                    prepare_round_screen_user=runtime.prepare_round_screen))
                runner = web.AppRunner(app)
                await runner.setup()
                await web.SockSite(runner, sock).start()
                child = None
                try:
                    before = sha256((tmp_path/"sources.db").read_bytes()).hexdigest()
                    diagnostics = engine.sdk_call("diagnostics")
                    child = await asyncio.create_subprocess_exec(str(PY310), "-I", "-X", "utf8", "-B",
                        str(ROOT/"tests/fixtures/voice_proposal_rpc_sdk_client.py"),
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    child.stdin.write((json.dumps({"authority":f"http://127.0.0.1:{port}","token":token,
                        "expected_hit":expected_hit})+"\n").encode())
                    await child.stdin.drain()
                    phase = json.loads(await asyncio.wait_for(child.stdout.readline(), 12))
                    assert phase == {"phase":"candidate_prepared"}, phase
                    assert sha256((tmp_path/"sources.db").read_bytes()).hexdigest() == before
                    assert not assembly.method.journal.events()
                    assert engine.sdk_call("diagnostics")["simulated_model_requests"] == diagnostics["simulated_model_requests"]
                    assert engine.sdk_call("semantic_status")["task_counts"] == {}
                    snapshot = runtime.candidate_memory_snapshot("检查资料")
                    if scenario == "projection":
                        assert len(snapshot["engine"]["items"]) == 6
                    if policy_change:
                        runtime.configure(write_enabled=False, use_enabled=True)
                    child.stdin.write(b"continue\n")
                    await child.stdin.drain()
                    output, errors = await asyncio.wait_for(child.communicate(), 15)
                    summary = json.loads(output)
                    assert child.returncode == 0, (summary, errors.decode(errors="replace")[-1600:])
                    assert summary["python"].startswith("3.10.") and not summary["host_imported"]
                    assert summary["state"] == ("adopted" if expected_hit else "miss")
                    assert not model._candidate_handles and ledger.status()["unknown_or_inflight"] == 0
                    assert ledger.status()["attempt_count"] == 1
                    assert len(received) == 1
                    if scenario == "projection":
                        # 实际送入模型的系统消息保留全部六项，不在宿主截为5条。
                        sent = json.loads(received[0]["body"])["messages"][0]["content"]
                        assert all(row["content"] in sent for row in snapshot["engine"]["items"])
                finally:
                    if child is not None and child.returncode is None:
                        child.kill()
                        await child.communicate()
                    release.set()
                    await runner.cleanup()
                    assert (await host.aclose())["closed"]
            asyncio.run(run())
        finally:
            runtime.close()
