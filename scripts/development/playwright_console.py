"""为 Playwright 启动一次性 Fake 控制台，不读取真实配置或个人数据。"""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from aiohttp import web

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.entrypoints.api.chat_backend import ChatBackend
from longmemory.entrypoints.api.experiment_backend import ExperimentBackend
from longmemory.entrypoints.api.server import create_app
from longmemory.methods.longmemory_v1.method import LongMemoryV1


class OfflineBridge:
    """确定性离线设备替身；浏览器测试绝不向 SmartRing-Plus 发指令。"""

    async def status(self):
        return {
            "connection_count": 0,
            "ready": False,
            "read_volume_supported": False,
            "set_volume_supported": False,
            "allowed_volume": {"minimum": 5, "maximum": 60},
            "reason": "device_offline",
        }

    async def read_volume(self):
        raise AssertionError("Playwright 不应读取实机音量")

    async def set_volume(self, _volume):
        raise AssertionError("Playwright 不应设置实机音量")

    async def close(self):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port 必须在 1024–65535 之间")

    with TemporaryDirectory(prefix="longmemory-playwright-") as directory:
        root = Path(directory)
        database = root / "synthetic.db"
        LongMemoryV1(database).close()
        backend = ChatBackend(database, FakeAnswerGenerator())
        try:
            app = create_app(
                port=args.port,
                bridge=OfflineBridge(),
                database=database,
                chat_backend=backend,
                experiment_backend=ExperimentBackend(root / "experiments"),
            )
            web.run_app(app, host="127.0.0.1", port=args.port, access_log=None, print=None)
        finally:
            backend.close()


if __name__ == "__main__":
    main()
