"""在冻结 L2 开发集上单独评估证据充分性门控。"""

import argparse
from dataclasses import asdict
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
    EvidenceCandidate,
    EvidenceSufficiencyError,
    EvidenceSufficiencyInput,
)
from longmemory.evaluation.l2_retrieval import (
    evaluate_l2_retrieval,
    load_l2_corpus,
    load_l2_relevance_annotations,
)
from longmemory.evaluation.runner import provenance
from longmemory.infrastructure.config.model_profiles import ModelProfileStore


ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = "l2-evidence-sufficiency-evaluation-v1"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _fuse_rows(keyword: dict, dense: dict | None, *, limit: int) -> list[dict]:
    """RRF 只用排名产生候选，不把分数解释为充分性概率。"""

    keyword_scores = dict(keyword["retrieved"])
    dense_scores = dict(dense["retrieved"]) if dense is not None else {}
    rankings = [keyword["retrieved"]]
    if dense is not None:
        rankings.append(dense["retrieved"])
    fused: dict[str, float] = {}
    order: dict[str, int] = {}
    for ranking in rankings:
        for rank, (item_id, _score) in enumerate(ranking, 1):
            order.setdefault(item_id, len(order))
            fused[item_id] = fused.get(item_id, 0.0) + 1.0 / (60 + rank)
    ids = sorted(fused, key=lambda item_id: (-fused[item_id], order[item_id]))[:limit]
    return [{
        "item_id": item_id,
        "keyword_score": keyword_scores.get(item_id),
        "dense_score": dense_scores.get(item_id),
        "fused_score": fused[item_id],
    } for item_id in ids]


def _summary(rows: list[dict]) -> dict:
    completed = [row for row in rows if row["status"] == "completed"]
    answerable = [row for row in rows if row["expected_supported_ids"]]
    unsupported = [row for row in rows if not row["expected_supported_ids"]]
    return {
        "total": len(rows),
        "completed": len(completed),
        "failed": sum(row["status"] == "failed" for row in rows),
        "request_attempts": sum(row.get("request_attempted", False) for row in rows),
        "answerable": len(answerable),
        "answerable_exact_support": sum(
            row.get("exact_supported_set") is True for row in answerable
        ),
        "unsupported": len(unsupported),
        "unsupported_correct_rejection": sum(
            row.get("exact_supported_set") is True for row in unsupported
        ),
        "all_cases_exact": sum(row.get("exact_supported_set") is True for row in rows),
        "false_positive_ids": sum(len(row.get("false_positive_ids", [])) for row in rows),
        "missed_support_ids": sum(len(row.get("missed_support_ids", [])) for row in rows),
    }


