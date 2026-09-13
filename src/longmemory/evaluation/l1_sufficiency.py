"""冻结 L1 候选的证据充分性评估；不访问个人数据库。"""

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from longmemory.adapters.llm.evidence_sufficiency import (
    OpenAICompatibleEvidenceSufficiencyGate,
    SUFFICIENCY_GATE_PROMPT_SHA256,
)
from longmemory.core.memory.retrieval.sufficiency import (
    EvidenceCandidate, EvidenceSufficiencyError, EvidenceSufficiencyInput,
)
from longmemory.evaluation.runner import provenance
from longmemory.infrastructure.config.model_profiles import ModelProfileStore


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = ROOT / "datasets/synthetic/l1_evidence_sufficiency_v2.json"
PROTOCOL = "l1-evidence-sufficiency-evaluation-v2"


@dataclass(frozen=True, slots=True)
class L1SufficiencyDataset:
    dataset_id: str
    sha256: str
    cases: tuple[dict, ...]


def load_l1_sufficiency_dataset(path: Path) -> L1SufficiencyDataset:
    raw = path.read_bytes()
    data = json.loads(raw)
    if set(data) != {"schema_version", "dataset_id", "description", "cases"}:
        raise ValueError("l1_sufficiency_dataset_invalid")
    if data["schema_version"] != 1 or not isinstance(data["dataset_id"], str):
        raise ValueError("l1_sufficiency_dataset_invalid")
    case_ids = set()
    for case in data["cases"]:
        if set(case) != {"id", "split", "category", "query", "candidates", "expected_supported_ids"}:
            raise ValueError("l1_sufficiency_dataset_invalid")
        if (case["id"] in case_ids or case["split"] not in {"dev", "holdout"}
                or not all(isinstance(case[key], str) and case[key].strip()
                           for key in ("id", "category", "query"))):
            raise ValueError("l1_sufficiency_dataset_invalid")
        case_ids.add(case["id"])
        candidate_ids = []
        for candidate in case["candidates"]:
            if (set(candidate) != {"id", "content"}
                    or not all(isinstance(candidate[key], str) and candidate[key].strip()
                               for key in ("id", "content"))):
                raise ValueError("l1_sufficiency_dataset_invalid")
            candidate_ids.append(candidate["id"])
        expected = case["expected_supported_ids"]
        if (len(candidate_ids) != len(set(candidate_ids))
                or not isinstance(expected, list)
                or not all(isinstance(value, str) for value in expected)
                or len(expected) != len(set(expected))
                or not set(expected).issubset(candidate_ids)):
            raise ValueError("l1_sufficiency_dataset_invalid")
    if not case_ids:
        raise ValueError("l1_sufficiency_dataset_invalid")
    return L1SufficiencyDataset(
        data["dataset_id"], hashlib.sha256(raw).hexdigest(), tuple(data["cases"]),
    )


def _summary(rows: list[dict]) -> dict:
    completed = [row for row in rows if row["status"] == "completed"]
    answerable = [row for row in rows if row["expected_supported_ids"]]
    unsupported = [row for row in rows if not row["expected_supported_ids"]]
    return {
        "total": len(rows), "completed": len(completed),
        "failed": sum(row["status"] == "failed" for row in rows),
        "request_attempts": sum(bool(row.get("request_attempted")) for row in rows),
        "answerable": len(answerable),
        "answerable_exact_support": sum(row.get("exact_supported_set") is True for row in answerable),
        "unsupported": len(unsupported),
        "unsupported_correct_rejection": sum(row.get("exact_supported_set") is True for row in unsupported),
        "all_cases_exact": sum(row.get("exact_supported_set") is True for row in rows),
        "false_positive_ids": sum(len(row.get("false_positive_ids", ())) for row in rows),
        "missed_support_ids": sum(len(row.get("missed_support_ids", ())) for row in rows),
    }


