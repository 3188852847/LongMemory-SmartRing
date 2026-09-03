"""固定小智快照的启动适配：每连接独立 Memory 对象，不改上游源码。

必须通过 setup.py start 启动，工作目录为上游服务根目录。
"""

from pathlib import Path
import argparse
import runpy
import sys


def isolate_memory_initialization(connection_class, provider_class):
    original = connection_class._initialize_memory

    def initialize(connection):
        name = connection.config["selected_module"]["Memory"]
        config = connection.config["Memory"][name]
        if config.get("type") == "longmemory":
            # 原实例在服务启动时生成并共享；必须在设备身份绑定前替换，
            # 即使非法设备初始化失败，它也不能复用合法设备的记忆对象。
            connection.memory = provider_class(config)
        return original(connection)

    connection_class._initialize_memory = initialize


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
    if args.device_control:
        from core.websocket_server import WebSocketServer
        from control_http import install_control_server
        install_control_server(WebSocketServer, ConnectionHandler)
    runpy.run_path(str(root / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
