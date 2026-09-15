"""固定小智快照的启动适配：每连接独立 Memory 对象，不改上游源码。

必须通过 setup.py start 启动，工作目录为上游服务根目录。
"""

from pathlib import Path
import argparse
from contextvars import ContextVar
import runpy
import sys
import time


def observe_memory_operations(connection):
    """为任意小智 Memory 提供器记录统一耗时，不读取或打印记忆正文。"""
    memory = connection.memory
    if memory is None or getattr(memory, "_longmemory_observed", False):
        return
    provider = connection.config["selected_module"]["Memory"]
    original_query = memory.query_memory
    original_save = memory.save_memory

    async def query_memory(*args, **kwargs):
        # 捕获请求开始时所属句子；同一设备快速产生多轮输入时，旧请求可能晚于
        # 新请求完成，不能让它覆盖控制台显示的最近一轮首声计时。
        sentence_id = getattr(connection, "sentence_id", None)
        started = time.perf_counter()
        try:
            result = await original_query(*args, **kwargs)
        except Exception as error:
            tracker = getattr(connection, "_longmemory_voice_latency", None)
            if tracker is not None:
                code = ("memory_response_invalid"
                        if str(error) == "LongMemory 返回协议无效"
                        else "memory_runtime_failed")
                tracker.bind_sentence(sentence_id)
                tracker.fail(code, stage="memory")
            # 固定上游在查询记忆前已发送 FIRST，却会在这里的异常分支直接
            # return，遗漏 LAST。补发同一 sentence_id 的结束动作，避免圆屏
            # 永久停留在“说话中”；不把异常正文送往设备或控制台。
            tts = getattr(connection, "tts", None)
            queue = getattr(tts, "tts_text_queue", None)
            if queue is not None and sentence_id is not None:
                from core.providers.tts.dto.dto import (
                    ContentType, SentenceType, TTSMessageDTO,
                )
                queue.put(TTSMessageDTO(
                    sentence_id=sentence_id,
                    sentence_type=SentenceType.LAST,
                    content_type=ContentType.ACTION,
                ))
            raise
        else:
            tracker = getattr(connection, "_longmemory_voice_latency", None)
            if tracker is not None:
                tracker.bind_sentence(sentence_id)
                tracker.mark("memory_ready_ms", sentence_id=sentence_id)
            return result
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            connection.logger.bind(tag="memory-comparison").info(
                f"记忆查询后端={provider} 耗时={elapsed_ms:.1f}ms"
            )

    async def save_memory(*args, **kwargs):
        started = time.perf_counter()
        try:
            return await original_save(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            connection.logger.bind(tag="memory-comparison").info(
                f"记忆保存后端={provider} 耗时={elapsed_ms:.1f}ms"
            )

    memory.query_memory = query_memory
    memory.save_memory = save_memory
    memory._longmemory_observed = True


def isolate_memory_initialization(connection_class, provider_class):
    original = connection_class._initialize_memory

    def initialize(connection):
        name = connection.config["selected_module"]["Memory"]
        config = connection.config["Memory"][name]
        if config.get("type") == "longmemory":
            # 原实例在服务启动时生成并共享；必须在设备身份绑定前替换，
            # 即使非法设备初始化失败，它也不能复用合法设备的记忆对象。
            connection.memory = provider_class(config)
        result = original(connection)
        observe_memory_operations(connection)
        return result

    connection_class._initialize_memory = initialize


def install_answer_completion(connection_class):
    """在顶层回答完成后归档实际助手文本，不侵入厂商源码。"""

    if getattr(connection_class, "_longmemory_completion_installed", False):
        return
    original = connection_class.chat

    def chat(connection, query, depth=0):
        before = len(connection.dialogue.dialogue)
        result = original(connection, query, depth)
        memory = connection.memory
        # 上游 chat() 的正常分支并不都返回 True：direct_answer 在已经把
        # 助手文本写入对话并送入 TTS 队列后会直接返回 None。因此完成依据
        # 必须是“本次顶层调用新增了助手文本”，不能依赖厂商内部返回值。
        if (depth == 0 and query
                and callable(getattr(memory, "record_completed_turn", None))):
            answers = [
                item.content for item in connection.dialogue.dialogue[before:]
                if getattr(item, "role", None) == "assistant"
                and isinstance(getattr(item, "content", None), str)
                and item.content.strip()
            ]
            if answers:
                try:
                    memory.record_completed_turn("\n".join(answers))
                except Exception:
                    # 语音回答已经进入播放队列，归档失败不能伪装成聊天失败；
                    # 只输出稳定错误，不记录回答正文。
                    connection.logger.bind(tag="LongMemory").error(
                        "回答完成回执失败；本轮不会自动重试"
                    )
        return result

    connection_class.chat = chat
    connection_class._longmemory_completion_installed = True


def install_internal_end_prompt_boundary(receive_audio_module):
    """标记上游静默超时生成的结束提示，不按用户输入写入记忆。

    ContextVar 让并发设备任务彼此隔离；这里只绑定上游
    no_voice_close_connect -> startToChat 的结构化调用来源，不匹配中文内容。
    """

    if getattr(receive_audio_module, "_longmemory_end_boundary_installed", False):
        return
    original_no_voice = receive_audio_module.no_voice_close_connect
    original_start = receive_audio_module.startToChat
    internal_end = ContextVar("longmemory_internal_end_prompt", default=False)

    async def no_voice_close_connect(connection, have_voice):
        token = internal_end.set(True)
        try:
            return await original_no_voice(connection, have_voice)
        finally:
            internal_end.reset(token)

    async def start_to_chat(connection, text):
        if internal_end.get():
            suppress = getattr(
                getattr(connection, "memory", None),
                "suppress_internal_query_once", None,
            )
            if callable(suppress):
                suppress(text)
        return await original_start(connection, text)

    receive_audio_module.no_voice_close_connect = no_voice_close_connect
    receive_audio_module.startToChat = start_to_chat
    receive_audio_module._longmemory_end_boundary_installed = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-control", action="store_true")
    parser.add_argument("--voice-mode", choices=["pipeline", "doubao_realtime"], default="pipeline")
    parser.add_argument("--doubao-env", "--doubao-env-file", type=Path,
                        default=Path(__file__).resolve().parents[3] / ".env.doubao.local")
    args = parser.parse_args()
    root = Path.cwd()
    if args.device_control or args.voice_mode == "doubao_realtime":
        from control_compatibility import verify_control_snapshot
        verify_control_snapshot(root)
    sys.path.insert(0, str(root))
    from core.connection import ConnectionHandler
    from direct_ws_v2 import install_direct_ws_v2
    install_direct_ws_v2(ConnectionHandler)
    if args.voice_mode == "doubao_realtime":
        from doubao_realtime.config import load_config
        from doubao_realtime.bootstrap import install_realtime_mode
        install_realtime_mode(ConnectionHandler, load_config(args.doubao_env))
        if args.device_control:
            from core.websocket_server import WebSocketServer
            from control_http import install_control_server
            install_control_server(WebSocketServer, ConnectionHandler)
        runpy.run_path(str(root / "app.py"), run_name="__main__")
        return
    import core.handle.receiveAudioHandle as receive_audio_handle
    from core.providers.memory.longmemory.longmemory import MemoryProvider
    from fast_voice_responses import install_fast_voice_responses
    from voice_latency import install_audio_send_observer, install_voice_latency
    from voice_input_latency import install_voice_input_latency
    from voice_prediction import install_voice_prediction_shadow
    isolate_memory_initialization(ConnectionHandler, MemoryProvider)
    from core.providers.asr import base as asr_base
    install_voice_input_latency(asr_base)
    # 快速通道必须位于时序包装器内部，才能像普通回答一样记录真实首包。
    install_fast_voice_responses(ConnectionHandler)
    install_voice_latency(ConnectionHandler)
    install_audio_send_observer()
    install_answer_completion(ConnectionHandler)
    # 第一版只做无正文、无播放的封闭分支影子统计，为是否值得预合成提供证据。
    install_voice_prediction_shadow(ConnectionHandler)
    install_internal_end_prompt_boundary(receive_audio_handle)
    if args.device_control:
        from core.websocket_server import WebSocketServer
        from control_http import install_control_server
        install_control_server(WebSocketServer, ConnectionHandler)
    runpy.run_path(str(root / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
