"""固定小智快照的启动适配：每连接独立 Memory 对象，不改上游源码。

必须通过 setup.py start 启动，工作目录为上游服务根目录。
"""

from pathlib import Path
import argparse
from contextvars import ContextVar
import os
import runpy
import sys
import time
from threading import Lock
from voice_diagnostics import CURRENT


def voice_proposal_formal_metadata(connection):
    """领取本线程实际Memory prepare的关联ID；不调用query、不取最近一轮冒充。

    只给语音RPC桥提供已有平台回执的身份。拿不到无竞争快照或遇固定管理/预算
    回复时直接放弃候选；原回答链路保持原有处理，不等待旧轮网络回执。
    """
    import re
    from uuid import UUID
    memory = getattr(connection, "memory", None)
    context = getattr(memory, "_turn_key", None)
    lock = getattr(memory, "_lock", None)
    if not callable(getattr(context, "get", None)) or not callable(getattr(lock, "acquire", None)):
        return None
    key = context.get()
    if not lock.acquire(blocking=False):
        return None
    try:
        pending = getattr(memory, "_pending_completions", {}).get(key)
        if (not isinstance(pending, dict) or pending.get("memory_protocol") != 2
                or pending.get("fixed_reply") is not None or pending.get("client_round_id") != key):
            return None
        session = getattr(memory, "_session_id", None)
        formal = pending.get("turn_id")
        if (not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{24,32}", key) is None
                or not isinstance(session, str) or re.fullmatch(r"[0-9a-f]{32}", session) is None
                or not isinstance(formal, str)):
            return None
        try:
            if str(UUID(formal)) != formal:
                return None
        except ValueError:
            return None
        return {"formal_turn_id": formal, "client_round_id": key, "session_id": session}
    finally:
        lock.release()


def install_advanced_voice_policy(connection_class, *, turn_end_mode="off",
                                  turn_end_model=None, cosy_delivery_mode="buffered",
                                  detector_factory=None, asr_provider_class=None,
                                  on_turn_event=None, calibration_approved=False):
    """公共接线只激活有实际前提的方向；失败保留既有 buffered/VAD 主链路。

    必须在输入计时/ASR预取后安装话轮层。off 不导入模型或推理依赖。
    calibration_approved 由可信组合验收提供，CLI/环境变量不能自行声明通过。
    """
    if turn_end_mode not in {"off", "shadow", "enabled"}:
        raise ValueError("voice_turn_end_mode_invalid")
    if cosy_delivery_mode not in {"buffered", "incremental", "adaptive"}:
        raise ValueError("cosyvoice_delivery_mode_invalid")
    if getattr(connection_class, "_longmemory_advanced_voice_installed", False):
        raise RuntimeError("advanced_voice_policy_restart_required")
    report = {"version": 1,
              "cosy": {"mode": cosy_delivery_mode, "actual_playback_proven": False},
              "turn_end": {"requested": turn_end_mode, "mode": "off", "installed": False,
                           "reason": "disabled"}}
    if turn_end_mode == "enabled" and not calibration_approved:
        report["turn_end"]["reason"] = "calibration_required"
    elif turn_end_mode != "off":
        if turn_end_model is None or asr_provider_class is None:
            report["turn_end"]["reason"] = "model_unavailable"
        else:
            try:
                if detector_factory is None:
                    from voice_turn_end_model import SmartTurnCPU
                    detector_factory = SmartTurnCPU
                detector = detector_factory(turn_end_model)
                if not callable(getattr(detector, "predict", None)):
                    raise ValueError("turn_end_detector_invalid")
            except Exception:
                # 固定错误码，不输出模型路径、依赖异常或凭据；不尝试下载/换源。
                report["turn_end"]["reason"] = "model_unavailable"
            else:
                from voice_turn_end import TurnEndConfig, install_voice_turn_end
                try:
                    installed = install_voice_turn_end(
                        connection_class, asr_provider_class, detector=detector,
                        config=TurnEndConfig(mode=turn_end_mode), on_event=on_turn_event,
                        calibration_approved=calibration_approved)
                except BaseException:
                    close = getattr(detector, "close", None)
                    if callable(close):
                        close()
                    raise
                connection_class._longmemory_advanced_detector = detector
                close = getattr(detector, "close", None)
                if callable(close):
                    # app.py拥有自己的事件循环；启动中途异常也须回收仅本进程创建的侧车。
                    import atexit
                    atexit.register(close)
                report["turn_end"] = {"requested": turn_end_mode, **installed, "reason": None}
    # 明确的子进程参数；不改共享声音档案、服务端默认或已运行连接。
    connection_class._longmemory_cosy_delivery_mode = cosy_delivery_mode
    connection_class._longmemory_advanced_voice_status = report
    connection_class._longmemory_advanced_voice_installed = True
    return report


