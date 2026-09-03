"""复核计数与模型运行隔离；失败/待评不能伪装成完整质量验收。"""

import json

import pytest

from longmemory.evaluation.comparison import review, runner
from longmemory.infrastructure.config.settings import ModelSettings


@pytest.fixture
def report_path(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"questions": [
        {"method": "a", "question_id": "q1", "status": "completed",
         "answer": "合成回答", "state_unchanged": True, "answer_proxy_pass": False},
        {"method": "a", "question_id": "q2", "status": "failed"},
    ]}), encoding="utf-8")
    return path


def test_review_separate_pending_and_unscorable_keep_denominator(report_path):
    original = report_path.read_bytes()
    sheet = review.prepare(report_path, reviewer="assistant-test", reviewer_kind="assistant")
    assert review.summarize_review(report_path, sheet)["methods"]["a"]["pending"] == 2
    sheet["items"][0].update(verdict="pass", rationale="事实正确；词面初筛误判。")
    sheet["items"][1].update(verdict="unscorable", rationale="模型调用失败，无回答。")
    result = review.summarize_review(report_path, sheet)
    assert result["methods"]["a"] == {"total": 2, "pass": 1, "fail": 0, "pending": 0, "unscorable": 1}
    assert result["reviewer_kind"] == "assistant"
    assert report_path.read_bytes() == original


@pytest.mark.parametrize("invalid", ["hash", "duplicate", "missing", "unknown", "reason", "failed_pass", "version", "reviewer"])
def test_invalid_review_rejected(report_path, invalid):
    sheet = review.prepare(report_path, reviewer="test", reviewer_kind="human")
    if invalid == "hash": sheet["report_sha256"] = "0" * 64
    if invalid == "duplicate": sheet["items"].append(sheet["items"][0])
    if invalid == "missing": sheet["items"].pop()
    if invalid == "unknown": sheet["items"][0]["question_id"] = "unknown"
    if invalid == "reason": sheet["items"][0]["verdict"] = "pass"
    if invalid == "failed_pass": sheet["items"][1].update(verdict="pass", rationale="不能通过")
    if invalid == "version": sheet["rubric"] = "unknown"
    if invalid == "reviewer": sheet["reviewer"] = ""
    with pytest.raises(ValueError):
        review.summarize_review(report_path, sheet)


def test_cli_never_overwrites_and_summarizes_offline(report_path, tmp_path, capsys):
    original = report_path.read_bytes()
    common = ["prepare", "--report", str(report_path), "--reviewer", "test", "--reviewer-kind", "human"]
    assert review.main([*common, "--output", str(report_path)]) == 2
    assert report_path.read_bytes() == original
    output = tmp_path / "review.json"
    assert review.main([*common, "--output", str(output)]) == 0
    assert review.main([*common, "--output", str(output)]) == 2
    assert review.main(["summarize", "--report", str(report_path), "--review", str(output)]) == 0
    assert '"pending": 2' in capsys.readouterr().out


@pytest.mark.parametrize("provider", ["fake", "openai_compatible"])
def test_runner_output_names_actual_provider_without_network(provider, tmp_path, monkeypatch, capsys):
    settings = ModelSettings() if provider == "fake" else ModelSettings(
        provider=provider, base_url="https://example.invalid/v1", api_key="synthetic", model="synthetic")
    monkeypatch.setattr(runner, "load_model_settings", lambda **kwargs: settings)
    # 不构造网络回答器；此测试只验证命令行文案与显式 provider 一致。
    monkeypatch.setattr(runner, "run_comparison", lambda *args, **kwargs:
                        (tmp_path, {"status": "completed", "summary": {}}))
    assert runner.main(["--provider", provider]) == 0
    output = capsys.readouterr().out
    assert ("本次使用 Fake" in output) == (provider == "fake")
    assert ("本次使用 openai_compatible" in output) == (provider == "openai_compatible")
    assert "词面初筛不是语义质量结论" in output
