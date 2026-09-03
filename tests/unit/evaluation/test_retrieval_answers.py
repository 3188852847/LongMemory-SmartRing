"""冻结检索回答协议测试，全部合成数据，禁止真实外部模型请求。"""

from dataclasses import replace
import json

import pytest

from longmemory.core.memory.retrieval.vector import fingerprint
from longmemory.evaluation.comparison import retrieval, retrieval_answers as qa, runner, review
from longmemory.evaluation.comparison.methods import METHOD_NAME, state_digest
from longmemory.methods.contracts import MemorySupport, RetrievedTrace


@pytest.fixture
def inputs(tmp_path):
    dataset = runner.load_dataset(runner.DEFAULT_DATASET)
    class Producer:
        def propose(self, *, source_text):
            return json.dumps({"schema_version": 1, "operation": "ADD",
                "facts": [{"content": source_text, "quote": source_text}]})
    class Encoder:
        metadata = {"provider": "test_only"}
        identity = fingerprint(metadata)
        def encode_documents(self, texts):
            return [[1.0, 0.1] for _ in texts]
        def encode_query(self, text):
            return [1.0, 0.1]
    source, _ = runner.run_comparison(dataset, runner.FakeAnswerGenerator,
        output_root=tmp_path / "source", model_config={"provider": "fake"},
        methods=("longmemory_v1", METHOD_NAME), candidate_producer_factory=Producer,
        extraction_config={"provider": "fake"})
    cached, _ = retrieval.run_retrieval(source / "report.json", dataset, Encoder(), output_root=tmp_path / "cached")
    return cached / "report.json", source / "report.json", dataset


def execute(inputs, tmp_path, factory=runner.FakeAnswerGenerator, **kwargs):
    cached, source, dataset = inputs
    return qa.run_answers(cached, source, dataset, factory, output_root=tmp_path / "answers",
                          model_config={"provider": "fake"}, **kwargs)


def test_frozen_replay_budget_labels_and_review_compatibility(inputs, tmp_path):
    cached, source, dataset = inputs
    before = (state_digest(cached.parent), state_digest(source.parent))
    calls, instances = [], []
    class Spy:
        def __init__(self):
            instances.append(self)
        def generate(self, **kwargs):
            calls.append(kwargs)
            return "合成回答"
    labelled = replace(dataset, questions=tuple(replace(q, answer_contains="SECRET_LABEL") for q in dataset.questions))
    path, report = execute((cached, source, labelled), tmp_path, Spy, context_chars=40)
    assert report["status"] == "completed" and len(report["questions"]) == len(instances) == 32
    assert report["answer_attempts"] == 32
    assert all(set(c) == {"query", "memory_context"} and len(c["memory_context"]) <= 40 for c in calls)
    assert "SECRET_LABEL" not in repr(calls)
    assert not any(q.query in [c["query"] for c in calls] for q in dataset.questions if q.split == "holdout")
    assert before == (state_digest(cached.parent), state_digest(source.parent))
    assert all(r["state_unchanged"] for r in report["questions"])
    assert report["manifest"]["new_extraction_requests"] == report["manifest"]["new_embedding_requests"] == 0
    assert all(r["evidence_metric_scope"] == "injected_whole_items" for r in report["questions"])
    assert report["questions"][0]["method"] != report["questions"][4]["method"]
    assert any(r["retrieved_evidence_complete"] and not r["evidence_complete"] for r in report["questions"])
    draft = review.prepare(path / "report.json", reviewer="synthetic", reviewer_kind="assistant")
    assert len(draft["items"]) == 32  # 四组唯一 ID 可复用现有离线复核，不改旧报告协议。


def test_budget_whole_prefix_and_empty():
    items = (RetrievedTrace("a", "很长" * 20, ("e01",)), RetrievedTrace("b", "短", ("e03",)))
    support = MemorySupport("call", qa.render(items), items)
    assert qa.budget_support(support, 30).context == ""  # 不跳过排名第一条。
    exact = len(qa.render(items[:1]))
    assert qa.budget_support(support, exact).retrieved == items[:1]
    assert qa.budget_support(MemorySupport("empty", "", ()), 100).context == ""


