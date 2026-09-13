from pathlib import Path

import pytest

from longmemory.evaluation.semantic_relations import (
    evaluate_semantic_pairing,
    load_semantic_relation_dataset,
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
