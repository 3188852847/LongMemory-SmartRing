"""离线复核附页：保存判断，不覆盖原报告，也不重新调用回答模型。"""

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

RUBRIC = "target-fact-adequacy-v1"


def load_report(path):
    raw = path.read_bytes()
    report = json.loads(raw)
    rows = report["questions"]
    keys = [(row["method"], row["question_id"]) for row in rows]
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("原报告题目为空或存在重复方法/题目。")
    return report, hashlib.sha256(raw).hexdigest()


def prepare(report_path, *, reviewer, reviewer_kind):
    """只建待复核清单；自动初筛不预填为复核通过，避免锚定偏差。"""
    if not reviewer.strip() or reviewer_kind not in {"human", "assistant"}:
        raise ValueError("必须明确复核者及其类型。")
    report, digest = load_report(report_path)
    return {
        "schema_version": 1, "rubric": RUBRIC,
        "report_sha256": digest,
        "reviewer": reviewer, "reviewer_kind": reviewer_kind,
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "所问事实的正确性、信息不足时不编造；不评总体人格或性能。",
        "items": [{"method": row["method"], "question_id": row["question_id"],
                   "verdict": "pending", "rationale": ""} for row in report["questions"]],
    }


def summarize_review(report_path, review):
    """复核必须逐题完整对应原报告，未评题不得从分母消失。

    哈希只绑定报告字节版本，不证明复核者身份、判断正确性或独立盲评。
    评分本身仍需查看来源、实际注入和整段回答，不能只看预期关键词。
    """
    report, digest = load_report(report_path)
    if (review["schema_version"] != 1 or review["rubric"] != RUBRIC
            or review["report_sha256"] != digest):
        raise ValueError("复核版本或原报告哈希不匹配。")
    if review["reviewer_kind"] not in {"human", "assistant"} or not review["reviewer"].strip():
        raise ValueError("缺少有效复核者。")
    rows = {(row["method"], row["question_id"]): row for row in report["questions"]}
    seen, result = set(), {}
    for item in review["items"]:
        key = item["method"], item["question_id"]
        if key not in rows or key in seen:
            raise ValueError("复核包含重复或不属于本报告的题目。")
        seen.add(key)
        verdict = item["verdict"]
        if verdict not in {"pending", "pass", "fail", "unscorable"}:
            raise ValueError("未知复核结论。")
        if not isinstance(item["rationale"], str) or (verdict != "pending" and not item["rationale"].strip()):
            raise ValueError("已复核项必须解释判断依据。")
        row = rows[key]
        if verdict in {"pass", "fail"} and (
                row["status"] != "completed" or not row.get("answer", "").strip()
                or row.get("state_unchanged") is not True):
            raise ValueError("失败、无回答或冻结异常的题目只能待复核或标记不可评分。")
        counts = result.setdefault(key[0], {"total": 0, "pass": 0, "fail": 0,
                                            "pending": 0, "unscorable": 0})
        counts["total"] += 1
        counts[verdict] += 1
    if seen != set(rows):
        raise ValueError("复核遗漏题目；请用 pending 保留未评题。")
    return {"rubric": RUBRIC, "report_sha256": digest,
            "reviewer": review["reviewer"], "reviewer_kind": review["reviewer_kind"],
            "methods": result,
            "warning": "复核判断不是独立盲评或统计结论；原始词面初筛保持不变。"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线复核附页，不改报告、不调用模型")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("prepare")
    create.add_argument("--report", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--reviewer", required=True)
    create.add_argument("--reviewer-kind", choices=("human", "assistant"), required=True)
    check = sub.add_parser("summarize")
    check.add_argument("--report", type=Path, required=True)
    check.add_argument("--review", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            review = prepare(args.report, reviewer=args.reviewer, reviewer_kind=args.reviewer_kind)
            # 排他创建：包括输出误指向 report.json 时，也不能覆盖已有结果。
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(review, stream, ensure_ascii=False, indent=2)
            print(f"待复核附页：{args.output}")
        else:
            review = json.loads(args.review.read_text(encoding="utf-8"))
            print(json.dumps(summarize_review(args.report, review), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print("文件或复核格式无效；检查哈希、逐题清单及输出文件是否已存在。原报告未修改。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
