from dataclasses import replace
import json

import pytest

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.core.memory.retrieval.vector import fingerprint
from longmemory.evaluation.comparison import retrieval, runner
from longmemory.evaluation.comparison.dataset import load_dataset
from longmemory.evaluation.comparison.methods import state_digest, METHOD_NAME
from longmemory.methods.contracts import MemorySupport, RetrievedTrace


class FakeEncoder:
    """仅验证排序、隔离和错误处理，不冒充真实语义模型。"""
    metadata = {"provider": "test_only", "model": "synthetic-two-dim"}
    identity = fingerprint(metadata)

    def __init__(self):
        self.documents, self.queries = [], []

    def encode_documents(self, texts):
        self.documents.extend(texts)
        return [[1.0, 0.1] for _ in texts]

    def encode_query(self, text):
        self.queries.append(text)
        return [1.0, 0.1]


@pytest.fixture
def source(tmp_path):
    dataset = load_dataset(runner.DEFAULT_DATASET)
    class Producer:
        def propose(self, *, source_text):
            return json.dumps({"schema_version": 1, "operation": "ADD",
                               "facts": [{"content": source_text, "quote": source_text}]})
    directory, _ = runner.run_comparison(dataset, FakeAnswerGenerator, output_root=tmp_path / "source",
        model_config={"provider": "fake"}, methods=("longmemory_v1", METHOD_NAME),
        candidate_producer_factory=Producer, extraction_config={"provider": "fake"})
    return directory / "report.json", dataset


def test_reuses_exact_corpus_preserves_old_files_and_has_no_labels(source, tmp_path):
    path, dataset = source
    before = state_digest(path.parent)
    encoder = FakeEncoder()
    changed = replace(dataset, questions=tuple(replace(q, answer_contains="SECRET_LABEL_SENTINEL") for q in dataset.questions))
    directory, report = retrieval.run_retrieval(path, changed, encoder, output_root=tmp_path / "output")
    assert state_digest(path.parent) == before
    assert report["status"] == "completed" and len(report["questions"]) == 32
    assert report["manifest"]["new_llm_requests"] == 0
    assert len(encoder.queries) == 16
    assert "SECRET_LABEL_SENTINEL" not in repr(encoder.documents + encoder.queries)
    assert not any(q.id.startswith("holdout") and q.query in encoder.queries for q in dataset.questions)
    assert all(r["state_unchanged"] for r in report["questions"])
    assert all("answer" not in r for r in report["questions"])
    assert len(list(directory.glob("*-vectors.json"))) == 2
    saved = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    assert saved["summary"] == report["summary"]
    original = json.loads(path.read_text(encoding="utf-8"))
    for row in saved["questions"]:
        if row["strategy"] == "original_keyword":
            old = next(r for r in original["questions"] if (r["method"], r["question_id"]) == (row["method"], row["question_id"]))
            assert row["support"]["retrieved"] == old["support"]["retrieved"]


def test_source_mutation_rejected_before_encoding(source, tmp_path):
    path, dataset = source
    (path.parent / "longmemory_v1/unexpected").write_text("change")
    encoder = FakeEncoder()
    with pytest.raises(ValueError):
        retrieval.run_retrieval(path, dataset, encoder, output_root=tmp_path / "out")
    assert encoder.documents == [] and not (tmp_path / "out").exists()


def test_dataset_mismatch_and_output_under_source_rejected(source, tmp_path):
    path, dataset = source
    with pytest.raises(ValueError):
        retrieval.run_retrieval(path, replace(dataset, sha256="wrong"), FakeEncoder(), output_root=tmp_path / "out")
    with pytest.raises(ValueError):
        retrieval.run_retrieval(path, dataset, FakeEncoder(), output_root=path.parent / "out")


@pytest.mark.parametrize("phase", ["build", "query", "interrupt"])
def test_failure_records_all_rows_without_retry_or_private_error(source, tmp_path, phase):
    path, dataset = source
    class Broken(FakeEncoder):
        def encode_documents(self, texts):
            if phase == "build":
                raise ValueError("PRIVATE_ERROR")
            return super().encode_documents(texts)
        def encode_query(self, text):
            if phase == "interrupt":
                raise KeyboardInterrupt
            self.queries.append(text)
            raise ValueError("PRIVATE_ERROR")
    encoder = Broken()
    directory, report = retrieval.run_retrieval(path, dataset, encoder, output_root=tmp_path / "out")
    assert report["status"] == "incomplete" and len(report["questions"]) == 32
    assert "PRIVATE_ERROR" not in (directory / "report.json").read_text(encoding="utf-8")
    if phase == "query":
        assert len(encoder.queries) == 16
        assert sum(r["status"] == "completed" for r in report["questions"]) == 16
    if phase == "build":
        assert all(r["status"] == "failed" for r in report["questions"])
    if phase == "interrupt":
        assert any(r["status"] == "interrupted" for r in report["questions"])


def test_query_mutation_blocks_remaining_questions(source, tmp_path):
    path, dataset = source
    class Corrupt(FakeEncoder):
        def encode_query(self, text):
            (path.parent / "longmemory_v1/changed").write_text("changed")
            return super().encode_query(text)
    _, report = retrieval.run_retrieval(path, dataset, Corrupt(), output_root=tmp_path / "out")
    rows = [r for r in report["questions"] if r["method"] == "longmemory_v1"]
    assert rows[1]["error"] == "frozen_state_changed"
    assert all(r["error"] == "previous_freeze_violation" for r in rows[2:])
    assert report["summary"]["longmemory_v1/dense_cosine"]["evidence_complete"] == 0


def test_rank_metric_requires_sufficient_evidence_not_just_first_hit():
    dataset = load_dataset(runner.DEFAULT_DATASET)
    q = replace(dataset.questions[0], evidence_sets=(("e01", "e03"),))
    items = tuple(RetrievedTrace(str(i), "合成", (source,)) for i, source in enumerate(["e01", "e01", "e03"]))
    result = retrieval.retrieval_metrics(q, MemorySupport("id", "text", items))
    assert result["first_sufficient_rank"] == 3 and result["fully_redundant_source_items"] == 1
    unknown = replace(q, abstain=True, evidence_sets=())
    assert retrieval.retrieval_metrics(unknown, MemorySupport("id", "text", items))["evidence_complete"] is None


def test_empty_corpus_and_empty_recall_are_success(source, tmp_path):
    path, dataset = source
    # 来源校验不能绕过，因此另建一个只有不值得提取的历史的合法合成实验。
    modified = replace(dataset, history=tuple(replace(e, content="你好") for e in dataset.history))
    folder, _ = runner.run_comparison(modified, FakeAnswerGenerator, output_root=tmp_path / "empty-source",
        model_config={"provider": "fake"}, methods=("longmemory_v1",))
    encoder = FakeEncoder()
    _, report = retrieval.run_retrieval(folder / "report.json", modified, encoder, output_root=tmp_path / "out")
    assert report["status"] == "completed" and encoder.documents == []
    assert all(r["retrieved_count"] == 0 for r in report["questions"])