def run_l1_sufficiency(dataset: L1SufficiencyDataset, gate, *, split="dev",
                       unlock_holdout=False, output_root: Path | None = None,
                       model_config: dict | None = None):
    if split not in {"dev", "holdout"} or (split == "holdout" and not unlock_holdout):
        raise ValueError("l1_sufficiency_split_locked")
    cases = [case for case in dataset.cases if case["split"] == split]
    rows = [{
        "case_id": case["id"], "category": case["category"], "query": case["query"],
        "candidates": case["candidates"],
        "expected_supported_ids": case["expected_supported_ids"],
        "status": "not_run", "error": None,
    } for case in cases]
    manifest = {
        "protocol": PROTOCOL, "started_at": datetime.now(UTC).isoformat(),
        "code": provenance(), "dataset_id": dataset.dataset_id,
        "dataset_sha256": dataset.sha256, "split": split,
        "question_order": [case["id"] for case in cases],
        "gate_version": gate.version, "gate_prompt_sha256": SUFFICIENCY_GATE_PROMPT_SHA256,
        "model": model_config, "request_limit": sum(bool(case["candidates"]) for case in cases),
        "retry_limit": 0,
        "limitations": ["synthetic_only", "no_personal_database_access", "no_daily_behavior_change"],
    }
    report = {"manifest": manifest, "rows": rows, "status": "running", "summary": _summary(rows)}
    run_dir = None
    if output_root is not None:
        run_dir = output_root.resolve() / ("l1-sufficiency-" + uuid4().hex)
        run_dir.mkdir(parents=True, exist_ok=False)

    def checkpoint():
        report["summary"] = _summary(rows)
        if run_dir is not None:
            (run_dir / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
            )

    checkpoint()
    for row in rows:
        values = tuple(EvidenceCandidate(item["id"], item["content"]) for item in row["candidates"])
        if not values:
            row.update(status="completed", request_attempted=False, duration_ms=0.0,
                       predicted_supported_ids=[], decisions=[], exact_supported_set=True,
                       false_positive_ids=[], missed_support_ids=[])
            checkpoint()
            continue
        started = perf_counter()
        row["request_attempted"] = True
        checkpoint()
        try:
            review = gate.review(EvidenceSufficiencyInput(row["query"], values))
            actual = set(review.supported_ids)
            expected = set(row["expected_supported_ids"])
            row.update(status="completed", decisions=[asdict(item) for item in review.decisions],
                       predicted_supported_ids=list(review.supported_ids),
                       exact_supported_set=actual == expected,
                       false_positive_ids=sorted(actual - expected),
                       missed_support_ids=sorted(expected - actual))
        except EvidenceSufficiencyError as error:
            code = str(error)
            row.update(status="failed", error=(code if code.startswith("evidence_sufficiency_") else "gate_failed"))
        finally:
            row["duration_ms"] = round((perf_counter() - started) * 1000, 3)
            checkpoint()
    report["status"] = "completed" if all(row["status"] == "completed" for row in rows) else "completed_with_errors"
    report["finished_at"] = datetime.now(UTC).isoformat()
    checkpoint()
    return run_dir, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="评估冻结 L1 候选是否足以回答问题")
    parser.add_argument("--model-profile", choices=("official", "campus"), required=True)
    parser.add_argument("--allow-model-requests", action="store_true")
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--unlock-holdout", action="store_true")
    parser.add_argument("--output-root", type=Path, default=ROOT / "experiments/runs")
    args = parser.parse_args(argv)
    if not args.allow_model_requests:
        print("未显式允许模型请求；未运行。")
        return 2
    try:
        dataset = load_l1_sufficiency_dataset(DEFAULT_DATASET)
        settings = ModelProfileStore(ROOT).settings(args.model_profile)
        gate = OpenAICompatibleEvidenceSufficiencyGate(settings)
        config = {"profile": args.model_profile, "provider": settings.provider,
                  "model": settings.model, "timeout_seconds": settings.timeout_seconds,
                  "endpoint_sha256": hashlib.sha256(settings.base_url.encode()).hexdigest()}
        request_limit = sum(bool(case["candidates"]) for case in dataset.cases if case["split"] == args.split)
        print(f"将在冻结 {args.split} 合成集最多发出 {request_limit} 次请求；不重试、不读个人库。")
        path, report = run_l1_sufficiency(
            dataset, gate, split=args.split, unlock_holdout=args.unlock_holdout,
            output_root=args.output_root, model_config=config,
        )
        summary = report["summary"]
        print(f"报告：{path / 'report.json'}")
        print(f"完成 {summary['completed']}/{summary['total']}；有答案精确通过 "
              f"{summary['answerable_exact_support']}/{summary['answerable']}；"
              f"证据不足正确拒绝 {summary['unsupported_correct_rejection']}/{summary['unsupported']}。")
        return 0 if report["status"] == "completed" else 1
    except (OSError, ValueError, KeyError, TypeError):
        print("数据、模型配置或输出路径校验失败；未输出密钥和数据正文。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
