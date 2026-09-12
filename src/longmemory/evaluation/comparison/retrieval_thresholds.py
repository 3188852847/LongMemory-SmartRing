"""用冻结检索报告中的既有分数回放余弦阈值，不重新编码或调用模型。"""

import argparse
import json
import math
from pathlib import Path

from longmemory.methods.contracts import MemorySupport, RetrievedTrace

from .dataset import load_dataset
from .retrieval import PROTOCOL_VERSION, retrieval_metrics
from .runner import DEFAULT_DATASET


def replay_thresholds(report_path: Path, dataset, thresholds: tuple[float, ...]):
    """返回各方法在不同阈值下的证据覆盖与空召回诊断。

    这里复用报告中已经冻结的候选顺序和余弦分数。未知题的空召回数量只用于
    观察检索行为，不能解释为最终回答已经正确拒答。
    """
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = report.get("manifest", {})
    if (report.get("status") != "completed"
            or manifest.get("protocol") != PROTOCOL_VERSION
            or manifest.get("source_manifest", {}).get("dataset", {}).get("sha256") != dataset.sha256):
        raise ValueError("需要同一合成数据集已完成的冻结检索报告。")
    if (not thresholds or any(type(value) not in (int, float)
                              or not math.isfinite(value) or not -1 <= value <= 1
                              for value in thresholds)):
        raise ValueError("余弦阈值必须是 -1 到 1 的有限数字。")

    questions = {question.id: question for question in dataset.questions}
    dense_rows = [row for row in report.get("questions", ())
                  if row.get("strategy") == "dense_cosine" and row.get("status") == "completed"]
    methods = tuple(dict.fromkeys(row.get("method") for row in dense_rows))
    if not methods:
        raise ValueError("报告中没有已完成的稠密检索结果。")

    results = []
    for threshold in thresholds:
        for method in methods:
            metrics = []
            for row in (item for item in dense_rows if item.get("method") == method):
                question = questions.get(row.get("question_id"))
                retrieved = row.get("support", {}).get("retrieved")
                scores = row.get("scores")
                if question is None or not isinstance(retrieved, list) or not isinstance(scores, list):
                    raise ValueError("冻结检索行缺少问题、条目或分数。")
                if len(retrieved) != len(scores):
                    raise ValueError("冻结条目与分数数量不一致。")
                kept = tuple(
                    RetrievedTrace(item["item_id"], item["content"],
                                   tuple(item["source_event_ids"]) if item.get("source_event_ids") is not None else None)
                    for item, score in zip(retrieved, scores)
                    if type(score) in (int, float) and math.isfinite(score) and score >= threshold
                )
                measured = retrieval_metrics(question, MemorySupport("threshold-replay", "", kept))
                metrics.append((question, measured))
            answerable = [measured for question, measured in metrics if not question.abstain]
            unknown = [measured for question, measured in metrics if question.abstain]
            results.append({
                "threshold": threshold,
                "method": method,
                "total": len(metrics),
                "answerable_total": len(answerable),
                "evidence_complete": sum(item["evidence_complete"] is True for item in answerable),
                "unknown_total": len(unknown),
                "unknown_empty_retrieval": sum(item["retrieved_count"] == 0 for item in unknown),
                "mean_retrieved_count": (
                    sum(item["retrieved_count"] for _, item in metrics) / len(metrics) if metrics else 0.0
                ),
            })
    return tuple(results)


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线回放冻结余弦分数的阈值，不重新编码或调用模型")
    parser.add_argument("--retrieval-report", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--threshold", type=float, action="append", required=True)
    args = parser.parse_args(argv)
    try:
        rows = replay_thresholds(args.retrieval_report, load_dataset(args.dataset), tuple(args.threshold))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        print("阈值回放失败：请核对冻结报告、数据集与已保存分数。未重新编码或调用模型。")
        return 2
    print(json.dumps({"results": rows, "limitations": [
        "unknown_empty_retrieval_is_not_answer_abstention_quality",
        "saved_candidates_below_original_top_k_are_unavailable",
        "synthetic_dev_set_not_a_production_threshold",
    ]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
