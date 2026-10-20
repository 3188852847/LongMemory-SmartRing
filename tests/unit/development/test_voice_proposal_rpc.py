import asyncio
import importlib.util
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

import pytest

from test_voice_preemptive import p


ROOT = Path(__file__).resolve().parents[3]
sys.modules["voice_preemptive"] = p
SPEC = importlib.util.spec_from_file_location("ae_voice_proposal_rpc", ROOT / "scripts/development/xiaozhi/voice_proposal_rpc.py")
r = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = r
SPEC.loader.exec_module(r)
TOKEN = "b" * 64


def environment(url="http://127.0.0.1:19231/api/internal/memory/prepare"):
    return {"LONGMEMORY_RUNTIME_URL": url, "LONGMEMORY_RUNTIME_TOKEN": TOKEN}


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:19231/api/internal/memory/prepare",
    "http://localhost:19231/api/internal/memory/prepare",
    "http://example.invalid:19231/api/internal/memory/prepare",
    "http://127.0.0.1:19231/api/internal/memory/prepare?x=1",
    "http://127.0.0.1:19231/api/internal/memory/prepare#fragment",
    "http://user@127.0.0.1:19231/api/internal/memory/prepare",
    "http://127.0.0.1/api/internal/memory/prepare",
    "http://127.0.0.1:0/api/internal/memory/prepare",
    "http://127.0.0.1:19231/api/internal/memory/complete",
    "http://127.0.0.1:19231/api/internal/memory/prepare/../prepare",
])
def test_only_inherited_exact_loopback_runtime_origin_is_allowed(url):
    with pytest.raises(r.ProposalRPCError, match="authority_invalid"):
        r.VoiceProposalRPC.from_environment(connection_id="a" * 32, environ=environment(url))


def test_bad_token_identifier_and_bounds_do_not_create_transport():
    for value in ("short", "b" * 64 + "\r\nX: bad", None):
        env = environment()
        env["LONGMEMORY_RUNTIME_TOKEN"] = value
        with pytest.raises(r.ProposalRPCError):
            r.VoiceProposalRPC.from_environment(connection_id="a" * 32, environ=env)
    for value in (0, -1, float("nan"), True, 11):
        with pytest.raises(r.ProposalRPCError):
            r.VoiceProposalRPC.from_environment(connection_id="a" * 32, environ=environment(), timeout_seconds=value)


def test_fixed_route_table_excludes_formal_prepare_and_is_immutable():
    assert set(r.ROUTES) == {"snapshot", "start", "confirm", "cancel", "close"}
    assert all(path.startswith("/api/internal/memory/proposals/") for path in r.ROUTES.values())
    with pytest.raises(TypeError):
        r.ROUTES["prepare"] = "/api/internal/memory/prepare"


def test_bound_connection_id_is_read_only():
    client = r.VoiceProposalRPC.from_environment(connection_id="a" * 32, environ=environment())
    with pytest.raises(AttributeError):
        client.connection_id = "c" * 32


def test_older_turn_cannot_cancel_new_turn_and_higher_epoch_cancel_is_allowed():
    async def run():
        client = r.VoiceProposalRPC.from_environment(connection_id="a" * 32, environ=environment())
        calls = []
        async def post(operation, body, **kwargs):
            calls.append((operation, body))
            if operation == "start":
                return {"version": 1, "state": "preparing", "reason_code": None}
            return {"version": 1, "state": "cancelled", "owned_upstream_exited": True,
                    "provider_compute_stopped": False}
        client._post = post
        proof = p.CloseConfirmation()
        await client.start(scope=p.TurnStamp(2, 1, 1), snapshot_id="e" * 32,
                           messages=[["system", "合成角色"]], close_confirmation=proof)
        with pytest.raises(r.ProposalRPCError, match="cancel_scope_invalid"):
            await client.cancel(scope=p.TurnStamp(1, 1, 1))
        assert len(calls) == 1 and not proof.confirmed
        await client.cancel(scope=p.TurnStamp(2, 1, 2))
        assert len(calls) == 2 and calls[-1][1]["cancel_epoch"] == 2 and proof.confirmed
    asyncio.run(run())


def test_local_bad_messages_and_versions_never_send_network():
    async def run():
        client = r.VoiceProposalRPC.from_environment(connection_id="a" * 32, environ=environment())
        scope = p.TurnStamp(0, 1, 0)
        with pytest.raises(r.ProposalRPCError):
            await client.start(scope=scope, snapshot_id="e" * 32,
                               messages=[["system", "one"], ["system", "two"]])
        with pytest.raises(r.ProposalRPCError):
            await client.start(scope=scope, snapshot_id="e" * 32,
                               messages=[{"role": "system", "content": "wrong shape"}])
        with pytest.raises(r.ProposalRPCError):
            await client.snapshot(scope=p.TurnStamp(2**63, 0, 0), query="合成问题", session_id="c" * 32)
        assert client.snapshot_status()["requests"] == 0
        assert TOKEN not in repr(client) and TOKEN not in repr(client.snapshot_status())
    asyncio.run(run())


