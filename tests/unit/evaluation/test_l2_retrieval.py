import json
from pathlib import Path

from longmemory.evaluation.l2_retrieval import (
    evaluate_l2_retrieval,
    load_l2_corpus,
    load_l2_relevance_annotations,
)


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


def test_v2_dataset_keeps_dev_and_holdout_separate_and_excludes_expired_scenes():
    corpus = load_l2_corpus(ROOT / "datasets/synthetic/l2_retrieval_v2.json")

    assert corpus.available_splits == ("dev", "holdout")
    dev = evaluate_l2_retrieval(corpus, split="dev")
    holdout_cases = [case for case in corpus.cases if case["split"] == "holdout"]

    assert dev["split"] == "dev"
    assert dev["eligible_scenarios"] == 11
    assert dev["excluded_scenarios"] == 2
    assert dev["summary"]["l2_keyword_v1"]["answerable"] == 15
    assert dev["summary"]["l2_keyword_v1"]["unanswerable"] == 9
    assert len(dev["results"]["l2_keyword_v1"]) == 24
    assert sum(bool(case["expected_ids"]) for case in holdout_cases) == 9
    assert sum(not case["expected_ids"] for case in holdout_cases) == 5
    assert len(holdout_cases) == 14


def test_multi_scene_case_reports_full_evidence_coverage():
    corpus = load_l2_corpus(ROOT / "datasets/synthetic/l2_retrieval_v2.json")
    report = evaluate_l2_retrieval(corpus, split="dev", limit=1)
    row = next(
        item for item in report["results"]["l2_keyword_v1"]
        if item["case_id"] == "dev-multi-week-plan"
    )

    assert row["hit_at_k"] is True
    assert row["evidence_recall_at_k"] == 0.5
    assert row["full_coverage_at_k"] is False


def test_unknown_or_missing_split_is_rejected():
    corpus = load_l2_corpus(ROOT / "datasets/synthetic/l2_retrieval_v2.json")

    try:
        evaluate_l2_retrieval(corpus, split="legacy")
    except ValueError as error:
        assert str(error) == "l2_retrieval_split_invalid"
    else:
        raise AssertionError("unknown split accepted")


def test_relevance_annotations_separate_topic_from_answer_support():
    corpus = load_l2_corpus(ROOT / "datasets/synthetic/l2_retrieval_v2.json")
    annotations = load_l2_relevance_annotations(
        ROOT / "datasets/synthetic/l2_retrieval_v2_relevance_v1.json", corpus,
    )
    report = evaluate_l2_retrieval(
        corpus, split="dev", relevance_annotations=annotations,
    )
    row = next(
        item for item in report["results"]["l2_keyword_v1"]
        if item["case_id"] == "dev-unknown-cat-color"
    )

    assert row["expected_ids"] == []
    assert row["eligible_topical_ids"] == ["cat"]
    assert row["topical_hit_at_k"] is True
    assert row["correct_abstention"] is False
    assert report["relevance_annotation_id"] == "l2-retrieval-v2-relevance-v1"


def test_relevance_annotations_are_bound_to_exact_dataset_hash(tmp_path):
    corpus = load_l2_corpus(ROOT / "datasets/synthetic/l2_retrieval_v2.json")
    source = ROOT / "datasets/synthetic/l2_retrieval_v2_relevance_v1.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["dataset_sha256"] = "0" * 64
    path = tmp_path / "mismatched.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        load_l2_relevance_annotations(path, corpus)
    except ValueError as error:
        assert str(error) == "l2_relevance_annotations_invalid"
    else:
        raise AssertionError("mismatched relevance annotations accepted")
