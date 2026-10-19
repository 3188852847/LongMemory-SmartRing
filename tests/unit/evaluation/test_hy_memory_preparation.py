from pathlib import Path

import pytest

from longmemory.evaluation.comparison.dataset import load_dataset
from longmemory.evaluation.comparison.hy_memory_preparation import (
    changed_files, history_payload, prepare_development,
)


ROOT = Path(__file__).resolve().parents[3]
DEV = ROOT / "datasets/synthetic/hy_memory_dev_v1.json"


def test_preparation_uses_common_dataset_without_model():
    report = prepare_development(DEV)
    assert report["history_count"] == 12
    assert len(report["question_ids"]) == 10
    assert report["sdk_run"] is report["answer_run"] is False
    payload = history_payload(load_dataset(DEV))
    assert all(set(row) == {"event_id", "role", "content", "occurred_at", "session_id"} for row in payload)
    assert len({row["session_id"] for row in payload}) == 3


def test_nondev_data_refused_without_reading_repository_holdout(tmp_path):
    # 保留集不参与适配调试；用开发集副本测试门禁即可。
    import json
    data = json.loads(DEV.read_text(encoding="utf-8"))
    data["questions"][0]["split"] = "holdout"
    path = tmp_path / "synthetic-holdout-gate.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="开发集"):
        prepare_development(path)


def test_changed_history_or_cache_not_automatically_telemetry():
    result = changed_files({"history.db":"a", "cache.db":"a"}, {"history.db":"b", "cache.db":"b"})
    assert result["semantic_state_unchanged"] is None
    assert result["classification"] == "requires_store_level_review"
    assert changed_files({"vdb":"a"}, {"vdb":"a"})["byte_state_unchanged"]
