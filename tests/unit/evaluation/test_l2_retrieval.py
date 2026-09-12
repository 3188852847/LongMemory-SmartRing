import json
from pathlib import Path

from longmemory.evaluation.l2_retrieval import evaluate_l2_retrieval, load_l2_corpus


ROOT = Path(__file__).parents[3]


def test_frozen_l2_dataset_has_answerable_and_abstention_cases():
    corpus = load_l2_corpus(ROOT / "datasets/synthetic/l2_retrieval_v1.json")
    report = evaluate_l2_retrieval(corpus)

    summary = report["summary"]["l2_keyword_v1"]
    assert summary["answerable"] == 9
    assert summary["unanswerable"] == 4
    assert 0 <= summary["hit_at_k"] < 9
    assert 0 <= summary["correct_abstention"] <= 4
    assert len(report["dataset_sha256"]) == 64


def test_invalid_dataset_is_rejected(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"schema_version": 1, "dataset_id": "wrong"}), encoding="utf-8")

    try:
        load_l2_corpus(path)
    except ValueError as error:
        assert str(error) == "l2_retrieval_dataset_invalid"
    else:
        raise AssertionError("invalid dataset accepted")


def test_optional_dense_strategy_uses_same_cases_and_exposes_abstention_risk():
    class FakeEncoder:
        identity = "fake-l2-encoder"

        def encode_documents(self, texts):
            return [[1.0, index + 1.0] for index, _ in enumerate(texts)]

        def encode_query(self, _text):
            return [1.0, 1.0]

    corpus = load_l2_corpus(ROOT / "datasets/synthetic/l2_retrieval_v1.json")
    report = evaluate_l2_retrieval(corpus, encoder=FakeEncoder())

    assert set(report["summary"]) == {"l2_keyword_v1", "l2_dense_cosine"}
    # 无阈值稠密 top-k 必然返回候选；测试把这个风险固定下来，不能冒充拒答。
    assert report["summary"]["l2_dense_cosine"]["correct_abstention"] == 0
