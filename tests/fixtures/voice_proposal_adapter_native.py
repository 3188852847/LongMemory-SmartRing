"""从本地固定Git对象加载原ASR/提交/reset/chat方法，外围只有可控合成替身。"""

import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from types import ModuleType, SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[2]
NATIVE_REF = "eb4b28c59ed7ed885258498cf757ce14352d620e"
PCM = b"\x11\x00" * 960


def native_source(path):
    repo = os.environ["LONGMEMORY_TEST_XIAOZHI_ROOT"]
    return subprocess.run(["git", "-C", repo, "show", NATIVE_REF + ":main/xiaozhi-server/" + path],
        check=True, capture_output=True).stdout.decode("utf-8")


def load_nodes(source, module, names, class_name=None):
    parsed = ast.parse(source)
    nodes = parsed.body if class_name is None else next(n for n in parsed.body if isinstance(n, ast.ClassDef) and n.name == class_name).body
    selected = [node for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert {node.name for node in selected} == set(names)
    tree = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *selected], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), "<frozen-native-methods>", "exec"), vars(module))


def modules():
    spec = importlib.util.spec_from_file_location("ae_native_driver", ROOT / "tests/fixtures/xiaozhi_voice_boundary_driver.py")
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    snapshot = driver.load_snapshot()
    # 原chat AST与固定Git对象逐项相等，绝不靠脏树/手写替身宣称真实方法。
    original = next(node for node in ast.parse(native_source("core/connection.py")).body
                    if isinstance(node, ast.ClassDef) and node.name == "ConnectionHandler")
    chat = next(node for node in original.body if isinstance(node, ast.FunctionDef) and node.name == "chat")
    frozen = next(node for node in ast.parse(driver.FIXTURE.read_text(encoding="utf-8")).body
                  if isinstance(node, ast.FunctionDef) and node.name == "chat")
    assert ast.dump(chat) == ast.dump(frozen)
    snapshot.asyncio = asyncio
    base, receive, connection = ModuleType("native_asr_base"), ModuleType("native_receive"), ModuleType("native_connection")
    log = driver.Log()
    for module in (base, receive, connection):
        vars(module).update(asyncio=asyncio, time=time, json=json, queue=queue, logger=log, TAG="synthetic-native")
    base.InterfaceType = NS(STREAM="STREAM")
    base.remove_punctuation_and_length = lambda text: (len(text), text)
    base.enqueue_asr_report = lambda *_args: None
    load_nodes(native_source("core/providers/asr/base.py"), base, ["receive_audio", "handle_voice_stop"], "ASRProviderBase")
    load_nodes(native_source("core/handle/receiveAudioHandle.py"), receive, ["startToChat"])
    load_nodes(native_source("core/connection.py"), connection, ["reset_audio_states", "clear_queues"], "ConnectionHandler")
    async def unhandled(*_args):
        return False
    receive.handle_user_intent = unhandled
    receive.send_stt_message = unhandled
    receive.handleAbortMessage = unhandled
    base.startToChat = receive.startToChat
    return NS(base=base, receive=receive, connection=connection, snapshot=snapshot, Log=driver.Log)


class ControlledExecutor(ThreadPoolExecutor):
    def __init__(self):
        super().__init__(max_workers=2)
        self.release = threading.Event()
        self.release.set()
        self.entered = threading.Event()
        self.futures = []

    def submit(self, function, *args, **kwargs):
        def run():
            self.entered.set()
            assert self.release.wait(8), "synthetic worker barrier not released"
            return function(*args, **kwargs)
        future = super().submit(run)
        self.futures.append(future)
        return future


class SyntheticRPC:
    def __init__(self, **_kwargs):
        self.calls = []
        self.active = 0
        self.confirmation = None
        self.close_owned = True

    async def snapshot(self, **kwargs):
        self.calls.append("snapshot")
        return {"state": "ready", "snapshot_id": "e" * 32, "memory_context": "合成六项记忆"}

    async def start_effective(self, **kwargs):
        self.calls.append("start")
        self.confirmation = kwargs["close_confirmation"]
        self.confirmation.required = True
        self.active = 1
        return {"state": "preparing"}

    async def confirm_effective(self, **kwargs):
        self.calls.append("confirm")
        return {"state": "adopted", "text": "合成候选回答"}

    async def cancel(self, **kwargs):
        self.calls.append("cancel")
        if self.close_owned:
            self.active = 0
            self.confirmation.confirmed = True
        return {"owned_upstream_exited": self.close_owned}

    async def aclose(self):
        self.calls.append("close")
        return not self.active

    def snapshot_status(self):
        return {"active": self.active}


