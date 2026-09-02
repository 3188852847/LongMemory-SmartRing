"""独立进程重启与固定合成数据的完全离线验收。"""

import json
import os
import subprocess
import sys

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.evaluation.runner import DEFAULT_DATASET, run_cases, main


def test_fixed_cases_and_ablation(tmp_path):
    dataset = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    results = run_cases(FakeAnswerGenerator(), dataset, temp_root=tmp_path)
    assert len(results) == 16
    assert all(row["error"] is None for row in results)
    assert all(row["write_ok"] and row["persistence_ok"] and row["retrieval_ok"] for row in results)
    assert all(row["answer_check_pass"] for row in results if row["mode"] == "with_memory_context")
    assert sum(row["answer_check_pass"] for row in results if row["mode"] == "without_memory_context") == 5
    known = [row for row in results if row["case_id"] == "remember"]
    assert known[0]["answer"] != known[1]["answer"]


def test_v2_preserves_original_cases_and_documents_call_budget():
    original = json.loads(DEFAULT_DATASET.with_name("memory_smoke_v1.json").read_text(encoding="utf-8"))
    current = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    assert current["cases"][:5] == original["cases"]
    assert sum(len(case["history"]) + 1 for case in current["cases"]) * 2 == 40


def test_report_does_not_overwrite_or_store_key(tmp_path, monkeypatch):
    monkeypatch.setenv("LONGMEMORY_LLM_API_KEY", "synthetic-secret")
    output = tmp_path / "report.json"
    assert main(["--provider", "fake", "--output", str(output)]) == 0
    content = output.read_text(encoding="utf-8")
    assert "synthetic-secret" not in content
    assert json.loads(content)["dataset_sha256"]
    assert json.loads(content)["scorer_version"] == "lexical-v2"
    assert json.loads(content)["scorer_sha256"]
    assert main(["--provider", "fake", "--output", str(output)]) == 2
    assert output.read_text(encoding="utf-8") == content


def test_two_cli_processes_recall_persistent_memory(tmp_path):
    command = [sys.executable, "-m", "longmemory", "--provider", "fake",
               "--database", str(tmp_path / "process.db"), "--log-file", str(tmp_path / "events.jsonl")]
    env = {key: value for key, value in os.environ.items() if not key.startswith("LONGMEMORY_")}
    env["PYTHONIOENCODING"] = "utf-8"
    first = subprocess.run(command, input="我养了一只叫豆包的猫。\n/exit\n", capture_output=True,
                           encoding="utf-8", timeout=20, env=env)
    assert first.returncode == 0, first.stderr
    second = subprocess.run(command, input="我的猫叫什么\n我的猫是什么颜色\n/memories\n/exit\n", capture_output=True,
                            encoding="utf-8", timeout=20, env=env)
    assert second.returncode == 0, second.stderr
    assert "你的猫叫豆包。" in second.stdout
    assert "我还没有找到相关记忆。" in second.stdout
    assert "本轮保存了" not in second.stdout
    assert second.stdout.count("记忆 ID：") == 1
