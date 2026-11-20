"""为 Playwright 启动一次性 Fake 控制台，不读取真实配置或个人数据。"""

import argparse
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

from aiohttp import web

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.entrypoints.api.chat_backend import ChatBackend
from longmemory.entrypoints.api.server import create_app
from longmemory.infrastructure.config.round_skins import RoundSkinStore
from longmemory.infrastructure.media.round_wallpaper_library import RoundWallpaperLibrary
from longmemory.bootstrap import build_hy_memory_runtime
from longmemory.methods.hy_memory.settings import HySettings


class OfflineBridge:
    """确定性离线设备替身；浏览器测试绝不向 SmartRing-Plus 发指令。"""

    async def status(self):
        return {
            "connection_count": 0,
            "ready": False,
            "read_volume_supported": False,
            "set_volume_supported": False,
            "allowed_volume": {"minimum": 5, "maximum": 100},
            "reason": "device_offline",
        }

    async def read_volume(self):
        raise AssertionError("Playwright 不应读取实机音量")

    async def set_volume(self, _volume):
        raise AssertionError("Playwright 不应设置实机音量")

    async def close(self):
        return None


def offline_runtime(root):
    fixture = Path(__file__).resolve().parents[2] / "tests/fixtures/hy_memory_fake_worker.py"
    spec = importlib.util.spec_from_file_location("offline_hy_worker", fixture)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return build_hy_memory_runtime(settings=HySettings(user_id="local-browser-test"),
        state_directory=root / "hy-engine", source_path=root / "sources.db",
        create=True, client_factory=module.PersistentFakeClient)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--otto-assets", type=Path, help="显式绑定只读固定 Otto 资源；省略时不借用其他工作树")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port 必须在 1024–65535 之间")

    temporary_root = Path(__file__).resolve().parents[2] / "data/test-tmp/playwright-console"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="run-", dir=temporary_root) as directory:
        root = Path(directory)
        runtime = offline_runtime(root)
        database = runtime.database
        backend = ChatBackend(database, FakeAnswerGenerator(), runtime=runtime)
        # 仅复用版本化的内置皮肤；选择、自定义皮肤和媒体都属于本次临时工程。
        # create_app 的默认目录是日用项目，测试必须显式覆盖这两个本地资产入口。
        skins = RoundSkinStore(root)
        skins.skin_root = Path(__file__).resolve().parents[2] / "firmware/smartring_plus/skins"
        try:
            app = create_app(
                port=args.port,
                bridge=OfflineBridge(),
                database=database,
                chat_backend=backend,
                round_skin_store=skins,
                round_wallpaper_library=RoundWallpaperLibrary(root / "wallpapers"),
                allow_memory_correction=True,
                allow_memory_delete=True,
                otto_asset_root=args.otto_assets,
            )
            web.run_app(app, host="127.0.0.1", port=args.port, access_log=None, print=None)
        finally:
            backend.close()


if __name__ == "__main__":
    main()