@pytest.mark.parametrize("mutation", ["duplicate", "query", "context", "source", "index", "incomplete", "manifest"])
def test_reject_bad_inputs_before_any_answer(inputs, tmp_path, mutation):
    cached, source, dataset = inputs
    report = json.loads(cached.read_text(encoding="utf-8"))
    if mutation == "duplicate":
        report["questions"][-1] = report["questions"][0]
    elif mutation == "query":
        report["questions"][0]["query"] = "forged"
    elif mutation == "context":
        report["questions"][0]["support"]["context"] = "forged"
    elif mutation == "source":
        (source.parent / "longmemory_v1/extra").write_text("change")
    elif mutation == "index":
        (cached.parent / "longmemory_v1-vectors.json").write_text("{}")
    elif mutation == "incomplete":
        report["status"] = "incomplete"
    else:
        report["manifest"]["split"] = "holdout"
    cached.write_text(json.dumps(report), encoding="utf-8")
    def no_call():
        pytest.fail("invalid source must not construct a generator")
    with pytest.raises((ValueError, KeyError)):
        execute(inputs, tmp_path, no_call)
    assert not (tmp_path / "answers").exists()


@pytest.mark.parametrize("kind", ["error", "empty", "interrupt", "mutation"])
def test_failures_keep_denominator_no_retry_no_private_errors(inputs, tmp_path, kind):
    count = 0
    class Broken:
        def generate(self, **kwargs):
            nonlocal count
            count += 1
            if kind == "error":
                raise RuntimeError("SECRET_ERROR")
            if kind == "empty":
                return " "
            if kind == "interrupt":
                raise KeyboardInterrupt
            (inputs[0].parent / "changed").write_text("changed")
            return "answer"
    directory, report = execute(inputs, tmp_path, Broken)
    assert report["status"] == "incomplete" and len(report["questions"]) == 32
    assert count == report["answer_attempts"] == (1 if kind in {"interrupt", "mutation"} else 32)
    assert sum(s["total"] for s in report["summary"].values()) == 32
    assert "SECRET_ERROR" not in (directory / "report.json").read_text(encoding="utf-8")
    if kind == "mutation":
        assert report["questions"][0]["state_unchanged"] is False
        assert report["questions"][0]["status"] == "failed"


def test_invalid_budget_output_and_model_metadata(inputs, tmp_path):
    cached, source, dataset = inputs
    for budget in (True, 0, 16001):
        with pytest.raises(ValueError):
            execute(inputs, tmp_path, context_chars=budget)
    with pytest.raises(ValueError):
        qa.run_answers(cached, source, dataset, runner.FakeAnswerGenerator,
                       output_root=tmp_path / "out", model_config={"api_key": "DO_NOT_PERSIST"})
    with pytest.raises(ValueError):
        qa.run_answers(cached, source, dataset, runner.FakeAnswerGenerator,
                       output_root=source.parent / "out", model_config={"provider": "fake"})


def test_cli_fake_and_invalid_source(inputs, tmp_path, capsys):
    cached, source, _ = inputs
    args = ["--retrieval-report", str(cached), "--source-report", str(source),
            "--output-root", str(tmp_path / "cli")]
    assert qa.main(args) == 0
    assert "provider=fake" in capsys.readouterr().out
    assert qa.main(args + ["--context-chars", "0"]) == 2


def test_compatible_transport_has_same_prompt_no_history_or_labels(inputs, tmp_path):
    from longmemory.infrastructure.config.settings import ModelSettings
    settings = ModelSettings(provider="openai_compatible", model="synthetic-model",
        base_url="https://synthetic.invalid/v1", api_key="PRIVATE_TEST_KEY")
    bodies = []
    def transport(config, body):
        bodies.append(json.loads(body))
        return 200, json.dumps({"choices": [{"message": {"content": "不知道"},
                                            "finish_reason": "stop"}]}).encode()
    directory, report = execute(inputs, tmp_path,
        lambda: runner.OpenAICompatibleAnswerGenerator(settings, transport=transport))
    assert len(bodies) == 32 and report["status"] == "completed"
    for body in bodies:
        assert len(body["messages"]) == 3
        assert body["messages"][0] == {"role": "system", "content": runner.SYSTEM_PROMPT}
        evidence = json.loads(body["messages"][1]["content"])
        assert set(evidence) == {"memory_evidence"}
        assert body["max_tokens"] == settings.max_tokens and body["model"] == settings.model
    assert "PRIVATE_TEST_KEY" not in (directory / "report.json").read_text(encoding="utf-8")


def test_failed_scored_row_does_not_inflate_evidence():
    row = {"method": "group", "status": "failed", "expected_abstention": False,
           "evidence_complete": True, "answer_proxy_pass": True}
    result = qa.answer_summary([row])["group"]
    assert result["evidence_complete"] == result["answer_proxy_pass"] == 0
    assert result["answerable_denominator_all_questions"] == 1
