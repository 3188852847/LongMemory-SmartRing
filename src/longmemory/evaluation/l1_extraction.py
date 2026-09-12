"""在冻结合成集上独立评估 L0→L1 候选提取，不打开记忆数据库。"""

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from longmemory.adapters.llm.candidate_extractor import (
    OpenAICompatibleCandidateProducer, PROMPT_SHA256, PROMPT_VERSION,
)
from longmemory.core.common.identifiers import MessageId
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.core.memory.extraction.candidates import (
    CandidateExtractionError, CandidateExtractionService, CandidateProducer,
    PREPROCESSOR_VERSION,
)
from longmemory.evaluation.runner import provenance
from longmemory.infrastructure.config.model_profiles import ModelProfileStore


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = ROOT / "datasets/synthetic/l1_extraction_v2.json"
PROTOCOL = "l1-extraction-evaluation-v1"


@dataclass(frozen=True, slots=True)
class L1ExtractionDataset:
    dataset_id: str
    cases: tuple[dict, ...]
    sha256: str


class _CountingProducer:
    """只统计真正越过领域短路门的模型请求，不读取或保存消息正文。"""

    def __init__(self, delegate: CandidateProducer):
        self._delegate = delegate
        self.calls = 0

    def propose(self, *, source_text: str) -> str:
        self.calls += 1
        return self._delegate.propose(source_text=source_text)


def load_l1_extraction_dataset(path: Path) -> L1ExtractionDataset:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    cases = payload.get("cases")
    if (payload.get("schema_version") != 1
            or payload.get("dataset_id") != "l1-extraction-v2"
            or not isinstance(cases, list) or not cases):
        raise ValueError("l1_extraction_dataset_invalid")
    ids = set()
    splits = set()
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {
            "id", "split", "category", "role", "input",
            "expected_operation", "expected_facts",
        }):
            raise ValueError("l1_extraction_dataset_invalid")
        if (not all(isinstance(case[key], str) and case[key].strip()
                    for key in ("id", "category", "input"))
                or case["id"] in ids or case["split"] not in {"dev", "holdout"}
                or case["role"] not in {"user", "assistant"}
                or case["expected_operation"] not in {"ADD", "NOOP"}
                or not isinstance(case["expected_facts"], list)
                or bool(case["expected_facts"]) != (case["expected_operation"] == "ADD")):
            raise ValueError("l1_extraction_dataset_invalid")
        for fact in case["expected_facts"]:
            if (not isinstance(fact, dict)
                    or set(fact) != {"required_terms", "forbidden_terms"}
                    or not isinstance(fact["required_terms"], list)
                    or not fact["required_terms"]
                    or not isinstance(fact["forbidden_terms"], list)
                    or not all(isinstance(term, str) and term.strip()
                               for term in fact["required_terms"] + fact["forbidden_terms"])):
                raise ValueError("l1_extraction_dataset_invalid")
        ids.add(case["id"])
        splits.add(case["split"])
    if splits != {"dev", "holdout"}:
        raise ValueError("l1_extraction_dataset_invalid")
    for split in splits:
        selected = [case for case in cases if case["split"] == split]
        if (not any(case["expected_operation"] == "ADD" for case in selected)
                or not any(case["expected_operation"] == "NOOP" for case in selected)):
            raise ValueError("l1_extraction_dataset_invalid")
    return L1ExtractionDataset(payload["dataset_id"], tuple(cases), sha256(raw).hexdigest())


def _fact_matches(content: str, expected: dict) -> bool:
    return (all(term in content for term in expected["required_terms"])
            and not any(term in content for term in expected["forbidden_terms"]))


def _has_exact_assignment(contents: tuple[str, ...], expected: list[dict]) -> bool:
    """小规模二分匹配，避免同一个候选同时冒充两条期望事实。"""

    if len(contents) != len(expected):
        return False
    options = [tuple(index for index, content in enumerate(contents)
                     if _fact_matches(content, fact)) for fact in expected]
    def assign(position: int, used: frozenset[int]) -> bool:
        if position == len(options):
            return True
        return any(index not in used and assign(position + 1, used | {index})
                   for index in options[position])
    return assign(0, frozenset())


def _summary(rows: list[dict]) -> dict:
    completed = [row for row in rows if row["status"] == "completed"]
    add_rows = [row for row in rows if row["expected_operation"] == "ADD"]
    noop_rows = [row for row in rows if row["expected_operation"] == "NOOP"]
    return {
        "total": len(rows), "completed": len(completed),
        "failed": sum(row["status"] == "failed" for row in rows),
        "request_attempts": sum(bool(row.get("request_attempted")) for row in rows),
        "operation_exact": sum(row.get("operation_exact") is True for row in rows),
        "fact_count_exact": sum(row.get("fact_count_exact") is True for row in rows),
        "fact_match_exact": sum(row.get("fact_match_exact") is True for row in rows),
        "add_cases": len(add_rows),
        "add_exact": sum(row.get("fact_match_exact") is True for row in add_rows),
        "noop_cases": len(noop_rows),
        "noop_exact": sum(row.get("operation_exact") is True for row in noop_rows),
    }


