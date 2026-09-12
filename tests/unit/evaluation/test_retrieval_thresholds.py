import json

import pytest

from longmemory.evaluation.comparison.dataset import load_dataset
from longmemory.evaluation.comparison import retrieval_thresholds as replay
from longmemory.evaluation.comparison.runner import DEFAULT_DATASET


def frozen_report(dataset):
    question = next(item for item in dataset.questions if item.split == "dev" and not item.abstain)
    unknown = next(item for item in dataset.questions if item.split == "dev" and item.abstain)
    source = question.evidence_sets[0][0]
    rows = []
    for current, score in ((question, 0.7), (unknown, 0.3)):
        rows.append({
            "method": "synthetic_method",
            "strategy": "dense_cosine",
            "question_id": current.id,
            "status": "completed",
            "scores": [score],
            "support": {"retrieved": [{
                "item_id": "memory-1", "content": "仅用于合成测试", "source_event_ids": [source],
            }]},
        })
    return {
        "status": "completed",
        "manifest": {"protocol": "frozen-l1-retrieval-ablation-v1",
                     "source_manifest": {"dataset": {"sha256": dataset.sha256}}},
        "questions": rows,
    }


def test_replays_saved_scores_without_encoder(tmp_path):
    dataset = load_dataset(DEFAULT_DATASET)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(frozen_report(dataset), ensure_ascii=False), encoding="utf-8")

    rows = replay.replay_thresholds(path, dataset, (0.2, 0.5))

    assert rows[0]["evidence_complete"] == 1
    assert rows[0]["unknown_empty_retrieval"] == 0
    assert rows[1]["evidence_complete"] == 1
    assert rows[1]["unknown_empty_retrieval"] == 1
    assert rows[1]["mean_retrieved_count"] == 0.5


def test_rejects_mismatched_or_malformed_frozen_report(tmp_path):
    dataset = load_dataset(DEFAULT_DATASET)
    report = frozen_report(dataset)
    report["manifest"]["source_manifest"]["dataset"]["sha256"] = "wrong"
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError):
        replay.replay_thresholds(path, dataset, (0.5,))

    report = frozen_report(dataset)
    report["questions"][0]["scores"] = []
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError):
        replay.replay_thresholds(path, dataset, (0.5,))