def install_pipeline_latency_policy(connection_class, *, mode, enable_asr_prefetch=False,
                                    enable_http_keepalive=False):
    """语音策略只在独立服务进程内生效；各项优化经过独立基准后才接入。"""
    if mode not in {"realtime", "original"}:
        raise ValueError("voice_latency_mode_invalid")
    os.environ["LONGMEMORY_VOICE_RESPONSE_STYLE"] = mode
    connection_class._longmemory_voice_latency_mode = mode
    if mode == "realtime" and enable_http_keepalive:
        from core.providers.llm.openai import openai as provider_module
        from voice_http_transport import install_voice_http_transport
        install_voice_http_transport(provider_module, enabled=True)
    if mode == "realtime" and enable_asr_prefetch:
        from core.providers.asr import fun_local
        from voice_asr_prefetch import install_voice_asr_prefetch
        install_voice_asr_prefetch(connection_class, fun_local, enabled=True)


def preview_voice_proposal_input(connection, raw_asr):
    """按原生chat与网页编排的真实能力预检；不执行工具、不改历史或缓存时间。"""
    from voice_latency import _ObservedLLM
    from voice_proposal_adapter import preview_native_input
    import voice_web_search as web

    intent = getattr(connection, "intent_type", None)
    if intent not in {"nointent", "function_call"}:
        # intent_llm可能在chat前执行意图工具；未知路径不能推定为纯文本。
        return None
    provider = getattr(connection, "llm", None)
    if isinstance(provider, _ObservedLLM):
        provider = provider._provider
    if not callable(getattr(provider, "response", None)):
        return None
    native_tools = intent == "function_call" and hasattr(connection, "func_handler")
    if native_tools and not callable(getattr(connection.func_handler, "get_functions", None)):
        return None
    # 原生首层function_call还会追加direct_answer，空工具表也不能当无工具。
    # 不调用get_functions：它会写工具描述缓存，预览只读能力而不执行编排。
    try:
        config = web.load_config()
    except (ValueError, OSError):
        config = None  # 与正式web_response的配置失败语义一致。
    configured = config is not None and config.provider in web.ENDPOINTS
    functions = callable(getattr(provider, "response_with_functions", None))
    if configured and not functions and not native_tools:
        # 正式路径仍会生成精确时间说明；不能复用旧时间制造命中或预发必弃请求。
        return None
    return preview_native_input(connection, raw_asr,
        tools_required=native_tools or (configured and functions), web_configured=configured)


