"""为 Playwright 启动一次性 Fake 控制台，不读取真实配置或个人数据。"""

import argparse
import sqlite3
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


def seed_owner_review_cases(database: Path) -> None:
    """只给一次性库写入可判定的重复与矛盾样例，验证所有者复核护栏。"""

    sources = [
        ("source-duplicate-a", "我喜欢乌龙茶。", "2026-09-13T00:00:00+00:00"),
        ("source-duplicate-b", "我确实喜欢乌龙茶", "2026-09-13T00:01:00+00:00"),
        ("source-conflict-a", "我喜欢喝咖啡。", "2026-09-13T00:02:00+00:00"),
        ("source-conflict-b", "我不喜欢喝咖啡。", "2026-09-13T00:03:00+00:00"),
    ]
    memories = [
        ("memory-duplicate-a", "用户喜欢乌龙茶。", sources[0][2]),
        ("memory-duplicate-b", "此人喜欢乌龙茶", sources[1][2]),
        ("memory-conflict-a", "用户喜欢喝咖啡。", sources[2][2]),
        ("memory-conflict-b", "用户不喜欢喝咖啡。", sources[3][2]),
    ]
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO conversation_messages(id,role,content,created_at) "
            "VALUES (?,'user',?,?)",
            sources,
        )
        connection.executemany(
            "INSERT INTO atomic_memories "
            "(id,subject_id,content,recorded_at,valid_from,valid_to,retired_at,"
            "superseded_by_id) VALUES (?,'user:self',?,?,NULL,NULL,NULL,NULL)",
            memories,
        )
        connection.executemany(
            "INSERT INTO memory_evidence(memory_id,source_message_id,source_type,linked_at) "
            "VALUES (?,?,'user_stated',?)",
            [
                (memory[0], source[0], source[2])
                for memory, source in zip(memories, sources, strict=True)
            ],
        )


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
        seed_owner_review_cases(database)
        backend = ChatBackend(database, FakeAnswerGenerator())
        try:
            app = create_app(
                port=args.port,
                bridge=OfflineBridge(),
                database=database,
                chat_backend=backend,
                experiment_backend=ExperimentBackend(root / "experiments"),
                allow_memory_correction=True,
                allow_memory_delete=True,
            )
            web.run_app(app, host="127.0.0.1", port=args.port, access_log=None, print=None)
        finally:
            backend.close()


if __name__ == "__main__":
    main()
