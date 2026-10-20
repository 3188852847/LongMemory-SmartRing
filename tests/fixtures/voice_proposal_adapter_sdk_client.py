"""真实3.10：固定原ASR/chat/LLM方法+真实MemoryProvider/RPC+实际最终输入层。"""

import asyncio
import ast
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import threading
import uuid
from types import ModuleType, SimpleNamespace as NS

root = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(root / "scripts/development/xiaozhi"), str(Path(__file__).parent)]
import voice_proposal_adapter as proposal
from voice_proposal_rpc import VoiceProposalRPC
import voice_proposal_adapter_native as boundary
import xiaozhi_voice_boundary_driver as driver


async def run():
    config = json.loads(sys.stdin.readline())
    scenario = config["scenario"]
    os.environ.update(LONGMEMORY_RUNTIME_URL=config["authority"] + "/api/internal/memory/prepare",
        LONGMEMORY_RUNTIME_TOKEN=config["token"], LONGMEMORY_MEMORY_TRANSPORT="runtime",
        LONGMEMORY_VOICE_RESPONSE_STYLE="realtime", NO_PROXY="127.0.0.1,localhost")
    assert "longmemory" not in sys.modules
    assert Path(proposal.__file__).resolve().is_relative_to(root)
    h = boundary.harness(rpc_factory=VoiceProposalRPC.from_environment, install_adapter=False)
    class SafeLog(driver.Log):
        def error(self, *_args, **_kwargs):
            kind, _value, trace = sys.exc_info()
            while trace is not None and trace.tb_next is not None:
                trace = trace.tb_next
            self.errors.append({"type": kind.__name__ if kind else "reported_failure",
                "file": Path(trace.tb_frame.f_code.co_filename).name if trace else None,
                "line": trace.tb_lineno if trace else None})
    h.connection.logger = SafeLog()
    # 真实MemoryProvider，仅其上游纯基类/日志为可控接口，不加载私有配置。
    base = ModuleType("core.providers.memory.base")
    class MemoryProviderBase:
        def __init__(self, config):
            self.config = config
        def init_memory(self, role_id, llm, **kwargs):
            self.role_id, self.llm = role_id, llm
    base.MemoryProviderBase, base.logger = MemoryProviderBase, driver.Log()
    sys.modules[base.__name__] = base
    spec = importlib.util.spec_from_file_location("adapter_real_memory", root / "scripts/development/xiaozhi/longmemory_provider.py")
    memory_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(memory_module)
    memory = memory_module.MemoryProvider({"allowed_device_id": "ae-synthetic", "python_executable": sys.executable,
        "project_root": str(root), "database_path": str(root / "data/databases/xiaozhi-demo-adapter.db"),
        "audit_log": str(root / "data/logs/xiaozhi-demo-adapter.jsonl")})
    memory.init_memory("ae-synthetic", None)
    h.connection.memory = memory
    import launch_with_memory as launch
    launch.install_answer_completion(type(h.connection))
    h.adapter = launch.install_voice_proposal_policy(type(h.connection), enabled=True,
        fun_local=h.fun, asr_base=h.native.base, rpc_factory=VoiceProposalRPC.from_environment)
    assert h.adapter.preview is launch.preview_voice_proposal_input
    assert h.adapter.formal_metadata is launch.voice_proposal_formal_metadata

    # 同固定上游完整Dialogue方法，不以手写标准消息替代最终装配。
    source = boundary.native_source("core/utils/dialogue.py")
    message_module = ModuleType("frozen_native_message")
    message_module.uuid = uuid
    boundary.load_nodes(source, message_module, ["__init__"], "Message")
    Message = type("Message", (), {"__init__": message_module.__init__})
    h.native.snapshot.Message = Message
    cls = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "Dialogue")
    methods = [node.name for node in cls.body if isinstance(node, ast.FunctionDef)]
    module = ModuleType("frozen_native_dialogue")
    vars(module).update(datetime=datetime, re=re, json=json)
    boundary.load_nodes(source, module, methods, "Dialogue")
    Dialogue = type("Dialogue", (), {name: vars(module)[name] for name in methods})
    h.connection.dialogue = Dialogue()
    h.connection.dialogue.put(Message(role="system", content="合成角色<memory>原内容</memory>"))
    tools = scenario == "tools"
    # 固定真实LLM方法使用可控SDK stream；仅候选模型实际走宿主Gateway回环SSE。
    original, streams, requests = driver.provider([driver.wire("原正式回答")], module=h.native.snapshot)
    original.model_name = "DeepSeek-V4-Flash"
    original.base_url = config["authority"] + "/voice/v1"
    import voice_latency as latency
    observed = latency._ObservedLLM(h.connection, original)
    private = observed._provider
    assert private.original is original
    if scenario in {"metadata", "date", "role", "history", "speaker"}:
        response = private.response
        def changed(session, dialogue, **kwargs):
            rows = [dict(row) for row in dialogue]
            if scenario in {"metadata", "speaker"}:
                raw = json.loads(rows[-1]["content"])
                raw["emotion" if scenario == "metadata" else "speaker"] = "实际输入变化"
                rows[-1]["content"] = json.dumps(raw, ensure_ascii=False)
            elif scenario == "history":
                rows.insert(-1, {"role": "assistant", "content": "实际历史变化"})
            else:
                rows[0]["content"] += "实际" + scenario + "变化"
            return response(session, rows, **kwargs)
        private.response = changed
    import voice_web_search as web
    class Waiting:
        def __init__(self, connection):
            self.connection, self.sentence_id, self.closed = connection, connection.sentence_id, False
        def current(self):
            return (not self.closed and not self.connection.stop_event.is_set() and not self.connection.client_abort
                    and self.connection.sentence_id == self.sentence_id)
        def cancel(self):
            self.closed = True
    def begin_waiting(connection, dialogue):
        connection._longmemory_waiting = Waiting(connection)
        return dialogue
    latency.begin_waiting = begin_waiting  # 不加载提示音/声音档案；实际输入/输出编排函数保留。
    web.load_config = lambda: NS(provider="tavily") if tools else None
    def forbidden_search(*_args, **_kwargs):
        raise AssertionError("no tool execution authorized in synthetic adapter proof")
    web.search_web = forbidden_search
    h.connection._longmemory_voice_latency = NS(bind_sentence=lambda *_a, **_k: None, mark=lambda *_a, **_k: None,
        mark_stage=lambda *_a, **_k: None, fail=lambda *_a, **_k: None)
    h.connection.llm = observed
    entered, release = threading.Event(), threading.Event()
    if scenario in {"yield_cancel", "new_turn"}:
        observed_response, first = h.connection.llm.response, [True]
        def pause(*args, **kwargs):
            for text in observed_response(*args, **kwargs):
                if first[0]:
                    first[0] = False
                    entered.set()
                    assert release.wait(8), "adapter output barrier not released"
                yield text
        h.connection.llm.response = pause
    try:
        await boundary.begin(h)
        print(json.dumps({"phase": "adapter_prepared"}), flush=True)
        assert await asyncio.to_thread(sys.stdin.readline) == "continue\n"
        if scenario == "pcm_changed":
            h.connection.asr_audio[0] = b"\x22\x00" * 960
        h.executor.release.clear()
        await boundary.endpoint(h)
        assert h.connection.asr_audio == []
        h.executor.release.set()
        if scenario in {"yield_cancel", "new_turn"}:
            assert await asyncio.to_thread(entered.wait, 5)
            if scenario == "yield_cancel":
                h.connection.clear_queues()  # 不依赖client_abort bool遮住入队竞争。
            else:
                h.connection.client_have_voice = True
                h.connection.vad_last_voice_time = boundary.time.time() * 1000 - 300
                await boundary.begin(h)
                await boundary.endpoint(h)
                await asyncio.wrap_future(h.executor.futures[-1])
            release.set()
        for future in h.executor.futures:
            await asyncio.wrap_future(future)
        if h.connection.logger.errors:
            raise RuntimeError(json.dumps(h.connection.logger.errors))
        stats = h.adapter.snapshot(h.connection)
        if scenario == "queued_cancel":
            assert h.stored == ["合成回答"] and not requests
            old_sentence = h.connection.sentence_id
            h.connection.tts.tts_audio_queue.put(("middle", [b"synthetic"], None, old_sentence))
            h.connection.client_have_voice = True
            h.connection.vad_last_voice_time = boundary.time.time() * 1000
            await h.provider.receive_audio(h.connection, boundary.PCM, True)
            assert h.connection.sentence_id == old_sentence
            await asyncio.to_thread(h.connection.tts.tts_audio_queue.put, ("middle", [b"late"], None, old_sentence))
            for q in (h.connection.tts.tts_text_queue, h.connection.tts.tts_audio_queue):
                try:
                    q.get_nowait()
                except boundary.queue.Empty:
                    pass
                else:
                    raise AssertionError("revoked output dequeued")
                assert q.empty()
            state = "suppressed_queued"
        elif scenario == "yield_cancel":
            assert h.stored == [] and h.connection.tts.tts_text_queue.empty()
            assert not any(row.role == "assistant" for row in h.connection.dialogue.dialogue)
            state = "suppressed"
        elif scenario == "new_turn":
            assert h.stored == ["合成回答"] and not requests
            assert len([row for row in h.connection.dialogue.dialogue if row.role == "assistant"]) == 1
            state = "adopted"
        elif scenario == "reset_worker":
            if not (h.stored == ["合成回答"] and not requests and stats["adopted"] == 1):
                raise RuntimeError(json.dumps([{"adapter_counts": stats, "fallback_count": len(requests),
                    "candidate_text_matched": h.stored == ["合成回答"]}]))
            state = "adopted"
        else:
            assert h.stored == ["原正式回答"] and len(requests) == 1
            assert all(stream.closed for stream in streams)
            if tools:
                assert requests[0]["tools"] == [web.TOOL] and stats["admitted"] == 0
            state = "miss"
        assert await h.adapter.aclose_connection(h.connection)
        assert "longmemory" not in sys.modules
        return {"ok": True, "state": state, "python": sys.version.split()[0], "host_imported": False,
                "admitted": stats["admitted"], "adopted": stats["adopted"], "fallback_calls": len(requests)}
    finally:
        release.set()
        await boundary.finish(h)


try:
    print(json.dumps(asyncio.run(run())), flush=True)
except Exception as error:
    trace = error.__traceback__
    while trace.tb_next is not None:
        trace = trace.tb_next
    print(json.dumps({"ok": False, "error": type(error).__name__, "line": trace.tb_lineno,
                      "file": Path(trace.tb_frame.f_code.co_filename).name,
                      **({"diagnostic": json.loads(str(error))} if isinstance(error, RuntimeError) else {})}), flush=True)
    raise SystemExit(1)
