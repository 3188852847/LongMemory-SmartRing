"""真实3.10客户端驱动；所有内容合成，分阶段检查提前写入边界。"""

import asyncio
import json
from pathlib import Path
import sys
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"scripts/development/xiaozhi"))
from voice_preemptive import CloseConfirmation, TurnStamp
from voice_proposal_rpc import VoiceProposalRPC


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


async def run():
    config = json.loads(sys.stdin.readline())
    authority, token = config["authority"], config["token"]
    client = VoiceProposalRPC.from_environment(connection_id="a"*32,
        environ={"LONGMEMORY_RUNTIME_URL": authority+"/api/internal/memory/prepare",
                 "LONGMEMORY_RUNTIME_TOKEN": token}, timeout_seconds=3, cleanup_seconds=3)
    assert "longmemory" not in sys.modules
    scope, confirmation = TurnStamp(1, 1, 0), CloseConfirmation()
    query, session, round_id = "检查资料", "c"*32, "d"*32
    snapshot = await client.snapshot(scope=scope, query=query, session_id=session)
    assert snapshot["state"] == "ready"
    messages = [["system", "合成角色\n"+snapshot["memory_context"]]]
    started = await client.start(scope=scope, snapshot_id=snapshot["snapshot_id"],
        messages=messages, close_confirmation=confirmation)
    assert started["state"] == "preparing" and "text" not in started
    print(json.dumps({"phase":"candidate_prepared"}), flush=True)
    assert await asyncio.to_thread(sys.stdin.readline) == "continue\n"

    # 这是正常正式流程的驱动，不向仅有五种操作的RPC客户端增加prepare权限。
    opener = build_opener(ProxyHandler({}), NoRedirect())
    def post(operation, body):
        req = Request(authority+"/api/internal/memory/"+operation,
            data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"}, method="POST")
        with opener.open(req, timeout=5) as response:
            assert response.status == 200
            return json.load(response)
    prepared = await asyncio.to_thread(post, "prepare", {"version":1,"query":query,
        "client_round_id":round_id,"session_id":session})
    assert prepared["memory_protocol"] == 2 and not prepared["command_reply"]
    formal_messages = [["system", "合成角色\n"+prepared["context"]]]
    answer = await client.confirm(scope=scope, snapshot_id=snapshot["snapshot_id"], query=query,
        messages=formal_messages, formal_turn_id=prepared["turn_id"], client_round_id=round_id, session_id=session)
    expected = config["expected_hit"]
    assert answer["state"] == ("adopted" if expected else "miss")
    assert answer["text"] == ("合成回答" if expected else None)
    assert await client.aclose() and confirmation.confirmed
    # 没有设备播放，不发助手完成回执；仅正常取消本次合成正式轮。
    await asyncio.to_thread(post, "cancel", {"version":1,"turn_id":prepared["turn_id"],
        "reason":"cancelled","client_round_id":round_id})
    assert client.snapshot_status()["local_sockets"] == 0
    return {"ok":True,"python":sys.version.split()[0],"host_imported":False,
            "state":answer["state"],"sockets":0}


try:
    print(json.dumps(asyncio.run(run())), flush=True)
except Exception as error:
    print(json.dumps({"ok":False,"error":type(error).__name__}), flush=True)
    raise SystemExit(1)
