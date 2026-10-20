"""冻结AI正式Runtime/路由/真实SDK与3.10真实ASR适配链的合成组合。"""

import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

root, state, scenario = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3]
sys.path[:0] = [str(root / "src"), str(root / "tests/integration"), str(root / "tests/unit/methods")]
from aiohttp import web
from longmemory.bootstrap import build_backend_runtime
from longmemory.bootstrap_hy_daily import OwnedHyModels
from longmemory.application.voice_proposals import VoiceProposalHost
from longmemory.entrypoints.api.routes.voice_proposals import register_voice_proposal_routes
from longmemory.entrypoints.api.routes.memory_runtime import register_memory_runtime_routes
from longmemory.entrypoints.api.security import Sessions, security_middleware
from longmemory.entrypoints.api.chat_backend import ChatBackend
import test_hy_semantic_sdk as sdk_fixture
from test_hy_candidate_response import gateway, complete_wire

assert Path(sys.modules["longmemory.bootstrap"].__file__).resolve().is_relative_to(root)
assert Path(sdk_fixture.__file__).resolve().is_relative_to(root)


async def run(runtime, assembly, model, ledger, received, release):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    assert port not in {8766, 8767, 8768, 8000, 8003, 18000, 18003, 18767, 18768, 18769, 18770}
    token, counts = "e" * 64, {}
    @web.middleware
    async def count_routes(request, handler):
        operation = request.path.rsplit("/", 1)[-1]
        counts[operation] = counts.get(operation, 0) + 1
        return await handler(request)
    app = web.Application(middlewares=[count_routes, security_middleware(f"127.0.0.1:{port}", Sessions(), token)])
    host = VoiceProposalHost(lambda: runtime, enabled=True)
    register_voice_proposal_routes(app, host)
    backend = ChatBackend(runtime.database, SimpleNamespace(), runtime=runtime, sidecar_database=state / "chat.db")
    original_prepare = backend.prepare_round_screen_user
    prepare_count = 0
    def prepare(*args, **kwargs):
        nonlocal prepare_count
        prepare_count += 1
        assert args == ("检查资料",)
        return original_prepare(*args, **kwargs)
    backend.prepare_round_screen_user = prepare
    register_memory_runtime_routes(app, backend)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.SockSite(runner, sock).start()
    child = None
    engine = assembly.method.engine
    try:
        before = sha256((state / "sources.db").read_bytes()).hexdigest()
        diagnostics = engine.sdk_call("diagnostics")
        assert diagnostics["actual_sdk_version"] == "2.0.3" and diagnostics["external_http_attempts"] == 0
        child = await asyncio.create_subprocess_exec(os.environ["LONGMEMORY_TEST_PY310"], "-I", "-X", "utf8", "-B",
            str(Path(__file__).with_name("voice_proposal_adapter_sdk_client.py")), str(root),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        child.stdin.write((json.dumps({"authority": f"http://127.0.0.1:{port}", "token": token, "scenario": scenario}) + "\n").encode())
        await child.stdin.drain()
        phase = json.loads(await asyncio.wait_for(child.stdout.readline(), 15))
        if phase != {"phase": "adapter_prepared"}:
            _, errors = await child.communicate()
            raise AssertionError((phase, errors.decode(errors="replace")[-1200:]))
        assert prepare_count == 0 and not assembly.method.journal.events()
        assert sha256((state / "sources.db").read_bytes()).hexdigest() == before
        after = engine.sdk_call("diagnostics")
        assert after["simulated_model_requests"] == diagnostics["simulated_model_requests"]
        assert after["external_http_attempts"] == 0
        assert engine.sdk_call("semantic_status")["task_counts"] == {}
        snapshot = runtime.candidate_memory_snapshot("检查资料")
        assert len(snapshot["engine"]["items"]) == 6
        if scenario == "tools":
            assert not received and not counts  # 实际functions能力在任何RPC前跳过。
        else:
            until = asyncio.get_running_loop().time() + 3
            while not received or model._candidate_handles:
                assert asyncio.get_running_loop().time() < until
                await asyncio.sleep(.002)
        child.stdin.write(b"continue\n")
        await child.stdin.drain()
        output, errors = await asyncio.wait_for(child.communicate(), 20)
        summary = json.loads(output)
        assert child.returncode == 0, (summary, errors.decode(errors="replace")[-2200:])
        assert summary["python"].startswith("3.10.") and not summary["host_imported"]
        expected = ("suppressed_queued" if scenario == "queued_cancel" else "suppressed" if scenario == "yield_cancel"
                    else "adopted" if scenario in {"reset_worker", "new_turn"} else "miss")
        assert summary["state"] == expected
        expected_requests = 0 if scenario == "tools" else (2 if scenario == "new_turn" else 1)
        assert prepare_count == (2 if scenario == "new_turn" else 1)
        assert counts.get("start", 0) == summary["admitted"] == expected_requests
        assert ledger.status()["attempt_count"] == len(received) == expected_requests
        assert not model._candidate_handles and ledger.status()["unknown_or_inflight"] == 0
        raw = json.dumps({"content": "检查资料", "language": "zh", "emotion": "calm"}, ensure_ascii=False)
        for item in received:
            messages = json.loads(item["body"])["messages"]
            assert messages[-1] == {"role": "user", "content": raw}
            assert all(row["content"] in messages[0]["content"] for row in snapshot["engine"]["items"])
            assert "圆屏实时语音表达规则" in messages[0]["content"]
            assert "当前未配置联网搜索" in messages[0]["content"]
        for secret in (token, "检查资料", "合成回答", "原正式回答"):
            assert secret not in output.decode() + errors.decode(errors="replace")
        return {"ok": True, "state": expected, "prepare_count": prepare_count, "attempt_count": expected_requests,
                "adopted": summary["adopted"], "memory_items": 6, "sdk": "2.0.3", "external_http_attempts": 0}
    finally:
        if child is not None and child.returncode is None:
            child.kill()
            await child.communicate()
        release.set()
        await runner.cleanup()
        assert (await host.aclose())["closed"]


assembly = sdk_fixture.open_backend(state, scenario="projection")
runtime = build_backend_runtime(assembly)
try:
    plans = [{"body": complete_wire()} for _ in range(2 if scenario == "new_turn" else 1)]
    with gateway(state, plans) as (model, ledger, received, _, release):
        model.encoder = SimpleNamespace(identity="synthetic-eight-dimension", encode_query=lambda _text: [1.0] + [0.0] * 7)
        runtime._model_service = OwnedHyModels(model, ledger)
        result = asyncio.run(run(runtime, assembly, model, ledger, received, release))
finally:
    runtime.close()
print(json.dumps(result), flush=True)
