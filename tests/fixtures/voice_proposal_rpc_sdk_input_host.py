"""冻结AI业务源码+真实SDK+正式路由；独立进程隔离导入与合成状态。"""

import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

root, state = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
change = sys.argv[3]
sys.path[:0] = [str(root / "src"), str(root / "tests/integration"), str(root / "tests/unit/methods")]
from aiohttp import web
from longmemory.bootstrap import build_backend_runtime
from longmemory.bootstrap_hy_daily import OwnedHyModels
from longmemory.application.voice_proposals import VoiceProposalHost
from longmemory.entrypoints.api.routes.voice_proposals import register_voice_proposal_routes
from longmemory.entrypoints.api.routes.memory_runtime import register_memory_runtime_routes
from longmemory.entrypoints.api.security import Sessions, security_middleware
import test_hy_semantic_sdk as sdk_fixture
from test_hy_candidate_response import gateway, complete_wire

assert Path(sys.modules["longmemory.bootstrap"].__file__).resolve().is_relative_to(root)
assert Path(sdk_fixture.__file__).resolve().is_relative_to(root)


async def run(runtime, assembly, model, ledger, received, release):
    engine = assembly.method.engine
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    assert port not in {8766, 8767, 8768, 8000, 8003, 18000, 18003, 18767, 18768, 18769, 18770}
    token = "e" * 64
    app = web.Application(middlewares=[security_middleware(f"127.0.0.1:{port}", Sessions(), token)])
    host = VoiceProposalHost(lambda: runtime, enabled=True)
    register_voice_proposal_routes(app, host)
    prepare_count = 0
    def prepare(*args, **kwargs):
        nonlocal prepare_count
        prepare_count += 1
        assert args == ("检查资料",)  # 正式路由确实提取正文，未把JSON元数据归档为正文。
        return runtime.prepare_round_screen(*args, **kwargs)
    register_memory_runtime_routes(app, SimpleNamespace(memory_runtime=lambda: runtime, prepare_round_screen_user=prepare))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.SockSite(runner, sock).start()
    child = None
    try:
        before = sha256((state / "sources.db").read_bytes()).hexdigest()
        diagnostics = engine.sdk_call("diagnostics")
        assert diagnostics["actual_sdk_version"] == "2.0.3" and diagnostics["external_http_attempts"] == 0
        child = await asyncio.create_subprocess_exec(os.environ["LONGMEMORY_TEST_PY310"], "-I", "-X", "utf8", "-B",
            str(Path(__file__).with_name("voice_proposal_rpc_sdk_input_client.py")), str(root),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        child.stdin.write((json.dumps({"authority": f"http://127.0.0.1:{port}", "token": token, "change": change}) + "\n").encode())
        await child.stdin.drain()
        phase = json.loads(await asyncio.wait_for(child.stdout.readline(), 12))
        assert phase == {"phase": "candidate_prepared"}, phase
        assert prepare_count == 0
        assert sha256((state / "sources.db").read_bytes()).hexdigest() == before
        assert not assembly.method.journal.events()
        after = engine.sdk_call("diagnostics")
        assert after["simulated_model_requests"] == diagnostics["simulated_model_requests"]
        assert after["external_http_attempts"] == 0
        assert engine.sdk_call("semantic_status")["task_counts"] == {}
        snapshot = runtime.candidate_memory_snapshot("检查资料")
        assert len(snapshot["engine"]["items"]) == 6
        child.stdin.write(b"continue\n")
        await child.stdin.drain()
        output, errors = await asyncio.wait_for(child.communicate(), 15)
        summary = json.loads(output)
        assert child.returncode == 0, (summary, errors.decode(errors="replace")[-1600:])
        assert summary["python"].startswith("3.10.") and not summary["host_imported"]
        assert prepare_count == 1
        assert summary["state"] == ("adopted" if change == "none" else "miss")
        assert not model._candidate_handles and ledger.status()["unknown_or_inflight"] == 0
        assert ledger.status()["attempt_count"] == len(received) == int(change != "tools")
        if received:
            messages = json.loads(received[0]["body"])["messages"]
            expected_raw = json.dumps({"content": "检查资料", "language": "zh", "emotion": "calm",
                "speaker": "合成声纹", "custom": "原样保留"}, ensure_ascii=False)
            assert messages[-1] == {"role": "user", "content": expected_raw}
            assert messages[1:3] == [{"role": "user", "content": "合成历史问题"}, {"role": "assistant", "content": "合成历史回答"}]
            assert all(row["content"] in messages[0]["content"] for row in snapshot["engine"]["items"])
        # 仅状态进入父进程；不回显实际消息、凭据或摘要。
        for secret in (token, "合成声纹", "原样保留", "合成回答"):
            assert secret not in output.decode() + errors.decode(errors="replace")
        return {"ok": True, "state": summary["state"], "prepare_count": prepare_count,
                "attempt_count": len(received), "memory_items": 6, "sdk": "2.0.3", "external_http_attempts": 0}
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
    with gateway(state, [{"body": complete_wire()}]) as (model, ledger, received, _, release):
        model.encoder = SimpleNamespace(identity="synthetic-eight-dimension", encode_query=lambda _text: [1.0] + [0.0] * 7)
        runtime._model_service = OwnedHyModels(model, ledger)
        result = asyncio.run(run(runtime, assembly, model, ledger, received, release))
finally:
    runtime.close()
print(json.dumps(result), flush=True)
