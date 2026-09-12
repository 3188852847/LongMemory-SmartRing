from pathlib import Path

from longmemory.core.memory.retrieval.sufficiency import (
    EvidenceSufficiencyDecision,
    EvidenceSufficiencyError,
    EvidenceSufficiencyReview,
)
from longmemory.evaluation.l2_retrieval import (
    load_l2_corpus,
    load_l2_relevance_annotations,
)
from longmemory.evaluation.l2_sufficiency import run_l2_sufficiency


ROOT = Path(__file__).parents[3]


def _inputs():
    corpus = load_l2_corpus(ROOT / "datasets/synthetic/l2_retrieval_v2.json")
    annotations = load_l2_relevance_annotations(
        ROOT / "datasets/synthetic/l2_retrieval_v2_relevance_v1.json", corpus,
    )
    return corpus, annotations


class LabelGate:
    version = "synthetic-label-gate"

    def __init__(self, expected_by_query):
        self.expected_by_query = expected_by_query
        self.calls = 0

    def review(self, value):
        self.calls += 1
        expected = set(self.expected_by_query[value.query])
        return EvidenceSufficiencyReview(tuple(
            EvidenceSufficiencyDecision(
                item.item_id, item.item_id in expected,
                "direct_support" if item.item_id in expected else "topic_only",
            ) for item in value.candidates
        ), self.version)


def test_gate_evaluation_keeps_fixed_denominators_and_scores_support(tmp_path):
    corpus, annotations = _inputs()
    expected = {case["query"]: case["expected_ids"]
                for case in corpus.cases if case["split"] == "dev"}
    gate = LabelGate(expected)

    directory, report = run_l2_sufficiency(
        corpus, annotations, gate, output_root=tmp_path,
        model_config={"provider": "synthetic"},
    )

    assert report["status"] == "completed"
    assert report["summary"]["total"] == 24
    assert report["summary"]["answerable_exact_support"] == 15
    assert report["summary"]["unsupported_correct_rejection"] == 9
    assert report["summary"]["request_attempts"] == gate.calls == 24
    assert (directory / "manifest.json").is_file()
    assert (directory / "report.json").is_file()


def test_gate_failure_is_recorded_once_without_removing_case_from_denominator():
    corpus, annotations = _inputs()

    class FailingGate:
        version = "synthetic-failing-gate"

        def __init__(self):
            self.calls = 0

        def review(self, _value):
            self.calls += 1
            raise EvidenceSufficiencyError("synthetic_failure")

    gate = FailingGate()
    _directory, report = run_l2_sufficiency(corpus, annotations, gate)

    assert report["status"] == "completed_with_errors"
    assert report["summary"]["total"] == 24
    assert report["summary"]["completed"] == 0
    assert report["summary"]["failed"] == 24
    assert report["summary"]["request_attempts"] == gate.calls == 24