def install_voice_proposal_policy(connection_class, *, enabled=False, fun_local=None, asr_base=None,
                                  rpc_factory=None):
    """显式连接原ASR预取与RPC；关闭时不导入适配器或修改类/提供器。"""
    if type(enabled) is not bool:
        raise ValueError("voice_proposal_enabled_invalid")
    if not enabled:
        return None
    from voice_proposal_adapter import install_voice_proposal_adapter
    return install_voice_proposal_adapter(connection_class, fun_local, asr_base, enabled=True,
        preview_effective_input=preview_voice_proposal_input, formal_metadata=voice_proposal_formal_metadata,
        rpc_factory=rpc_factory)


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
        trace = CURRENT.get()
        tracker = getattr(connection, "_longmemory_voice_latency", None)
        initial_tracker = tracker
        if tracker is not None:
            tracker.bind_sentence(sentence_id)
        if trace is not None:
            trace.event("memory_requested")
        started = time.perf_counter()
        try:
            result = await original_query(*args, **kwargs)
        except Exception as error:
            if trace is not None:
                trace.event("memory_failed")
            tracker = getattr(connection, "_longmemory_voice_latency", None)
            if tracker is not None:
                code = ("memory_response_invalid"
                        if str(error) == "LongMemory 返回协议无效"
                        else "memory_runtime_failed")
                if tracker is not initial_tracker:
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
        if os.environ.get("LONGMEMORY_MEMORY_BACKEND") == "hy_memory":
            from voice_budget import BudgetNoticeLLM
            connection.llm = BudgetNoticeLLM(connection.llm, connection.memory)
        observe_memory_operations(connection)
        return result

    connection_class._initialize_memory = initialize


def install_voice_output_revocation_policy(connection_class, receive_module, asr_base_module):
    """普通回答也安装永久撤权；不依赖候选开关，不声明设备flush已协商。"""
    from core.handle import sendAudioHandle
    from core.providers.tts import base as tts_base
    from voice_interruption import install_voice_interruption
    result = install_voice_interruption(connection_class, receive_module, asr_base_module,
        sendAudioHandle, tts_base_module=tts_base)
    from voice_completion import install_completion_handoff
    install_completion_handoff(receive_module, asr_base_module)
    return result


def _completion_output_lease(connection):
    from voice_completion import output_lease
    return output_lease(connection)