def run_l2_sufficiency(
        corpus, annotations, gate, *, encoder=None, split: str = "dev",
        candidate_limit: int = 3, output_root: Path | None = None,
        model_config: dict | None = None,
) -> tuple[Path | None, dict]:
    """每题最多一次门控请求；失败题保留于固定分母且不重试。"""

    if (split != "dev" or type(candidate_limit) is not int
            or not 1 <= candidate_limit <= 5):
        raise ValueError("l2_sufficiency_evaluation_config_invalid")
    retrieval = evaluate_l2_retrieval(
        corpus, encoder=encoder, split=split, limit=max(candidate_limit, 3),
        relevance_annotations=annotations,
    )
    by_scenario = {
        item["id"]: item for item in corpus.scenarios if item.get("status", "active") == "active"
    }
    keyword_rows = {row["case_id"]: row for row in retrieval["results"]["l2_keyword_v1"]}
    dense_rows = {
        row["case_id"]: row for row in retrieval["results"].get("l2_dense_cosine", [])
    }
    cases = [case for case in corpus.cases if case["split"] == split]
    rows = []
    for case in cases:
        candidates = _fuse_rows(
            keyword_rows[case["id"]], dense_rows.get(case["id"]), limit=candidate_limit,
        )
        rows.append({
            "case_id": case["id"], "query": case["query"], "category": case["category"],
            "expected_supported_ids": case["expected_ids"],
            "topical_ids": list(annotations.topical_ids_by_case[case["id"]]),
            "candidates": candidates, "status": "not_run", "error": None,
        })

    manifest = {
        "protocol": PROTOCOL, "started_at": _now(), "code": provenance(),
        "dataset_id": corpus.dataset_id, "dataset_sha256": corpus.sha256,
        "relevance_annotation_id": annotations.annotation_id,
        "relevance_annotation_sha256": annotations.sha256,
        "split": split, "question_order": [case["id"] for case in cases],
        "candidate_strategy": "keyword_dense_rrf_v1" if encoder else "keyword_v1",
        "candidate_limit": candidate_limit,
        "encoder_id": encoder.identity if encoder else None,
        "gate_version": gate.version,
        "gate_prompt_sha256": SUFFICIENCY_GATE_PROMPT_SHA256,
        "model": model_config,
        "request_limit": len(rows), "retry_limit": 0,
        "limitations": [
            "synthetic_development_only", "gate_model_not_answer_model_quality",
            "candidate_generation_and_gate_errors_reported_separately",
            "no_daily_memory_or_personal_database_access", "no_holdout_access",
        ],
    }
    report = {"manifest": manifest, "rows": rows, "status": "running", "summary": _summary(rows)}
    run_dir = None
    stream = None
    if output_root is not None:
        run_dir = output_root.resolve() / ("l2-sufficiency-" + uuid4().hex)
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        stream = (run_dir / "report.json").open("x+", encoding="utf-8")

    def checkpoint() -> None:
        report["summary"] = _summary(rows)
        if stream is not None:
            stream.seek(0)
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.truncate()
            stream.flush()

    checkpoint()
    try:
        for row in rows:
            candidate_values = tuple(EvidenceCandidate(
                item["item_id"],
                by_scenario[item["item_id"]]["title"] + " "
                + by_scenario[item["item_id"]]["summary"],
            ) for item in row["candidates"])
            if not candidate_values:
                row.update(status="completed", predicted_supported_ids=[], decisions=[],
                           exact_supported_set=not row["expected_supported_ids"],
                           false_positive_ids=[],
                           missed_support_ids=list(row["expected_supported_ids"]),
                           request_attempted=False, duration_ms=0.0)
                checkpoint()
                continue
            started = perf_counter()
            row["request_attempted"] = True
            checkpoint()
            try:
                review = gate.review(EvidenceSufficiencyInput(row["query"], candidate_values))
                predicted = list(review.supported_ids)
                expected = set(row["expected_supported_ids"])
                actual = set(predicted)
                row.update(
                    status="completed", decisions=[asdict(item) for item in review.decisions],
                    predicted_supported_ids=predicted,
                    exact_supported_set=actual == expected,
                    false_positive_ids=sorted(actual - expected),
                    missed_support_ids=sorted(expected - actual),
                )
            except EvidenceSufficiencyError as error:
                # 契约异常只有稳定错误码，不携带模型原文或数据正文。
                code = str(error)
                row.update(
                    status="failed",
                    error=(code if code.startswith("evidence_sufficiency_") else "gate_failed"),
                )
            finally:
                row["duration_ms"] = round((perf_counter() - started) * 1000, 3)
                checkpoint()
    finally:
        report.update(
            status="completed" if all(row["status"] == "completed" for row in rows)
            else "completed_with_errors",
            finished_at=_now(),
        )
        checkpoint()
        if stream is not None:
            stream.close()
    return run_dir, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="用真实模型复核冻结 L2 开发集的证据充分性",
    )
    parser.add_argument("--model-profile", choices=("official", "campus"), required=True)
    parser.add_argument("--allow-model-requests", action="store_true",
                        help="明确允许最多 24 次合成数据请求，失败不重试")
    parser.add_argument("--candidate-limit", type=int, default=3)
    parser.add_argument("--embedding-model-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "experiments/runs")
    args = parser.parse_args(argv)
    if not args.allow_model_requests:
        print("未显式允许模型请求；未运行。")
        return 2
    try:
        corpus = load_l2_corpus(ROOT / "datasets/synthetic/l2_retrieval_v2.json")
        annotations = load_l2_relevance_annotations(
            ROOT / "datasets/synthetic/l2_retrieval_v2_relevance_v1.json", corpus,
        )
        from longmemory.adapters.llm.local_embedding import LocalBGEEncoder
        encoder = LocalBGEEncoder(args.embedding_model_dir)
        settings = ModelProfileStore(ROOT).settings(args.model_profile)
        gate = OpenAICompatibleEvidenceSufficiencyGate(settings)
        config = {
            "profile": args.model_profile, "provider": settings.provider,
            "model": settings.model, "timeout_seconds": settings.timeout_seconds,
            "max_tokens": min(settings.max_tokens, 1024),
            "endpoint_sha256": hashlib.sha256(settings.base_url.encode()).hexdigest(),
            "sampling": "provider_default_unverified", "usage_tokens": None,
        }
        print("将在合成 dev 集上最多发出 24 次证据复核请求；不重试、不读个人库。")
        path, report = run_l2_sufficiency(
            corpus, annotations, gate, encoder=encoder,
            candidate_limit=args.candidate_limit, output_root=args.output_root,
            model_config=config,
        )
        print(f"报告：{path / 'report.json'}")
        summary = report["summary"]
        print(f"完成 {summary['completed']}/{summary['total']}；"
              f"有答案精确通过 {summary['answerable_exact_support']}/{summary['answerable']}；"
              f"证据不足正确拒绝 {summary['unsupported_correct_rejection']}/{summary['unsupported']}。")
        return 0 if report["status"] == "completed" else 1
    except (OSError, ValueError, KeyError, TypeError):
        print("数据、模型配置或输出路径校验失败；未输出密钥和数据正文。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
