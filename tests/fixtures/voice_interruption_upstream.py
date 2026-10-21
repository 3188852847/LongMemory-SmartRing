"""提取固定SDK的收音/发送/队列方法；依赖为合成对象，不导入模型。"""
import ast
import asyncio
from collections import deque
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from types import ModuleType, SimpleNamespace as NS
ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT.parents[2] if ROOT.parent.name == "worktrees" else ROOT
UPSTREAM = MAIN / "local/runtime/xiaozhi-esp32-server"
PIN = "eb4b28c59ed7ed885258498cf757ce14352d620e"
sys.path.insert(0, str(ROOT / "scripts/development/xiaozhi"))
def connection():
    return NS(sentence_id="old", tts=NS(_longmemory_cosy_streaming_installed=True),
        client_abort=False, stop_event=threading.Event(), sample_rate=16000,
        _longmemory_cosy_delivery_mode="adaptive")

def build():
    if not (UPSTREAM / ".git").exists():
        raise FileNotFoundError("owner-installed pinned SDK unavailable")
    silent = NS(bind=lambda **kw: NS(debug=lambda *a: None, info=lambda *a: None,
                                    warning=lambda *a: None, error=lambda *a: None))
    def source(path):
        return subprocess.check_output(["git", "-C", str(UPSTREAM), "show",
            PIN + ":main/xiaozhi-server/" + path], text=True, encoding="utf-8")
    def load(path, namespace):
        tree = ast.parse(source(path))
        tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        exec(compile(tree, "pinned:" + PIN + "/" + path, "exec"), namespace)
    scheduler = {"time": time, "asyncio": asyncio, "deque": deque, "logger": silent, "TAG": "test"}
    load("core/utils/audioRateController.py", scheduler)
    send = ModuleType("pinned_sender")
    send.__dict__.update(asyncio=asyncio, json=json, time=time, AUDIO_FRAME_DURATION=60,
        PRE_BUFFER_COUNT=5, AudioRateController=scheduler["AudioRateController"],
        TAG="test", SentenceType=NS(FIRST="first", MIDDLE="middle", LAST="last"),
        textUtils=NS(check_emoji=lambda text: text, get_string_no_punctuation_or_emoji=lambda text: text))
    load("core/handle/sendAudioHandle.py", send.__dict__)
    abort = {"json": json, "TAG": "test"}
    load("core/handle/abortHandle.py", abort)
    calls = []
    async def intent(conn, text):
        calls.append("intent")
        return False
    receive = ModuleType("pinned_receiver")
    receive.__dict__.update(asyncio=asyncio, json=json, time=time, TAG="test",
        handleAbortMessage=abort["handleAbortMessage"], handle_user_intent=intent,
        send_stt_message=send.send_stt_message)
    load("core/handle/receiveAudioHandle.py", receive.__dict__)
    conn_tree = ast.parse(source("core/connection.py"))
    cls = next(n for n in conn_tree.body if isinstance(n, ast.ClassDef) and n.name == "ConnectionHandler")
    cls.bases = []
    cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in {"clear_queues", "clearSpeakStatus"}]
    scope = {"queue": queue, "TAG": "test"}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), "pinned_connection_queue_methods", "exec"), scope)
    Connection = scope["ConnectionHandler"]
    async def close(conn):
        calls.append("close")
    Connection.close = close
    conn = Connection()
    conn.__dict__.update(connection().__dict__)
    conn.__dict__.update(logger=silent, config={}, need_bind=False, calling=False,
        client_is_speaking=False, client_listen_mode="realtime", client_aec=True,
        close_after_chat=False, max_output_size=0, introduced_speakers=set(), session_id="synthetic",
        conn_from_mqtt_gateway=False, last_activity_time=0,
        executor=NS(submit=lambda *args: calls.append("submit")), chat=lambda text: None,
        report_queue=queue.Queue())
    conn.tts.current_sentence_id = "old"
    conn.tts.tts_text_queue = queue.Queue()
    conn.tts.tts_audio_queue = queue.Queue()
    conn.tts.tts_audio_first_sentence = True
    messages = []
    async def socket_send(value):
        messages.append(value)
    conn.websocket = NS(send=socket_send)
    asr = NS(startToChat=receive.startToChat)
    ttsbase = NS(sendAudioMessage=send.sendAudioMessage)
    return NS(conn=conn, Connection=Connection, send=send, receive=receive, asr=asr,
              ttsbase=ttsbase, messages=messages, calls=calls)

