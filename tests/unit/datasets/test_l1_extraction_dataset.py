import json
from pathlib import Path

import pytest

from longmemory.evaluation.l1_extraction import load_l1_extraction_dataset


ROOT = Path(__file__).parents[3]
DATASET = ROOT / "datasets/synthetic/l1_extraction_v2.json"


def test_l1_extraction_dataset_has_frozen_dev_and_holdout_contract():
    dataset = load_l1_extraction_dataset(DATASET)

    dev = [case for case in dataset.cases if case["split"] == "dev"]
    holdout = [case for case in dataset.cases if case["split"] == "holdout"]

    assert dataset.dataset_id == "l1-extraction-v2"
    assert len(dataset.sha256) == 64
    assert len(dev) == 16
    assert len(holdout) == 8
    assert {case["expected_operation"] for case in dev} == {"ADD", "NOOP"}
    assert {case["expected_operation"] for case in holdout} == {"ADD", "NOOP"}
    assert {case["category"] for case in dev} >= {
        "identity", "multi_fact", "negation", "uncertainty",
        "provenance_guard", "instruction_guard", "mixed_statement_question",
    }


def test_l1_extraction_dataset_rejects_tampered_contract(tmp_path):
    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    payload["cases"][0]["unexpected"] = True
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="l1_extraction_dataset_invalid"):
        load_l1_extraction_dataset(changed)
