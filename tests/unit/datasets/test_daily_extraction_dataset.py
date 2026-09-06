"""固定开发集只包含合成内容，并遵守日常提取契约。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_daily_extraction_dataset_shape_and_unique_cases():
    data = json.loads((ROOT / "datasets/synthetic/daily_extraction_v1.json").read_text(encoding="utf-8"))
    assert data["version"] == "daily-extraction-v1"
    assert "真实个人" in data["source"]
    ids = set()
    categories = set()
    for case in data["cases"]:
        assert set(case) == {"id", "category", "role", "input", "expected_operation", "expected_facts"}
        assert case["id"] not in ids and case["input"].strip()
        assert case["role"] in {"user", "assistant"}
        assert case["expected_operation"] in {"ADD", "NOOP"}
        assert bool(case["expected_facts"]) == (case["expected_operation"] == "ADD")
        assert all(isinstance(fact, str) and fact.strip() for fact in case["expected_facts"])
        ids.add(case["id"])
        categories.add(case["category"])
    assert {"identity", "preference", "habit", "plan", "should_not_remember",
            "provenance_guard", "instruction_guard"} <= categories
