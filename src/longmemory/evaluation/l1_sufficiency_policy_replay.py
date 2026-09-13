"""离线回放 L1 充分性判断的策略影响；不调用模型或访问个人数据库。"""

import argparse
from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from longmemory.evaluation.runner import provenance


ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = "l1-sufficiency-policy-replay-v1"
SUPPORTED_SOURCE_PROTOCOLS = {
    "l1-evidence-sufficiency-evaluation-v2",
    "l1-evidence-sufficiency-rescore-v1",
}


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 6)


def _validate_ids(values, available: set[str], *, code: str) -> tuple[str, ...]:
    if (not isinstance(values, list)
            or not all(isinstance(value, str) and value in available for value in values)
            or len(values) != len(set(values))):
        raise ValueError(code)
    return tuple(values)


def _summarize(rows: list[dict]) -> dict:
    completed = [row for row in rows if row["status"] == "completed"]
    totals = Counter()
    for row in completed:
        for key in (
            "original_candidate_count", "kept_candidate_count",
            "original_context_characters", "kept_context_characters",
            "true_positive_ids", "false_positive_ids", "missed_support_ids",
        ):
            value = row[key]
            totals[key] += len(value) if isinstance(value, list) else value
    answerable = [row for row in completed if row["expected_answerable"]]
    unsupported = [row for row in completed if not row["expected_answerable"]]
    predicted_positive = totals["true_positive_ids"] + totals["false_positive_ids"]
    expected_positive = totals["true_positive_ids"] + totals["missed_support_ids"]
    removed_candidates = totals["original_candidate_count"] - totals["kept_candidate_count"]
    removed_characters = totals["original_context_characters"] - totals["kept_context_characters"]
    return {
        "total_cases": len(rows),
        "completed_cases": len(completed),
        "failed_cases": len(rows) - len(completed),
        "answerable_cases": len(answerable),
        "unsupported_cases": len(unsupported),
        "exact_support_set_cases": sum(row["exact_support_set"] for row in completed),
        "answerability_correct_cases": sum(row["answerability_correct"] for row in completed),
        "false_block_cases": sum(row["false_block"] for row in completed),
        "unsupported_pass_cases": sum(row["unsupported_pass"] for row in completed),
        "incomplete_allow_cases": sum(row["incomplete_allow"] for row in completed),
        "overinclusive_allow_cases": sum(row["overinclusive_allow"] for row in completed),
        "original_unsupported_injection_cases": sum(
            not row["expected_answerable"] and row["original_candidate_count"] > 0
            for row in completed
        ),
        "gated_unsupported_injection_cases": sum(
            not row["expected_answerable"] and row["kept_candidate_count"] > 0
            for row in completed
        ),
        "original_candidate_count": totals["original_candidate_count"],
        "kept_candidate_count": totals["kept_candidate_count"],
        "removed_candidate_count": removed_candidates,
        "candidate_reduction_rate": _safe_ratio(
            removed_candidates, totals["original_candidate_count"],
        ),
        "original_context_characters": totals["original_context_characters"],
        "kept_context_characters": totals["kept_context_characters"],
        "context_character_reduction_rate": _safe_ratio(
            removed_characters, totals["original_context_characters"],
        ),
        "candidate_precision": _safe_ratio(
            totals["true_positive_ids"], predicted_positive,
        ),
        "candidate_recall": _safe_ratio(
            totals["true_positive_ids"], expected_positive,
        ),
    }