def run_two_processes(action):
    python310 = os.environ.get("LONGMEMORY_TEST_PY310")
    if not python310:
        pytest.skip("explicit installed Python3.10 required for two-process contract test")
    assert Path(python310).is_file()
    server_script = ROOT / "tests/fixtures/voice_proposal_rpc_host.py"
    client_script = ROOT / "tests/fixtures/voice_proposal_rpc_client.py"
    env = dict(os.environ, RPC_TEST_TOKEN=TOKEN)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    server = subprocess.Popen([sys.executable, "-X", "utf8", "-B", str(server_script), action],
        cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", creationflags=creationflags)
    ready = queue.Queue()
    thread = threading.Thread(target=lambda: ready.put(server.stdout.readline()), daemon=True)
    thread.start()
    try:
        line = ready.get(timeout=5)
        port = json.loads(line)["port"]
        assert port not in {8766, 8767, 8768, 8000, 8003, 18000, 18003, 18767, 18768, 18769, 18770}
        client_env = dict(env, **environment(f"http://127.0.0.1:{port}/api/internal/memory/prepare"))
        if action == "wrong_auth":
            client_env["LONGMEMORY_RUNTIME_TOKEN"] = "f" * 64
        client = subprocess.run([python310, "-X", "utf8", "-B", str(client_script), action],
            cwd=ROOT, env=client_env, text=True, encoding="utf-8", capture_output=True, timeout=8,
            creationflags=creationflags)
        assert client.returncode == 0, (client.stdout, client.stderr)
        output = json.loads(client.stdout.strip())
        assert output["ok"]
        tail, error = server.communicate("stop\n", timeout=4)
        assert server.returncode == 0
        stats = json.loads(tail.strip())
        for text in (client.stdout, client.stderr, tail, error):
            assert TOKEN not in text
            assert "合成有效回答" not in text and "不应提前送出" not in text and "无糖茶" not in text
        assert stats["counts"].get("forbidden_path", 0) == 0
        return output, stats
    finally:
        if server.poll() is None:
            server.terminate()  # 本测试创建的精确子进程，不枚举或停止其他Python。
            server.communicate(timeout=3)
        thread.join(timeout=1)


def test_real_python310_client_and_host_subprocess_roundtrip_with_nonempty_context():
    output, stats = run_two_processes("roundtrip")
    assert output["python"] == "3.10.20" and not output["host_imported"]
    assert stats["counts"] == {"snapshot": 1, "start": 1, "preparing": 1, "confirm": 1, "close": 1}
    assert output["active"] == stats["active"] == 0


@pytest.mark.parametrize("action", ["slow_start", "disconnect_start", "leak_start"])
def test_ambiguous_start_never_retries_and_retains_slot_until_scoped_cancel_ack(action):
    output, stats = run_two_processes(action)
    assert stats["counts"]["start"] == 1 and stats["counts"]["cancel"] == 1
    assert stats["counts"].get("confirm", 0) == 0
    assert output["active"] == stats["active"] == 0


@pytest.mark.parametrize("action", ["slow_confirm", "epoch_race", "bad_confirm"])
def test_cancel_late_epoch_and_miss_cannot_publish_old_answer(action):
    output, stats = run_two_processes(action)
    assert stats["counts"]["start"] == stats["counts"]["confirm"] == 1
    assert stats["counts"]["cancel"] == 1 and output["active"] == 0


@pytest.mark.parametrize("action", ["closing", "bad_ack"])
def test_unconfirmed_or_false_provider_guarantee_keeps_compute_slot(action):
    output, stats = run_two_processes(action)
    assert output["active"] == 1 and not output["closed_confirmed"]
    assert stats["counts"]["start"] == 1


@pytest.mark.parametrize("action", ["redirect", "bad_json", "chunked"])
def test_bad_transport_response_cannot_redirect_or_start_model(action):
    output, stats = run_two_processes(action)
    assert output["rejected"] and stats["counts"]["snapshot"] == 1
    assert stats["counts"].get("start", 0) == 0


def test_tools_required_is_a_miss_and_never_prepares_model():
    output, stats = run_two_processes("tools_required")
    assert output["tools_executed"] is False
    assert stats["counts"]["start"] == 1 and stats["counts"].get("preparing", 0) == 0
    assert stats["counts"].get("confirm", 0) == 0


def test_rejected_runtime_auth_does_not_start_or_retry_candidate():
    output, stats = run_two_processes("wrong_auth")
    assert output["rejected"] and stats["counts"] == {}


def test_large_nonempty_memory_json_body_is_not_limited_by_header_buffer():
    output, stats = run_two_processes("large_context")
    assert output["active"] == 0
    assert stats["counts"]["snapshot"] == stats["counts"]["start"] == stats["counts"]["confirm"] == 1