def harness(*, tools=False, rpc_factory=None, install_adapter=True):
    import voice_asr_prefetch as prefetch
    import voice_proposal_adapter as proposal
    from voice_preemptive_input import capture_effective_voice_input
    native = modules()
    class Dialogue:
        def __init__(self):
            self.dialogue = []
        def put(self, item):
            self.dialogue.append(item)
        def get_llm_dialogue_with_memory(self, memory, *_args):
            return [{"role": "system", "content": "合成角色\n" + memory}] + [
                {"role": row.role, "content": row.content} for row in self.dialogue]
        def get_llm_dialogue(self):
            return []
    class Model:
        kwargs = {}
        def generate(self, **kwargs):
            return [{"text": "检查资料"}]
    class Provider:
        receive_audio, handle_voice_stop = native.base.receive_audio, native.base.handle_voice_stop
        model_dir, language, delete_audio_file = "models/SenseVoiceSmall", "zh", True
        interface_type = NS(value="LOCAL")
        model = Model()
        async def speech_to_text_wrapper(self, audio, session):
            return await self.speech_to_text(audio, session, NS(pcm_bytes=b"".join(audio), file_path=None))
        async def speech_to_text(self, audio, session, artifacts=None):
            return clean((await asyncio.to_thread(self.model.generate, input=artifacts.pcm_bytes))[0]["text"]), None
        def stop_ws_connection(self):
            pass
    def clean(text):
        return {"content": text, "language": "zh", "emotion": "calm"}
    class Connection:
        chat = native.snapshot.chat
        reset_audio_states, clear_queues = native.connection.reset_audio_states, native.connection.clear_queues
        async def close(self):
            self.stop_event.set()
            self.reset_audio_states()
    connection = Connection()
    connection.loop = asyncio.get_running_loop()
    connection.logger, connection.dialogue = native.Log(), Dialogue()
    executor = connection.executor = ControlledExecutor()
    connection.stop_event = threading.Event()
    connection.asr_audio, connection.client_audio_buffer, connection.client_voice_window = [], [], []
    connection.client_have_voice, connection.client_voice_stop = True, False
    connection.client_abort, connection.client_is_speaking, connection.need_bind = False, False, False
    connection.max_output_size, connection.client_listen_mode = 0, "auto"
    connection.vad_last_voice_time = time.time() * 1000 - 300
    connection.voiceprint_provider, connection.current_speaker = None, None
    connection.introduced_speakers, connection.system_introduced_speakers = set(), set()
    connection.session_id, connection.intent_type, connection.config = "c" * 32, "nointent", {"voiceprint": {}}
    connection.features, connection.report_queue = {"emoji": False}, queue.Queue()
    stored, requests = [], []
    connection.tts = NS(conn=connection, tts_text_queue=queue.Queue(), tts_audio_queue=queue.Queue(),
                         store_tts_text=lambda sid, text: stored.append(text))
    class Memory:
        _session_id = "c" * 32
        prepares = 0
        async def query_memory(self, raw):
            assert proposal._query(raw) == "检查资料"
            self.prepares += 1
            return "合成六项记忆"
    connection.memory = Memory()
    class LLM:
        identity = "synthetic-original"
        def response(self, session, dialogue, **kwargs):
            requests.append(dialogue)
            yield "原正式回答"
    rpc = SyntheticRPC() if rpc_factory is None else None
    fun = NS(ASRProvider=Provider, lang_tag_filter=clean)
    prefetch.install_voice_asr_prefetch(Connection, fun, enabled=True)
    # 同真实输入计时包装一样用ContextExecutor提交，检验Context.run包裹不丢票据。
    from voice_diagnostics import ContextExecutor
    connection.executor = ContextExecutor(executor, connection)
    def preview(conn, raw):
        rows = [{"role": "system", "content": "合成角色\n"}] + [
            {"role": row.role, "content": row.content} for row in conn.dialogue.dialogue]
        rows.append({"role": "user", "content": raw})
        def with_memory(context):
            frozen = [dict(row) for row in rows]
            frozen[0]["content"] += context
            return capture_effective_voice_input(proposal._query(raw), frozen, tools_required=tools)
        return proposal.PreviewPlan(capture_effective_voice_input(proposal._query(raw), rows, tools_required=tools), with_memory)
    metadata = {"formal_turn_id": "11111111-1111-4111-8111-111111111111", "client_round_id": "d" * 32, "session_id": "c" * 32}
    adapter = proposal.install_voice_proposal_adapter(Connection, fun, native.base, enabled=True,
        preview_effective_input=preview, formal_metadata=lambda conn: metadata,
        rpc_factory=rpc_factory or (lambda **_kwargs: rpc), confirmation_timeout_seconds=2) if install_adapter else None
    connection.llm = adapter.bind_provider(connection, LLM()) if adapter is not None else LLM()
    connection.asr = Provider()
    return NS(connection=connection, provider=connection.asr, native=native, adapter=adapter, rpc=rpc,
              executor=executor, stored=stored, requests=requests, prefetch=prefetch, fun=fun,
              preview=preview, metadata=metadata)


async def begin(h):
    for _ in range(16):
        await h.provider.receive_audio(h.connection, PCM, True)
    await h.provider.receive_audio(h.connection, PCM, False)
    ticket = getattr(h.connection, h.prefetch._STATE).ticket
    await ticket.task
    state = vars(h.connection).get("_longmemory_proposal_adapter_state")
    if state.current is not None:
        await state.current.task
    return ticket


async def endpoint(h):
    h.connection.client_voice_stop = True
    await h.provider.receive_audio(h.connection, PCM, False)


async def finish(h):
    h.executor.release.set()
    for future in h.executor.futures:
        await asyncio.wrap_future(future)
    await h.adapter.aclose_connection(h.connection)
    h.executor.shutdown(wait=True)
