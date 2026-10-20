"""由真实Python3.10子进程运行；输出只有状态，绝不回显Token/正文。"""

import asyncio
import json
from pathlib import Path
import sys


root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "scripts/development/xiaozhi"))
from voice_preemptive import CloseConfirmation, TurnStamp
from voice_proposal_rpc import ProposalRPCError, VoiceProposalRPC
from voice_preemptive_input import capture_effective_voice_input


async def run(action):
    client = VoiceProposalRPC.from_environment(connection_id="a" * 32,
        timeout_seconds=.05 if action == "slow_start" else 1, cleanup_seconds=1)
    assert "longmemory" not in sys.modules
    scope = TurnStamp(0, 1, 0)
    try:
        snapshot = await client.snapshot(scope=scope, query="完整合成问题", session_id="c" * 32)
    except ProposalRPCError:
        if action not in {"redirect", "bad_json", "chunked", "wrong_auth"}:
            raise
        if action == "wrong_auth":
            assert not await client.aclose()
        else:
            assert await client.aclose()
        return {"ok": True, "rejected": True, "active": 0}
    messages = [["system", "合成角色\n" + snapshot["memory_context"]]]
    is_v2 = action.startswith("v2_")
    asr_data = {"content": "完整合成问题", "language": "zh", "emotion": "NEUTRAL", "speaker": "合成说话人", "event": "SPEECH"}
    raw_asr = json.dumps(asr_data, ensure_ascii=False)
    def effective(rows, raw, *, tools=False):
        return capture_effective_voice_input("完整合成问题",
            [{"role": role, "content": text} for role, text in rows] + [{"role": "user", "content": raw}],
            tools_required=tools)
    confirmation = CloseConfirmation()
    try:
        if action in {"v2_effective", "v2_effective_tools"}:
            result = await client.start_effective(scope=scope, snapshot_id=snapshot["snapshot_id"],
                effective_input=effective(messages, raw_asr, tools=action == "v2_effective_tools"),
                close_confirmation=confirmation)
        else:
            result = await client.start(scope=scope, snapshot_id=snapshot["snapshot_id"], messages=messages,
                close_confirmation=confirmation, tools_required=action in {"tools_required", "v2_tools_present"},
                model_user_message=raw_asr if is_v2 else None)
    except ProposalRPCError:
        assert action in {"slow_start", "disconnect_start", "leak_start"}
        assert confirmation.required and not confirmation.confirmed
        await client.cancel(scope=scope)
        assert confirmation.confirmed
        try:
            await client.start(scope=scope, snapshot_id=snapshot["snapshot_id"], messages=messages)
        except ProposalRPCError:
            pass
        else:
            raise AssertionError("same turn retried")
        assert await client.aclose()
        return {"ok": True, "rejected": True, "active": 0}
    if action in {"tools_required", "v2_tools_present", "v2_effective_tools"}:
        assert result["state"] == "miss" and "text" not in result
        assert await client.aclose() and confirmation.confirmed
        return {"ok": True, "active": 0, "tools_executed": False}
    assert result["state"] == "preparing" and "text" not in result and not confirmation.confirmed
    if action in {"closing", "bad_ack"}:
        try:
            await client.cancel(scope=scope)
        except ProposalRPCError:
            assert action == "bad_ack"
        assert not confirmation.confirmed and not await client.aclose()
        return {"ok": True, "active": 1, "closed_confirmed": False}
    async def confirm():
        if action == "v2_effective":
            return await client.confirm_effective(scope=scope, snapshot_id=snapshot["snapshot_id"],
                effective_input=effective(messages, raw_asr), formal_turn_id="11111111-1111-4111-8111-111111111111",
                client_round_id="d" * 32, session_id="c" * 32)
        current_asr = raw_asr if is_v2 else None
        current_messages = messages
        if action in {"v2_metadata_changed", "v2_speaker_changed"}:
            changed = dict(asr_data)
            changed["emotion" if action == "v2_metadata_changed" else "speaker"] = "CHANGED"
            current_asr = json.dumps(changed, ensure_ascii=False)
        elif action == "v2_missing_current":
            current_asr = None
        elif action == "v2_context_changed":
            current_messages = [["system", messages[0][1] + "实际日期/历史/声纹说明变化"]]
        return await client.confirm(scope=scope, snapshot_id=snapshot["snapshot_id"], query="完整合成问题", messages=current_messages,
            formal_turn_id="11111111-1111-4111-8111-111111111111",
            client_round_id="d" * 32, session_id="c" * 32, model_user_message=current_asr)
    if action in {"real_host_headers_cancel", "real_host_body_cancel"}:
        await client.cancel(scope=scope)
    elif action == "slow_confirm":
        task = asyncio.create_task(confirm())
        await asyncio.sleep(.05)
        await client.cancel(scope=TurnStamp(0, 2, 1))
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancelled reply returned")
    elif action == "epoch_race":
        task = asyncio.create_task(confirm())
        await asyncio.sleep(.05)
        await client.snapshot(scope=TurnStamp(0, 2, 1), query="续说合成问题", session_id="c" * 32)
        value = await task
        assert value["state"] == "miss" and value["text"] is None
        await client.cancel(scope=TurnStamp(0, 2, 1))
    elif action == "bad_confirm":
        try:
            await confirm()
        except ProposalRPCError:
            pass
        else:
            raise AssertionError("text returned on miss")
        await client.cancel(scope=scope)
    elif action in {"real_host_fresh_miss", "real_host_source_miss", "v2_metadata_changed", "v2_speaker_changed",
                    "v2_missing_current", "v2_context_changed"}:
        value = await confirm()
        assert value["state"] == "miss" and value["text"] is None
    elif action in {"real_host_revised_cleanup", "real_host_new_turn_cleanup"}:
        latest = TurnStamp(0, 2, 1) if action == "real_host_revised_cleanup" else TurnStamp(1, 0, 1)
        await client.snapshot(scope=latest, query="续说合成问题", session_id="c" * 32)
    else:
        value = await confirm()
        expected = "合成回答" if action == "real_host_complete" else "合成有效回答"
        assert value["state"] == "adopted" and value["text"] == expected
        assert not confirmation.confirmed  # 返回最终文本不冒充关闭ACK。
    assert await client.aclose() and confirmation.confirmed
    assert client.snapshot_status()["local_sockets"] == 0
    return {"ok": True, "active": 0, "python": sys.version.split()[0], "host_imported": False}


try:
    value = asyncio.run(run(sys.argv[1]))
    print(json.dumps(value), flush=True)
except Exception as error:
    print(json.dumps({"ok": False, "error": type(error).__name__,
                      "code": str(error) if isinstance(error, ProposalRPCError) else "assertion"}), flush=True)
    raise SystemExit(1)
