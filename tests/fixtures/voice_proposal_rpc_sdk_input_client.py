"""真实3.10有效输入客户端；只输出状态，正式prepare仅由测试驱动执行。"""

import asyncio
import json
from pathlib import Path
import sys
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / "scripts/development/xiaozhi"))
from voice_preemptive import CloseConfirmation, TurnStamp
from voice_proposal_rpc import VoiceProposalRPC
from voice_preemptive_input import capture_effective_voice_input


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


async def run():
    config = json.loads(sys.stdin.readline())
    change = config["change"]
    authority, token = config["authority"], config["token"]
    client = VoiceProposalRPC.from_environment(connection_id="a" * 32,
        environ={"LONGMEMORY_RUNTIME_URL": authority + "/api/internal/memory/prepare",
                 "LONGMEMORY_RUNTIME_TOKEN": token}, timeout_seconds=3, cleanup_seconds=3)
    assert "longmemory" not in sys.modules
    assert Path(sys.modules["voice_proposal_rpc"].__file__).resolve().is_relative_to(root)
    scope, confirmation = TurnStamp(1, 1, 0), CloseConfirmation()
    query, session, round_id = "检查资料", "c" * 32, "d" * 32
    data = {"content": query, "language": "zh", "emotion": "calm", "speaker": "合成声纹", "custom": "原样保留"}
    raw = json.dumps(data, ensure_ascii=False)
    history = [{"role": "user", "content": "合成历史问题"}, {"role": "assistant", "content": "合成历史回答"}]
    def effective(context, actual, *, altered_history=False, altered_date=False, tools=False):
        rows = [{"role": "system", "content": "合成角色\n" + context + ("\n实际日期已变化" if altered_date else "")}]
        rows += [dict(row) for row in history]
        if altered_history:
            rows[-1]["content"] += "实际历史已变化"
        rows.append({"role": "user", "content": actual})
        return capture_effective_voice_input(query, rows, tools_required=tools)
    snapshot = await client.snapshot(scope=scope, query=query, session_id=session)
    assert snapshot["state"] == "ready"
    started = await client.start_effective(scope=scope, snapshot_id=snapshot["snapshot_id"],
        effective_input=effective(snapshot["memory_context"], raw, tools=change == "tools"),
        close_confirmation=confirmation)
    assert started["state"] == ("miss" if change == "tools" else "preparing") and "text" not in started
    print(json.dumps({"phase": "candidate_prepared"}), flush=True)
    assert await asyncio.to_thread(sys.stdin.readline) == "continue\n"

    opener = build_opener(ProxyHandler({}), NoRedirect())
    def post(operation, body):
        req = Request(authority + "/api/internal/memory/" + operation,
            data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method="POST")
        with opener.open(req, timeout=5) as response:
            assert response.status == 200
            return json.load(response)
    # 普通入口接收实际原字符串，并由原有服务提取正文，不在RPC内增加prepare权限。
    prepared = await asyncio.to_thread(post, "prepare", {"version": 1, "query": raw,
        "client_round_id": round_id, "session_id": session})
    assert prepared["memory_protocol"] == 2 and not prepared["command_reply"]
    current = dict(data)
    if change in {"metadata", "speaker", "current"}:
        current[{"metadata": "emotion", "speaker": "speaker", "current": "content"}[change]] = "实际输入已变化"
    actual = json.dumps(current, ensure_ascii=False)
    answer = await client.confirm_effective(scope=scope, snapshot_id=snapshot["snapshot_id"],
        effective_input=effective(prepared["context"], actual, altered_history=change == "history",
                                  altered_date=change == "date", tools=change == "tools"),
        formal_turn_id=prepared["turn_id"], client_round_id=round_id, session_id=session)
    assert answer["state"] == ("adopted" if change == "none" else "miss")
    assert answer["text"] == ("合成回答" if change == "none" else None)
    assert await client.aclose() and confirmation.confirmed
    await asyncio.to_thread(post, "cancel", {"version": 1, "turn_id": prepared["turn_id"],
        "reason": "cancelled", "client_round_id": round_id})
    assert client.snapshot_status()["local_sockets"] == 0
    return {"ok": True, "python": sys.version.split()[0], "host_imported": False, "state": answer["state"], "sockets": 0}


try:
    print(json.dumps(asyncio.run(run())), flush=True)
except Exception as error:
    print(json.dumps({"ok": False, "error": type(error).__name__}), flush=True)
    raise SystemExit(1)
