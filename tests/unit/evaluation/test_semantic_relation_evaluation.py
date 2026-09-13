from pathlib import Path

import pytest

from longmemory.evaluation.semantic_relations import (
    evaluate_semantic_pairing,
    load_semantic_relation_dataset,
    run_semantic_relation_review,
)
from longmemory.core.memory.quality.semantic_relations import (
    SemanticRelation,
    SemanticRelationDecision,
    SemanticRelationError,
    SemanticRelationReview,
)


DATASET = Path(__file__).resolve().parents[3] / "datasets/synthetic/l1_semantic_relations_v1.json"


class FakeEncoder:
    identity = "fake-semantic-pairing"

    def encode_documents(self, texts):
        # 相邻的人工目标对共享一个轴，其他对保持正交。
        vectors = []
        for index, _text in enumerate(texts):
            pair_index = index // 2
            vector = [0.0] * 4
            vector[pair_index] = 1.0
            vectors.append(vector)
        return vectors

    def encode_query(self, text):
        raise AssertionError


def test_frozen_dataset_has_separate_dev_and_holdout_annotations():
    dataset = load_semantic_relation_dataset(DATASET)

    assert dataset.dataset_id == "l1-semantic-relations-v1"
    assert len(dataset.memories) == 16
    assert {row["split"] for row in dataset.annotations} == {"dev", "holdout"}


def test_pairing_reports_annotated_recall_without_calling_unlabeled_pairs_wrong():
    dataset = load_semantic_relation_dataset(DATASET)
    report = evaluate_semantic_pairing(
        dataset, encoder=FakeEncoder(), split="dev", maximum_candidates=6,
    )

    assert report["annotated_pair_count"] == 4
    assert report["annotated_pair_hits"] == 4
    assert report["annotated_pair_recall"] == 1.0
    assert report["unannotated_candidate_count"] == 2


def test_invalid_split_is_rejected():
    dataset = load_semantic_relation_dataset(DATASET)
    with pytest.raises(ValueError, match="semantic_relation_split_invalid"):
        evaluate_semantic_pairing(dataset, encoder=FakeEncoder(), split="all")


class FakeReviewer:
    version = "fake-relation-v1"

    def __init__(self, relations):
        self.relations = relations
        self.calls = 0

    def review(self, pairs):
        self.calls += 1
        return SemanticRelationReview(self.version, tuple(
            SemanticRelationDecision(
                pair.pair_id, SemanticRelation(self.relations[pair.pair_id]),
                {
                    "equivalent": "same_claim",
                    "possible_conflict": "different_value_same_attribute",
                    "possible_change": "explicit_change_over_time",
                    "compatible": "coexisting_claims",
                }[self.relations[pair.pair_id]],
                pair.left_content, pair.right_content,
            ) for pair in pairs
        ))


def expected_dev_relations(dataset):
    return {row["id"]: row["relation"] for row in dataset.annotations
            if row["split"] == "dev"}


def test_relation_review_reports_accuracy_confusion_and_high_risk_errors():
    dataset = load_semantic_relation_dataset(DATASET)
    relations = expected_dev_relations(dataset)
    relations["dev-compatible-drinks"] = "possible_conflict"
    reviewer = FakeReviewer(relations)

    _path, report = run_semantic_relation_review(dataset, reviewer)

    assert reviewer.calls == 1
    assert report["status"] == "completed"
    assert report["summary"]["exact"] == 3
    assert report["summary"]["compatible_false_alarm"] == 1
    assert report["summary"]["conflict_missed"] == 0
    assert report["summary"]["confusion"]["compatible"]["possible_conflict"] == 1


def test_holdout_requires_separate_unlock():
    dataset = load_semantic_relation_dataset(DATASET)
    reviewer = FakeReviewer(expected_dev_relations(dataset))
    with pytest.raises(ValueError, match="semantic_relation_split_locked"):
        run_semantic_relation_review(dataset, reviewer, split="holdout")
    assert reviewer.calls == 0


def test_relation_protocol_failure_is_recorded_without_retry(tmp_path):
    dataset = load_semantic_relation_dataset(DATASET)

    class Failing:
        version = "fake-failing"
        calls = 0
        def review(self, _pairs):
            self.calls += 1
            raise SemanticRelationError("semantic_relation_schema_invalid")

    reviewer = Failing()
    path, report = run_semantic_relation_review(
        dataset, reviewer, output_root=tmp_path,
    )

    assert reviewer.calls == 1
    assert report["status"] == "completed_with_errors"
    assert report["summary"]["completed"] == 0
    assert report["summary"]["error"] == "semantic_relation_schema_invalid"
    assert (path / "report.json").is_file()
