"""L1 充分性策略回放只消费冻结报告，不运行模型或个人库。"""

import json

import pytest

from longmemory.evaluation.l1_sufficiency_policy_replay import (
    replay_l1_sufficiency_policy,
)


def _source(tmp_path, rows, *, protocol="l1-evidence-sufficiency-rescore-v1"):
    path = tmp_path / "source.json"
    path.write_text(json.dumps({
        "manifest": {
            "protocol": protocol,
            "target_dataset_id": "synthetic-v2",
            "target_dataset_sha256": "a" * 64,
            "model": {"provider": "synthetic"},
        },
        "status": "completed",
        "rows": rows,
    }, ensure_ascii=False), encoding="utf-8")
    return path


def _row(case_id, candidates, expected, predicted, category="direct"):
    return {
        "case_id": case_id,
        "category": category,
        "status": "completed",
        "candidates": [
            {"id": item_id, "content": content}
            for item_id, content in candidates
        ],
        "expected_supported_ids": expected,
        "predicted_supported_ids": predicted,
    }


def test_replay_separates_false_block_unsupported_pass_and_context_reduction(tmp_path):
    source = _source(tmp_path, [
        _row("exact", [("a", "猫叫豆包"), ("x", "喜欢茶")], ["a"], ["a"]),
        _row("false-block", [("b", "周五汇报")], ["b"], []),
        _row("unsafe-pass", [("c", "猫叫豆包")], [], ["c"], "missing_attribute"),
        _row("partial", [("d", "住在合肥"), ("e", "周末回家")], ["d", "e"], ["d"]),
    ])

    directory, report = replay_l1_sufficiency_policy(
        source, output_root=tmp_path / "runs",
    )

    summary = report["summary"]
    assert report["status"] == "completed"
    assert summary["completed_cases"] == 4
    assert summary["false_block_cases"] == 1
    assert summary["unsupported_pass_cases"] == 1
    assert summary["incomplete_allow_cases"] == 1
    assert summary["overinclusive_allow_cases"] == 1
    assert summary["original_candidate_count"] == 6
    assert summary["kept_candidate_count"] == 3
    assert summary["candidate_precision"] == pytest.approx(2 / 3, abs=1e-6)
    assert summary["candidate_recall"] == 0.5
    assert report["manifest"]["request_limit"] == 0
    assert "no_personal_database_access" in report["manifest"]["limitations"]
    assert (directory / "report.json").exists()


def test_replay_keeps_failed_source_rows_in_fixed_denominator(tmp_path):
    source = _source(tmp_path, [{
        "case_id": "failed", "category": "direct",
        "status": "failed", "error": "source_failed",
    }])

    _directory, report = replay_l1_sufficiency_policy(
        source, output_root=tmp_path / "runs",
    )

    assert report["status"] == "completed_with_errors"
    assert report["summary"]["total_cases"] == 1
    assert report["summary"]["failed_cases"] == 1


@pytest.mark.parametrize("change", ("protocol", "unknown_prediction", "duplicate_case"))
def test_replay_rejects_incompatible_or_drifting_source(tmp_path, change):
    rows = [_row("one", [("a", "猫叫豆包")], ["a"], ["a"])]
    protocol = "unknown-v1" if change == "protocol" else "l1-evidence-sufficiency-rescore-v1"
    if change == "unknown_prediction":
        rows[0]["predicted_supported_ids"] = ["missing"]
    if change == "duplicate_case":
        rows.append(dict(rows[0]))
    source = _source(tmp_path, rows, protocol=protocol)

    with pytest.raises(ValueError, match="replay_"):
        replay_l1_sufficiency_policy(source, output_root=tmp_path / "runs")
