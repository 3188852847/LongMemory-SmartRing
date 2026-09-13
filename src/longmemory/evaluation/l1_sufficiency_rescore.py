"""用修订后的冻结标注重评分既有 L1 充分性输出，不再次调用模型。"""

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from longmemory.evaluation.l1_sufficiency import (
    DEFAULT_DATASET, L1SufficiencyDataset, load_l1_sufficiency_dataset,
)
from longmemory.evaluation.runner import provenance


ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = "l1-evidence-sufficiency-rescore-v1"


def rescore_l1_sufficiency(source_path: Path, dataset: L1SufficiencyDataset,
                           *, output_root: Path):
    raw = source_path.read_bytes()
    source = json.loads(raw)
    cases = [case for case in dataset.cases if case["split"] == "dev"]
    if (source.get("manifest", {}).get("protocol") != "l1-evidence-sufficiency-evaluation-v1"
            or source.get("manifest", {}).get("question_order") != [case["id"] for case in cases]
            or len(source.get("rows", ())) != len(cases)):
        raise ValueError("l1_sufficiency_rescore_source_invalid")
    rows = []
    for old, case in zip(source["rows"], cases, strict=True):
        if (old.get("case_id") != case["id"] or old.get("query") != case["query"]
                or old.get("candidates") != case["candidates"]):
            raise ValueError("l1_sufficiency_rescore_source_invalid")
        row = dict(old)
        row["category"] = case["category"]
        row["expected_supported_ids"] = case["expected_supported_ids"]
        if row.get("status") == "completed":
            actual = set(row.get("predicted_supported_ids", ()))
            expected = set(case["expected_supported_ids"])
            row["exact_supported_set"] = actual == expected
            row["false_positive_ids"] = sorted(actual - expected)
            row["missed_support_ids"] = sorted(expected - actual)
        rows.append(row)
    answerable = [row for row in rows if row["expected_supported_ids"]]
    unsupported = [row for row in rows if not row["expected_supported_ids"]]
    summary = {
        "total": len(rows),
        "completed": sum(row.get("status") == "completed" for row in rows),
        "failed": sum(row.get("status") == "failed" for row in rows),
        "request_attempts": 0,
        "answerable": len(answerable),
        "answerable_exact_support": sum(row.get("exact_supported_set") is True for row in answerable),
        "unsupported": len(unsupported),
        "unsupported_correct_rejection": sum(row.get("exact_supported_set") is True for row in unsupported),
        "all_cases_exact": sum(row.get("exact_supported_set") is True for row in rows),
        "false_positive_ids": sum(len(row.get("false_positive_ids", ())) for row in rows),
        "missed_support_ids": sum(len(row.get("missed_support_ids", ())) for row in rows),
    }
    manifest = {
        "protocol": PROTOCOL, "created_at": datetime.now(UTC).isoformat(),
        "code": provenance(), "source_report_sha256": hashlib.sha256(raw).hexdigest(),
        "source_dataset_sha256": source["manifest"].get("dataset_sha256"),
        "target_dataset_id": dataset.dataset_id, "target_dataset_sha256": dataset.sha256,
        "model": source["manifest"].get("model"), "request_limit": 0,
        "retry_limit": 0,
        "annotation_change": "dev-roommate-pet: owning a cat does not prove not owning a dog",
    }
    report = {"manifest": manifest, "rows": rows, "status": source.get("status"),
              "summary": summary}
    directory = output_root.resolve() / ("l1-sufficiency-rescore-" + uuid4().hex)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return directory, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="不调用模型，按 V2 标注重评分 L1 充分性报告")
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "experiments/runs")
    args = parser.parse_args(argv)
    try:
        directory, report = rescore_l1_sufficiency(
            args.source_report, load_l1_sufficiency_dataset(DEFAULT_DATASET),
            output_root=args.output_root,
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        print("来源报告或冻结标注不匹配；没有重评分，也没有调用模型。")
        return 2
    summary = report["summary"]
    print(f"报告：{directory / 'report.json'}")
    print(f"重评分 {summary['completed']}/{summary['total']}；精确支持集合 "
          f"{summary['all_cases_exact']}/{summary['total']}；模型请求 0。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
