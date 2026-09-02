"""固定合成样例的工程验收；只比较有/无上下文，不宣称通用模型能力。"""

import argparse
import hashlib
import json
import subprocess
import tempfile
import platform
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.adapters.llm.openai_compatible import OpenAICompatibleAnswerGenerator, SYSTEM_PROMPT
from longmemory.application.chat.contracts import AnswerGenerationError, AnswerGenerator
from longmemory.bootstrap import build_application
from longmemory.infrastructure.config.settings import load_model_settings


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = ROOT / "datasets/synthetic/memory_smoke_v1.json"
REFUSAL_MARKERS = ("不知道", "不清楚", "没有找到", "没有相关", "没有提供", "未提供", "无法确定", "没有记录", "未记录", "不确定")


class ContextSwitch:
    """对照仅关闭回答阶段的记忆注入，写入和检索条件保持一致。"""

    def __init__(self, generator: AnswerGenerator, enabled: bool):
        self.generator = generator
        self.enabled = enabled

    def generate(self, *, query: str, memory_context: str) -> str:
        return self.generator.generate(query=query, memory_context=memory_context if self.enabled else "")


def run_cases(generator: AnswerGenerator, dataset: dict, *, temp_root: Path | None = None) -> list[dict]:
    """每个用例、每个组使用独立临时库，绝不打开个人数据库。"""

    results = []
    for case in dataset["cases"]:
        for enabled in (True, False):
            mode = "with_memory_context" if enabled else "without_memory_context"
            with tempfile.TemporaryDirectory(prefix="longmemory-eval-", dir=temp_root) as directory:
                path = Path(directory) / "synthetic.db"
                wrapper = ContextSwitch(generator, enabled)
                app = build_application(database_path=path, answer_generator=wrapper)
                try:
                    for text in case["history"]:
                        app.chat(text)
                    before = tuple(item.memory for item in app.list_memories())
                    app.close()
                    app = build_application(database_path=path, answer_generator=wrapper)
                    persistence_ok = before == tuple(item.memory for item in app.list_memories())
                    response = app.chat(case["query"])
                    contents = [item.memory.content for item in app.list_memories()]
                    retrieved = [item.content for item in response.retrieved_memories]
                    refusal = any(marker in response.answer for marker in REFUSAL_MARKERS)
                    # 两组必须使用同一份题目真值；不能为了让无记忆组通过而改答案。
                    requires_refusal = case["abstain"]
                    # 简单词面代理：保留原回答供人工复核，不能作为语义正确性的最终裁判。
                    answer_ok = (refusal if requires_refusal else
                                 case["answer_contains"] in response.answer and not refusal)
                    results.append({
                        "case_id": case["id"], "category": case["category"], "mode": mode,
                        "write_ok": contents == case["memories"], "persistence_ok": persistence_ok,
                        "retrieval_ok": retrieved == case["retrieved"],
                        "answer_check_pass": answer_ok, "expected_abstention": requires_refusal,
                        "answer": response.answer, "error": None,
                    })
                except AnswerGenerationError as error:
                    results.append({"case_id": case["id"], "mode": mode, "error": str(error)})
                finally:
                    app.close()
    return results


def provenance() -> dict:
    """即使工作区未提交，也以源码哈希标记实际测试代码。"""

    digest = hashlib.sha256()
    for path in sorted((ROOT / "src").rglob("*.py")):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, stderr=subprocess.DEVNULL, text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, None
    return {"commit": commit, "dirty": dirty, "source_sha256": digest.hexdigest()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="合成工程验收：回答上下文消融对照")
    parser.add_argument("--provider", choices=("fake", "openai_compatible"))
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        settings = load_model_settings(provider=args.provider)
        raw = args.dataset.read_bytes()
        dataset = json.loads(raw)
    except (ValueError, OSError):
        print("评估配置或数据集无效，请检查本地文件和模型环境变量。")
        return 2
    generator = FakeAnswerGenerator() if settings.provider == "fake" else OpenAICompatibleAnswerGenerator(settings)
    if settings.provider != "fake" and settings.allow_http:
        print("警告：即将通过明文 HTTP 发送凭据与合成文本，请只在已确认风险的校园网运行。")
    output = args.output or ROOT / "experiments/runs" / f"smoke-{uuid4().hex}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    # 独占创建，拒绝覆盖历史结果；先预留输出文件，避免跑完昂贵请求才发现路径冲突。
    try:
        stream = output.open("x", encoding="utf-8")
    except OSError:
        print("无法创建报告文件（可能已存在）；请选择新路径，不覆盖历史结果。")
        return 2
    started_at = datetime.now(UTC).isoformat()
    with stream:
        results = run_cases(generator, dataset)
        report = {
            "schema_version": 1, "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "code": provenance(), "dataset_version": dataset["version"],
            "runtime": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version},
            "dataset_sha256": hashlib.sha256(raw).hexdigest(),
            "provider": settings.provider, "model": settings.model if settings.provider != "fake" else "fake-rule-v1",
            "config": {"max_tokens": settings.max_tokens, "timeout_seconds": settings.timeout_seconds, "stream": False},
            "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
            "comparison": "仅关闭回答上下文；两组都运行相同写入/检索流程。",
            "scoring": "合成样例词面代理，拒答与正确性需人工复核，不是模型准确率。",
            "results": results,
        }
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(f"报告：{output.resolve()}")
    for mode in ("with_memory_context", "without_memory_context"):
        rows = [row for row in results if row["mode"] == mode]
        passed = sum(all(row.get(key, False) for key in ("write_ok", "persistence_ok", "retrieval_ok", "answer_check_pass")) for row in rows)
        print(f"{mode}: {passed}/{len(rows)} 个合成用例通过全部工程检查")
    # 对照组答不出有记忆才能回答的题目是预期现象，不算运行故障。
    return 0 if all(row.get("error") is None for row in results) and all(
        all(row.get(key, False) for key in ("write_ok", "persistence_ok", "retrieval_ok", "answer_check_pass"))
        for row in results if row["mode"] == "with_memory_context"
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
