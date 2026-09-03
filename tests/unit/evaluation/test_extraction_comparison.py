"""新条件保持对照隔离；候选替身只能验证工程流程与可观测性。"""

import json

import pytest

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.evaluation.comparison import runner
from longmemory.evaluation.comparison.dataset import load_dataset
from longmemory.evaluation.comparison.methods import REGISTERED_METHODS, METHOD_NAME
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.adapters.llm.candidate_extractor import OpenAICompatibleCandidateProducer


class QuoteStub:
    """逐字保留用户正文，故意不模拟真正语义提取或生成预期答案。"""
    def __init__(self):
        self.seen = []
    def propose(self, *, source_text):
        self.seen.append(source_text)
        return json.dumps({"schema_version": 1, "operation": "ADD",
                           "facts": [{"content": source_text, "quote": source_text}]}, ensure_ascii=False)


def run(tmp_path, producer, extraction_config=None):
    return runner.run_comparison(load_dataset(runner.DEFAULT_DATASET), FakeAnswerGenerator,
                                 output_root=tmp_path, model_config={"provider": "fake"},
                                 methods=REGISTERED_METHODS, candidate_producer_factory=lambda: producer,
                                 extraction_config=extraction_config or {"provider": "fake", "model": "quote-stub"})


def test_three_groups_manifest_cost_and_no_question_extraction(tmp_path):
    producer = QuoteStub()
    directory, report = run(tmp_path, producer)
    assert report["status"] == "completed" and len(report["questions"]) == 24
    assert len(producer.seen) == 7
    assert not any("holdout" in r["question_id"] for r in report["questions"])
    assert all(r["state_unchanged"] for r in report["questions"])
    diagnostic = report["builds"][METHOD_NAME]["extraction"]
    assert diagnostic["request_attempts"] == 7 and len(diagnostic["events"]) == 14
    assert all(r["status"] == "completed" for r in diagnostic["events"])
    assert sum(r["request_attempts"] for r in diagnostic["events"]) == 7
    assert report["manifest"]["method_settings"][METHOD_NAME]["retrieval"] == "unchanged_v1_keyword"
    assert report["manifest"]["method_settings"][METHOD_NAME]["prompt_sha256"] is None
    assert (directory / METHOD_NAME / "memory.db").is_file()
    # 新提取条件可保存非第一人称陈述；不把替身答案分数当质量证据。
    rows = {(r["method"], r["question_id"]): r for r in report["questions"]}
    assert rows["longmemory_v1", "dev-research"]["evidence_complete"] is False
    assert rows[METHOD_NAME, "dev-research"]["evidence_complete"] is True


@pytest.mark.parametrize("interrupt", [False, True])
def test_failed_or_interrupted_build_keeps_all_rows_and_diagnostics(tmp_path, interrupt):
    class Broken:
        def propose(self, **kwargs):
            if interrupt:
                raise KeyboardInterrupt
            raise RuntimeError("PRIVATE_SENTINEL")
    directory, report = run(tmp_path, Broken())
    expected = "interrupted" if interrupt else "failed"
    assert report["builds"][METHOD_NAME]["status"] == expected
    assert report["builds"][METHOD_NAME]["extraction"]["request_attempts"] == 1
    rows = [r for r in report["questions"] if r["method"] == METHOD_NAME]
    assert len(rows) == 8 and all(r["status"] == expected for r in rows)
    saved = (directory / "report.json").read_text(encoding="utf-8")
    assert "PRIVATE_SENTINEL" not in saved
    assert json.loads(saved)["builds"][METHOD_NAME]["extraction"]["events"][0]["status"] == expected
    assert report["summary"]["longmemory_v1"]["completed"] == 8


def test_new_method_requires_metadata_and_does_not_change_default(tmp_path):
    dataset = load_dataset(runner.DEFAULT_DATASET)
    with pytest.raises(ValueError):
        runner.run_comparison(dataset, FakeAnswerGenerator, output_root=tmp_path / "missing",
                              model_config={}, methods=REGISTERED_METHODS)
    assert not (tmp_path / "missing").exists()
    with pytest.raises(ValueError):
        runner.run_comparison(dataset, FakeAnswerGenerator, output_root=tmp_path / "secret",
                              model_config={}, methods=REGISTERED_METHODS,
                              candidate_producer_factory=QuoteStub, extraction_config={"api_key": "PRIVATE"})
    assert not (tmp_path / "secret").exists()
    _, report = runner.run_comparison(dataset, FakeAnswerGenerator, output_root=tmp_path,
                                      model_config={"provider": "fake"})
    assert len(report["questions"]) == 16 and METHOD_NAME not in report["manifest"]["method_settings"]


def test_cli_explicit_opt_in_tokens_and_no_silent_fake(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "load_model_settings", lambda **kwargs: ModelSettings())
    assert runner.main(["--include-llm-extraction", "--output-root", str(tmp_path / "not-created")]) == 2
    assert not (tmp_path / "not-created").exists()
    config = ModelSettings(provider="openai_compatible", base_url="https://example.invalid/v1",
                           api_key="synthetic", model="synthetic", max_tokens=128)
    monkeypatch.setattr(runner, "load_model_settings", lambda **kwargs: config)
    captured = {}
    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return tmp_path, {"status": "completed", "summary": {}}
    monkeypatch.setattr(runner, "run_comparison", fake_run)
    assert runner.main(["--provider", "openai_compatible", "--include-llm-extraction", "--extraction-max-tokens", "2048"]) == 0
    assert captured["methods"] == REGISTERED_METHODS
    assert captured["model_config"]["max_tokens"] == 128
    assert captured["extraction_config"]["max_tokens"] == 2048
    assert "7 次额外提取请求" in capsys.readouterr().out


def test_compatible_transport_to_validation_storage_and_frozen_comparison(tmp_path):
    settings = ModelSettings(provider="openai_compatible", base_url="https://example.invalid/v1",
                             api_key="synthetic", model="synthetic")
    requests = []
    def transport(config, raw):
        payload = json.loads(raw)
        assert len(payload["messages"]) == 2
        source = json.loads(payload["messages"][1]["content"])["source_text"]
        requests.append(source)
        content = QuoteStub().propose(source_text=source)
        return 200, json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": content}}]}).encode()
    producer = OpenAICompatibleCandidateProducer(settings, transport=transport)
    _, report = run(tmp_path, producer, {"provider": "openai_compatible", "model": "synthetic-http-transport"})
    assert len(requests) == 7
    assert report["summary"][METHOD_NAME]["completed"] == 8
    assert all(r["state_unchanged"] for r in report["questions"])
    assert report["builds"][METHOD_NAME]["extraction"]["request_attempts"] == 7
    assert len(report["manifest"]["method_settings"][METHOD_NAME]["prompt_sha256"]) == 64