def install_answer_completion(connection_class):
    """在顶层回答完成后归档实际助手文本，不侵入厂商源码。"""

    if getattr(connection_class, "_longmemory_completion_installed", False):
        return
    original = connection_class.chat
    capture = ContextVar("round_answer_capture", default=None)
    capture_lock = Lock()

    def chat(connection, query, depth=0):
        output_lease = _completion_output_lease(connection)
        if depth == 0 and output_lease is not None and not output_lease.current():
            return None  # 已排队但未开始的旧工作不再执行正式prepare。
        before = len(connection.dialogue.dialogue)
        memory = connection.memory
        owned = depth == 0 and callable(getattr(memory, "begin_turn", None))
        turn_key, token = memory.begin_turn() if owned else (None, None)
        record = {"answers": [], "superseded": False, "output_lease": output_lease}
        capture_token = None
        if owned:
            with capture_lock:
                previous = getattr(connection, "_longmemory_active_completion", None)
                if previous is not None:
                    previous["superseded"] = True
                connection._longmemory_active_completion = record
                dialogue = connection.dialogue
                if not getattr(dialogue, "_longmemory_capture_installed", False) and callable(getattr(dialogue, "put", None)):
                    put = dialogue.put

                    def capture_put(message):
                        current = capture.get()
                        lease = current.get("output_lease") if current is not None else None
                        if lease is not None and getattr(message, "role", None) == "assistant":
                            # 与音频撤权共用同一锁，不能在检查后被撤权，再把旧助手文本写入历史。
                            with lease.state.lock:
                                if not lease.current():
                                    return None
                                if isinstance(getattr(message, "content", None), str) and message.content.strip():
                                    current["answers"].append(message.content)
                                return put(message)
                        if (current is not None and getattr(message, "role", None) == "assistant"
                                and isinstance(getattr(message, "content", None), str) and message.content.strip()):
                            current["answers"].append(message.content)
                        return put(message)

                    dialogue.put = capture_put
                    dialogue._longmemory_capture_installed = True
            capture_token = capture.set(record)
        adapter = getattr(connection, "_longmemory_proposal_adapter", None)
        if adapter is not None:
            adapter.guard_history(connection)
        try:
            result = original(connection, query, depth)
        except BaseException:
            if owned:
                try:
                    memory.cancel_turn(turn_key, "chat_failed")
                except Exception:
                    connection.logger.bind(tag="LongMemory").error("回答失败状态回执失败；不会自动重试")
            raise
        finally:
            if owned:
                memory.end_turn(token)
                capture.reset(capture_token)
                with capture_lock:
                    if getattr(connection, "_longmemory_active_completion", None) is record:
                        connection._longmemory_active_completion = None
        # 上游 chat() 的正常分支并不都返回 True：direct_answer 在已经把
        # 助手文本写入对话并送入 TTS 队列后会直接返回 None。因此完成依据
        # 必须是“本次顶层调用新增了助手文本”，不能依赖厂商内部返回值。
        if (depth == 0 and query
                and callable(getattr(memory, "record_completed_turn", None))):
            lease = record["output_lease"]
            revoked = lease is not None and not lease.current()
            answers = record["answers"] if owned else [
                item.content for item in connection.dialogue.dialogue[before:]
                if getattr(item, "role", None) == "assistant"
                and isinstance(getattr(item, "content", None), str)
                and item.content.strip()
            ]
            if answers:
                try:
                    if owned and (revoked or record["superseded"] or getattr(connection, "client_abort", False)):
                        memory.cancel_turn(turn_key, "superseded" if record["superseded"] else "cancelled")
                    elif owned:
                        if lease is None:
                            memory.record_completed_turn("\n".join(answers), turn_key=turn_key)
                        elif type(getattr(memory, "completion_guard_protocol", None)) is int and memory.completion_guard_protocol == 1:
                            from voice_completion import completion_guard
                            memory.record_completed_turn("\n".join(answers), turn_key=turn_key,
                                completion_guard=completion_guard(lease))
                        else:
                            # 未声明原子领取支持时不冒充受保护完成；真实MemoryProvider与此处同批部署。
                            memory.cancel_turn(turn_key, "cancelled")
                    elif not revoked:
                        memory.record_completed_turn("\n".join(answers))
                except Exception:
                    # 语音回答已经进入播放队列，归档失败不能伪装成聊天失败；
                    # 只输出稳定错误，不记录回答正文。
                    connection.logger.bind(tag="LongMemory").error(
                        "回答完成回执失败；本轮不会自动重试"
                    )
            elif owned:
                try:
                    memory.cancel_turn(turn_key, "cancelled" if revoked or getattr(connection, "client_abort", False) else "chat_failed")
                except Exception:
                    connection.logger.bind(tag="LongMemory").error("未完成回答状态回执失败；不会自动重试")
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
    parser.add_argument("--voice-latency-mode", choices=["realtime", "original"], default="realtime")
    parser.add_argument("--enable-voice-preemptive", action="store_true",
                        default=os.environ.get("LONGMEMORY_VOICE_PREEMPTIVE_ENABLED") == "1")
    parser.add_argument("--voice-turn-end-mode", choices=["off", "shadow", "enabled"],
                        default=os.environ.get("LONGMEMORY_TURN_END_MODE", "off"))
    parser.add_argument("--voice-turn-end-model", type=Path,
                        default=os.environ.get("LONGMEMORY_TURN_END_MODEL") or None)
    parser.add_argument("--voice-turn-end-python", type=Path,
                        default=os.environ.get("LONGMEMORY_TURN_END_PYTHON") or None)
    parser.add_argument("--cosy-delivery-mode", choices=["buffered", "incremental", "adaptive"],
                        default=os.environ.get("LONGMEMORY_COSY_DELIVERY_MODE", "buffered"))
    parser.add_argument("--doubao-env", "--doubao-env-file", type=Path,
                        default=Path(__file__).resolve().parents[3] / "local/config/.env.doubao.local")
    args = parser.parse_args()
    if args.enable_voice_preemptive and (args.voice_mode != "pipeline" or args.voice_latency_mode != "realtime"):
        parser.error("voice_preemptive_requires_realtime_pipeline")
    if args.voice_mode != "pipeline" and (args.voice_turn_end_mode != "off"
                                         or args.cosy_delivery_mode != "buffered"):
        parser.error("advanced_voice_policy_requires_pipeline")
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
    from voice_persistent_session import install_persistent_device_session
    from voice_latency import install_audio_send_observer, install_voice_latency
    from voice_input_latency import install_voice_input_latency
    from voice_prediction import install_voice_prediction_shadow
    isolate_memory_initialization(ConnectionHandler, MemoryProvider)
    from core.providers.asr import base as asr_base
    install_voice_input_latency(asr_base)
    # 子类预识别须捕获已经加过输入计时的基类方法。这里只改小智子进程，
    # 不改系统环境或网页策略；面板选择在重启时生效。
    install_pipeline_latency_policy(ConnectionHandler, mode=args.voice_latency_mode,
                                    enable_asr_prefetch=True, enable_http_keepalive=True)
    turn_asr_class = None
    if args.voice_turn_end_mode != "off":
        # 接在已有预取包装器外层，清空上游音频前先取得真实PCM版本。
        from core.providers.asr import fun_local
        turn_asr_class = fun_local.ASRProvider
    detector_factory = None
    if args.voice_turn_end_python is not None:
        from voice_turn_end_sidecar import SidecarDetector
        detector_factory = lambda model: SidecarDetector(args.voice_turn_end_python, model)
    install_advanced_voice_policy(
        ConnectionHandler, turn_end_mode=args.voice_turn_end_mode,
        turn_end_model=args.voice_turn_end_model, asr_provider_class=turn_asr_class,
        cosy_delivery_mode=args.cosy_delivery_mode, detector_factory=detector_factory)
    if os.environ.get("LONGMEMORY_MEMORY_BACKEND") == "hy_memory":
        from core.providers.llm.openai import openai as provider_module
        from voice_budget import install_no_retry_gateway_client
        install_no_retry_gateway_client(provider_module)
    # 快速通道必须位于时序包装器内部，才能像普通回答一样记录真实首包。
    install_fast_voice_responses(ConnectionHandler)
    install_voice_latency(ConnectionHandler)
    install_audio_send_observer()
    if args.voice_latency_mode == "realtime":
        from voice_waiting import install_waiting_sender
        from core.handle import sendAudioHandle
        install_waiting_sender(sendAudioHandle)
        ConnectionHandler._longmemory_waiting_enabled = True
    install_answer_completion(ConnectionHandler)
    # 生命周期须包住快捷回复和完成归档：这些分支可能不进入原生chat/LLM。
    # provider在连接初始化时才绑定，因此此处仍先于任何实际provider创建。
    if args.enable_voice_preemptive:
        from core.providers.asr import fun_local
        install_voice_proposal_policy(ConnectionHandler, enabled=True, fun_local=fun_local, asr_base=asr_base)
    # 第一版只做无正文、无播放的封闭分支影子统计，为是否值得预合成提供证据。
    install_voice_prediction_shadow(ConnectionHandler)
    install_internal_end_prompt_boundary(receive_audio_handle)
    install_persistent_device_session(ConnectionHandler, receive_audio_handle)
    # 所有既有ASR/等待音/AE等包装完成后装配，保留各自别名；普通candidate OFF也有效。
    install_voice_output_revocation_policy(ConnectionHandler, receive_audio_handle, asr_base)
    if args.device_control:
        from core.websocket_server import WebSocketServer
        from control_http import install_control_server
        install_control_server(WebSocketServer, ConnectionHandler)
    runpy.run_path(str(root / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
