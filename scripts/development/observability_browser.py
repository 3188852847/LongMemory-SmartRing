"""Q 浏览器验收主机；真实观测 API，只注入声明为合成的阶段和日志元数据。"""

import hashlib
import importlib.util
from pathlib import Path
import secrets
import subprocess
from tempfile import TemporaryDirectory

from aiohttp import web

import longmemory
from longmemory.infrastructure.logging.diagnostics import Diagnostics
from longmemory.infrastructure.logging.retention import retention_plan


ROOT = Path(__file__).resolve().parents[2]


def seed_diagnostics(root, observer=None):
    """只生成测试输入，绝不声称实际 ASR、模型、合成或播放已经执行。"""
    if observer is None:
        observer = Diagnostics(root)
    else:
        # 仅此一次性主机的合成状态；每个用例重置，避免100条环形缓冲
        # 随前序页面请求逐出既定种子。不扩大生产容量，也不清理日用记录。
        with observer.lock:
            observer.rows.clear()
            observer.started.clear()
            observer.voice_rows.clear()
    old_round, current_round = secrets.token_hex(12), secrets.token_hex(12)
    trace = observer.begin("device", mutating=True)
    observer.finish(trace, 504, code="bridge_timeout")
    memory = observer.begin("memory_runtime", mutating=True)
    observer.bind_voice(memory[0], current_round)
    observer.stage(memory[0], "context_built")
    observer.finish(memory, 200)
    for round_id, event, sequence in (
        (old_round, "chat_entered", 1), (old_round, "cancelled", 2),
        (old_round, "tts_audio_ready", 3), (current_round, "chat_entered", 1),
        (current_round, "memory_response", 2), (current_round, "model_timeout", 4),
    ):
        observer.voice_event({"round_id": round_id, "event": event, "sequence": sequence})
    speech_id = secrets.token_hex(12)
    for event, sequence in (("tts_service_entered", 1), ("tts_service_failed", 3)):
        observer.voice_event({"round_id": current_round, "event": event, "sequence": sequence,
                              "source": "cosyvoice", "http_request_id": speech_id})
    # 定长合成占位文件仅核对实际 stat 预算；不读正文、不占用日用证据目录。
    path = root / "data/logs/diagnostics/api-99999-0123456789abcdef.jsonl"
    with path.open("wb") as output:
        output.truncate(65 * 1024 * 1024)
    return observer


def main():
    assert Path(longmemory.__file__).resolve().is_relative_to(ROOT)
    temporary = ROOT / "data/test-tmp/browser-q"
    temporary.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="diagnostics-", dir=temporary) as directory:
        observer = seed_diagnostics(Path(directory))
        spec = importlib.util.spec_from_file_location("q_synthetic_console", ROOT / "scripts/development/playwright_console.py")
        console = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(console)
        create_app = console.create_app
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        manifest = ROOT / "web/react-chat/dist/.vite/manifest.json"
        manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()

        def synthetic_app(**kwargs):
            app = create_app(**kwargs, diagnostics=observer)

            async def identity(_request):
                return web.json_response({"fixture": "Q_SYNTHETIC_OBSERVABILITY_ONLY", "revision": revision,
                                          "manifest_sha256": manifest_sha256, "device_playback": "unconfirmed"})

            async def reset(_request):
                seed_diagnostics(Path(directory), observer)
                return web.json_response({"fixture": "Q_SYNTHETIC_OBSERVABILITY_ONLY",
                                          "capacity": observer.capacity, "seeded_requests": len(observer.rows)})

            async def empty(_request):
                # 与第一次进程尚无事件时相同的实际数据模型，不回填伪造“成功”。
                return web.json_response({**Diagnostics().snapshot(), "logs": [], "log_retention": retention_plan(None)})

            async def truncated(_request):
                sample = Diagnostics()
                sample.write_failed = True  # 已在单元层用真实 OSError 验证的观测故障状态。
                round_id = secrets.token_hex(12)
                for _ in range(129):
                    sample.voice_event({"round_id": round_id, "event": "tts_service_entered", "sequence": 1,
                                        "source": "cosyvoice", "http_request_id": secrets.token_hex(12)})
                return web.json_response({**sample.snapshot(), "logs": [], "log_retention": retention_plan(None)})

            app.router.add_get("/api/q-fixture/identity", identity)
            app.router.add_post("/api/q-fixture/reset", reset)
            app.router.add_get("/api/q-fixture/empty", empty)
            app.router.add_get("/api/q-fixture/truncated", truncated)
            return app

        console.create_app = synthetic_app
        try:
            console.main()
        finally:
            observer.close()


if __name__ == "__main__":
    main()
