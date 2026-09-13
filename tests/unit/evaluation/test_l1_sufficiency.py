"""L1 证据充分性冻结协议只使用合成数据和本地替身。"""

import json

import pytest

from longmemory.core.memory.retrieval.sufficiency import (
    EvidenceSufficiencyDecision, EvidenceSufficiencyReview,
)
from longmemory.evaluation.l1_sufficiency import (
    DEFAULT_DATASET, load_l1_sufficiency_dataset, run_l1_sufficiency,
)
from longmemory.evaluation.l1_sufficiency_rescore import rescore_l1_sufficiency


class LabelGate:
    version = "synthetic-label-gate-v1"

    def __init__(self, expected_by_query):
        self.expected_by_query = expected_by_query
        self.calls = 0

    def review(self, value):
        self.calls += 1
        expected = set(self.expected_by_query[value.query])
        return EvidenceSufficiencyReview(tuple(
            EvidenceSufficiencyDecision(
                item.item_id, item.item_id in expected,
                "direct_support" if item.item_id in expected else "missing_attribute",
            ) for item in value.candidates
        ), self.version)


def test_frozen_dataset_and_label_gate_complete_dev_without_personal_database(tmp_path):
    dataset = load_l1_sufficiency_dataset(DEFAULT_DATASET)
    dev = [case for case in dataset.cases if case["split"] == "dev"]
    holdout = [case for case in dataset.cases if case["split"] == "holdout"]
    assert len(dev) == 16 and len(holdout) == 8
    gate = LabelGate({case["query"]: case["expected_supported_ids"] for case in dev})

    directory, report = run_l1_sufficiency(
        dataset, gate, output_root=tmp_path, model_config={"provider": "synthetic"},
    )

    assert report["status"] == "completed"
    assert report["summary"]["all_cases_exact"] == 16
    assert gate.calls == 15  # 空候选是确定性完成，不浪费模型请求。
    assert report["manifest"]["split"] == "dev"
    assert report["manifest"]["request_limit"] == 15
    assert (directory / "report.json").exists()


def test_holdout_requires_explicit_unlock():
    dataset = load_l1_sufficiency_dataset(DEFAULT_DATASET)
    with pytest.raises(ValueError, match="split_locked"):
        run_l1_sufficiency(dataset, LabelGate({}), split="holdout")


def test_loader_rejects_candidate_or_expected_id_drift(tmp_path):
    data = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    data["cases"][0]["expected_supported_ids"] = ["missing-candidate"]
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="dataset_invalid"):
        load_l1_sufficiency_dataset(changed)


def test_v1_open_world_label_can_be_rescored_without_model_calls(tmp_path):
    v1 = load_l1_sufficiency_dataset(
        DEFAULT_DATASET.with_name("l1_evidence_sufficiency_v1.json")
    )
    expected = {
        case["query"]: (
            [] if case["id"] == "dev-roommate-pet" else case["expected_supported_ids"]
        ) for case in v1.cases if case["split"] == "dev"
    }
    _directory, original = run_l1_sufficiency(v1, LabelGate(expected))
    assert original["summary"]["all_cases_exact"] == 15
    original["manifest"]["protocol"] = "l1-evidence-sufficiency-evaluation-v1"
    source = tmp_path / "source.json"
    source.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

    directory, rescored = rescore_l1_sufficiency(
        source, load_l1_sufficiency_dataset(DEFAULT_DATASET), output_root=tmp_path,
    )

    assert rescored["summary"]["all_cases_exact"] == 16
    assert rescored["summary"]["request_attempts"] == 0
    assert rescored["manifest"]["source_report_sha256"]
    assert (directory / "report.json").exists()
