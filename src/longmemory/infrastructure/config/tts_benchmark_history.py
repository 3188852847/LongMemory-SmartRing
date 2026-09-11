"""TTS 固定用例测试历史的本机原子档案。

这里只保存合成耗时与 WAV 摘要，不保存聊天、记忆、用户录音或生成音频。
不同 TTS 需要重启切换，因此这个小档案负责把跨启动结果留在同一张对照表中。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from uuid import uuid4


SCHEMA_VERSION = 2
MAX_RUNS = 120
MAX_FILE_BYTES = 512 * 1024
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")


class TTSBenchmarkHistory:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load_document(self) -> dict[str, object]:
        if not self.path.exists():
            return {"schema_version": SCHEMA_VERSION, "runs": []}
        if not self.path.is_file() or self.path.is_symlink() or self.path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("tts_benchmark_history_invalid")
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("tts_benchmark_history_invalid") from error
        if not isinstance(document, dict) or set(document) != {"schema_version", "runs"}:
            raise ValueError("tts_benchmark_history_invalid")
        if document["schema_version"] not in {1, SCHEMA_VERSION} or not isinstance(document["runs"], list):
            raise ValueError("tts_benchmark_history_invalid")
        if document["schema_version"] == 1:
            if any(not isinstance(item, dict) for item in document["runs"]):
                raise ValueError("tts_benchmark_history_invalid")
            # V1 运行均使用提供器默认行为。VoxCPM2 因而可能混合真实生成与重复句
            # 缓存命中；迁移只补事实标签，不改写任何既有测量值。
            document = {
                "schema_version": SCHEMA_VERSION,
                "runs": [dict(item, cache_policy="provider_default") for item in document["runs"]],
            }
        if len(document["runs"]) > MAX_RUNS or any(not self._valid_run(item) for item in document["runs"]):
            raise ValueError("tts_benchmark_history_invalid")
        return document

    @staticmethod
    def _valid_run(item: object) -> bool:
        if not isinstance(item, dict) or set(item) != {
            "id", "backend", "case_id", "started_at", "adapter_delivery",
            "first_audio_available_ms", "completed_ms", "audio_bytes", "content_type", "wave",
            "cache_policy",
        }:
            return False
        numbers = (item["first_audio_available_ms"], item["completed_ms"])
        return (
            isinstance(item["id"], str) and len(item["id"]) == 32
            and isinstance(item["backend"], str) and _IDENTIFIER.fullmatch(item["backend"]) is not None
            and isinstance(item["case_id"], str) and _IDENTIFIER.fullmatch(item["case_id"]) is not None
            and isinstance(item["started_at"], str) and 10 <= len(item["started_at"]) <= 40
            and item["adapter_delivery"] in {"buffered", "audio_stream"}
            and item["cache_policy"] in {"provider_default", "bypass_local_cache"}
            and all(type(value) in {int, float} and 0 <= value <= 600_000 for value in numbers)
            and type(item["audio_bytes"]) is int and 0 < item["audio_bytes"] <= 8 * 1024 * 1024
            and isinstance(item["content_type"], str) and 1 <= len(item["content_type"]) <= 80
            and (item["wave"] is None or isinstance(item["wave"], dict))
        )

    def list_runs(self) -> list[dict[str, object]]:
        return list(reversed(self._load_document()["runs"]))

    def append(self, result: dict[str, object]) -> str:
        document = self._load_document()
        run_id = uuid4().hex
        record = {
            "id": run_id,
            "backend": result["backend"],
            "case_id": result["case"]["id"],
            "started_at": result["started_at"],
            "adapter_delivery": result["adapter_delivery"],
            "first_audio_available_ms": result["first_audio_available_ms"],
            "completed_ms": result["completed_ms"],
            "audio_bytes": result["audio_bytes"],
            "content_type": result["content_type"],
            "wave": result["wave"],
            "cache_policy": result["cache_policy"],
        }
        if not self._valid_run(record):
            raise ValueError("tts_benchmark_result_invalid")
        runs = [*document["runs"], record][-MAX_RUNS:]
        encoded = json.dumps(
            {"schema_version": SCHEMA_VERSION, "runs": runs}, ensure_ascii=False,
            indent=2, allow_nan=False,
        )
        if len(encoded.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("tts_benchmark_history_too_large")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, self.path)
        return run_id