def run_l1_extraction(dataset: L1ExtractionDataset, producer: CandidateProducer,
                      *, split: str = "dev", output_root: Path | None = None,
                      model_config: dict | None = None) -> tuple[Path | None, dict]:
    if split not in {"dev", "holdout"}:
        raise ValueError("l1_extraction_split_invalid")
    cases = [case for case in dataset.cases if case["split"] == split]
    counting_producer = _CountingProducer(producer)
    service = CandidateExtractionService(counting_producer)
    manifest = {
        "protocol": PROTOCOL, "started_at": datetime.now(UTC).isoformat(),
        "code": provenance(), "dataset_id": dataset.dataset_id,
        "dataset_sha256": dataset.sha256, "split": split,
        "case_order": [case["id"] for case in cases],
        "extractor_version": PROMPT_VERSION, "prompt_sha256": PROMPT_SHA256,
        "preprocessor_version": PREPROCESSOR_VERSION,
        "model": model_config, "request_limit": len(cases), "retry_limit": 0,
        "limitations": ["synthetic_only", "term_constraint_semantic_proxy",
                        "no_personal_database_access", "no_memory_writes"],
    }
    rows = [{"case_id": case["id"], "category": case["category"],
             "role": case["role"], "input": case["input"],
             "expected_operation": case["expected_operation"],
             "expected_fact_count": len(case["expected_facts"]),
             "status": "not_run", "error": None} for case in cases]
    report = {"manifest": manifest, "rows": rows, "status": "running", "summary": _summary(rows)}
    run_dir = None
    if output_root is not None:
        run_dir = output_root.resolve() / ("l1-extraction-" + uuid4().hex)
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    def checkpoint():
        report["summary"] = _summary(rows)
        if run_dir is not None:
            temporary = run_dir / "report.json.tmp"
            temporary.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            temporary.replace(run_dir / "report.json")
    checkpoint()
    for case, row in zip(cases, rows, strict=True):
        message = ConversationMessage(
            MessageId("synthetic:" + case["id"]), MessageRole(case["role"]),
            case["input"], datetime(2026, 9, 13, tzinfo=UTC),
        )
        started = perf_counter()
        calls_before = counting_producer.calls
        try:
            proposal = service.extract(message)
            contents = tuple(candidate.content for candidate in proposal.candidates)
            operation_exact = proposal.operation == case["expected_operation"]
            count_exact = len(contents) == len(case["expected_facts"])
            fact_exact = operation_exact and _has_exact_assignment(contents, case["expected_facts"])
            row.update(status="completed", predicted_operation=proposal.operation,
                       predicted_facts=list(contents), operation_exact=operation_exact,
                       fact_count_exact=count_exact, fact_match_exact=fact_exact)
        except CandidateExtractionError:
            row.update(status="failed", error="candidate_extraction_failed")
        finally:
            row["request_attempted"] = counting_producer.calls > calls_before
            row["duration_ms"] = round((perf_counter() - started) * 1000, 3)
            checkpoint()
    report["status"] = "completed" if all(row["status"] == "completed" for row in rows) else "completed_with_errors"
    report["finished_at"] = datetime.now(UTC).isoformat()
    checkpoint()
    return run_dir, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="用真实模型评估冻结合成 L1 提取开发集")
    parser.add_argument("--model-profile", choices=("official", "campus"), required=True)
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--allow-model-requests", action="store_true")
    parser.add_argument("--allow-holdout", action="store_true")
    parser.add_argument("--output-root", type=Path, default=ROOT / "experiments/runs")
    args = parser.parse_args(argv)
    if not args.allow_model_requests or (args.split == "holdout" and not args.allow_holdout):
        print("未显式允许模型请求或冻结留出集；未运行。")
        return 2
    try:
        dataset = load_l1_extraction_dataset(DEFAULT_DATASET)
        settings = ModelProfileStore(ROOT).settings(args.model_profile)
        producer = OpenAICompatibleCandidateProducer(settings)
        config = {"profile": args.model_profile, "provider": settings.provider,
                  "model": settings.model, "timeout_seconds": settings.timeout_seconds,
                  "max_tokens": settings.max_tokens,
                  "endpoint_sha256": sha256(settings.base_url.encode()).hexdigest()}
        selected = sum(case["split"] == args.split for case in dataset.cases)
        print(f"将在合成 {args.split} 集上最多发出 {selected} 次提取请求；不重试、不读个人库。")
        path, report = run_l1_extraction(
            dataset, producer, split=args.split, output_root=args.output_root,
            model_config=config,
        )
        summary = report["summary"]
        print(f"报告：{path / 'report.json'}")
        print(f"完成 {summary['completed']}/{summary['total']}；操作正确 {summary['operation_exact']}/{summary['total']}；事实匹配 {summary['fact_match_exact']}/{summary['total']}。")
        return 0 if report["status"] == "completed" else 1
    except (OSError, ValueError, KeyError, TypeError):
        print("数据、模型配置或输出路径校验失败；未输出密钥和个人内容。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
