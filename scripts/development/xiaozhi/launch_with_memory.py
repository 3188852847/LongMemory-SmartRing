"""固定小智快照的启动适配：每连接独立 Memory 对象，不改上游源码。

必须通过 setup.py start 启动，工作目录为上游服务根目录。
"""

from pathlib import Path
import argparse
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
        started = time.perf_counter()
        try:
            return await original_query(*args, **kwargs)
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
        if (depth == 0 and result and query
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-control", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    if args.device_control:
        from control_compatibility import verify_control_snapshot
        verify_control_snapshot(root)
    sys.path.insert(0, str(root))
    from core.connection import ConnectionHandler
    from core.providers.memory.longmemory.longmemory import MemoryProvider
    isolate_memory_initialization(ConnectionHandler, MemoryProvider)
    install_answer_completion(ConnectionHandler)
    if args.device_control:
        from core.websocket_server import WebSocketServer
        from control_http import install_control_server
        install_control_server(WebSocketServer, ConnectionHandler)
    runpy.run_path(str(root / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