def replay_l1_sufficiency_policy(source_path: Path, *, output_root: Path,
                                 run_id: str | None = None):
    """将已保存的支持集合解释为假设门控；原报告与真实策略均不改变。"""

    raw = source_path.read_bytes()
    source = json.loads(raw)
    manifest = source.get("manifest")
    source_rows = source.get("rows")
    if (not isinstance(manifest, dict)
            or manifest.get("protocol") not in SUPPORTED_SOURCE_PROTOCOLS
            or source.get("status") != "completed"
            or not isinstance(source_rows, list)
            or not source_rows or len(source_rows) > 2000):
        raise ValueError("l1_sufficiency_policy_replay_source_invalid")

    rows = []
    seen = set()
    for source_row in source_rows:
        case_id = source_row.get("case_id")
        category = source_row.get("category")
        status = source_row.get("status")
        if (not isinstance(case_id, str) or not case_id.strip() or case_id in seen
                or not isinstance(category, str) or not category.strip()
                or status not in {"completed", "failed"}):
            raise ValueError("l1_sufficiency_policy_replay_row_invalid")
        seen.add(case_id)
        if status == "failed":
            rows.append({
                "case_id": case_id, "category": category, "status": "failed",
                "error_code": "source_case_failed",
            })
            continue

        candidates = source_row.get("candidates")
        if (not isinstance(candidates, list)
                or any(not isinstance(item, dict)
                       or set(item) != {"id", "content"}
                       or not isinstance(item["id"], str) or not item["id"].strip()
                       or not isinstance(item["content"], str) or not item["content"].strip()
                       for item in candidates)):
            raise ValueError("l1_sufficiency_policy_replay_candidates_invalid")
        candidate_ids = [item["id"] for item in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("l1_sufficiency_policy_replay_candidates_invalid")
        available = set(candidate_ids)
        expected = _validate_ids(
            source_row.get("expected_supported_ids"), available,
            code="l1_sufficiency_policy_replay_expected_invalid",
        )
        predicted = _validate_ids(
            source_row.get("predicted_supported_ids"), available,
            code="l1_sufficiency_policy_replay_predicted_invalid",
        )
        expected_set, predicted_set = set(expected), set(predicted)
        true_positive = sorted(expected_set & predicted_set)
        false_positive = sorted(predicted_set - expected_set)
        missed = sorted(expected_set - predicted_set)
        kept = [item for item in candidates if item["id"] in predicted_set]
        expected_answerable, predicted_answerable = bool(expected), bool(predicted)
        rows.append({
            "case_id": case_id,
            "category": category,
            "status": "completed",
            "expected_answerable": expected_answerable,
            "predicted_answerable": predicted_answerable,
            "answerability_correct": expected_answerable == predicted_answerable,
            "exact_support_set": expected_set == predicted_set,
            "false_block": expected_answerable and not predicted_answerable,
            "unsupported_pass": not expected_answerable and predicted_answerable,
            "incomplete_allow": expected_answerable and predicted_answerable and bool(missed),
            "overinclusive_allow": predicted_answerable and bool(false_positive),
            "original_candidate_count": len(candidates),
            "kept_candidate_count": len(kept),
            "original_context_characters": sum(len(item["content"]) for item in candidates),
            "kept_context_characters": sum(len(item["content"]) for item in kept),
            "true_positive_ids": true_positive,
            "false_positive_ids": false_positive,
            "missed_support_ids": missed,
        })

    summary = _summarize(rows)
    categories = []
    for category in sorted({row["category"] for row in rows}):
        category_rows = [row for row in rows if row["category"] == category]
        categories.append({"category": category, **_summarize(category_rows)})
    report = {
        "manifest": {
            "protocol": PROTOCOL,
            "created_at": datetime.now(UTC).isoformat(),
            "code": provenance(),
            "source_report_sha256": hashlib.sha256(raw).hexdigest(),
            "source_protocol": manifest["protocol"],
            "source_dataset_id": (
                manifest.get("target_dataset_id") or manifest.get("dataset_id")
            ),
            "source_dataset_sha256": (
                manifest.get("target_dataset_sha256") or manifest.get("dataset_sha256")
            ),
            "model": manifest.get("model"),
            "request_limit": 0,
            "retry_limit": 0,
            "policy": "keep_only_predicted_supported_l1_v1",
            "limitations": [
                "synthetic_candidate_replay_not_end_to_end_answer_quality",
                "predicted_nonempty_is_only_an_answerability_proxy",
                "development_set_used_during_annotation_correction",
                "no_personal_database_access",
                "no_model_requests",
                "no_daily_behavior_change",
            ],
        },
        "status": "completed" if summary["failed_cases"] == 0 else "completed_with_errors",
        "summary": summary,
        "categories": categories,
        "rows": rows,
    }
    if run_id is None:
        run_id = "l1-sufficiency-policy-replay-" + uuid4().hex
    if (not isinstance(run_id, str)
            or not run_id.startswith("l1-sufficiency-policy-replay-")
            or len(run_id) != len("l1-sufficiency-policy-replay-") + 32
            or any(character not in "0123456789abcdef" for character in run_id[-32:])):
        raise ValueError("l1_sufficiency_policy_replay_run_id_invalid")
    directory = output_root.resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return directory, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="离线回放 L1 充分性门控影响；不调用模型或访问个人库",
    )
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument(
        "--output-root", type=Path, default=ROOT / "experiments/runs",
    )
    args = parser.parse_args(argv)
    try:
        directory, report = replay_l1_sufficiency_policy(
            args.source_report, output_root=args.output_root,
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        print("离线策略回放失败：来源报告不完整或协议不匹配；没有调用模型。")
        return 2
    summary = report["summary"]
    print(f"报告：{directory / 'report.json'}")
    print(
        f"完成 {summary['completed_cases']}/{summary['total_cases']}；"
        f"误拦截 {summary['false_block_cases']}；"
        f"无证据误放行 {summary['unsupported_pass_cases']}；"
        f"候选减少 {summary['removed_candidate_count']}/"
        f"{summary['original_candidate_count']}。"
    )
    print("这是合成候选上的策略代理，不是端到端回答质量，也没有改变日常召回。")
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
