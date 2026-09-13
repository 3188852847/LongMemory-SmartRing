"""冻结合成 L1 上的语义配对与关系分类评估；不读取个人数据库。"""

import argparse
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from longmemory.adapters.llm.semantic_relation import (
    OpenAICompatibleSemanticRelationReviewer,
    SEMANTIC_RELATION_PROMPT_SHA256,
)
from longmemory.core.common.identifiers import MemoryId, MemorySubjectId
from longmemory.core.memory.l1_atomic.models import AtomicMemory
from longmemory.core.memory.quality.semantic_pairing import propose_semantic_relation_pairs
from longmemory.core.memory.quality.semantic_relations import (
    SemanticRelation,
    SemanticRelationError,
    SemanticRelationPair,
)
from longmemory.evaluation.runner import provenance
from longmemory.infrastructure.config.model_profiles import ModelProfileStore


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = ROOT / "datasets/synthetic/l1_semantic_relations_v1.json"
PROTOCOL = "l1-semantic-relation-evaluation-v1"


@dataclass(frozen=True, slots=True)
class SemanticRelationDataset:
    dataset_id: str
    memories: tuple[dict, ...]
    annotations: tuple[dict, ...]
    sha256: str


def load_semantic_relation_dataset(path: Path) -> SemanticRelationDataset:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
        if set(payload) != {"schema_version", "dataset_id", "memories", "annotations"}:
            raise ValueError
        if payload["schema_version"] != 1 or payload["dataset_id"] != "l1-semantic-relations-v1":
            raise ValueError
        memories, annotations = payload["memories"], payload["annotations"]
        if not isinstance(memories, list) or not isinstance(annotations, list):
            raise ValueError
        memory_ids = set()
        memory_by_id = {}
        for item in memories:
            if (
                not isinstance(item, dict)
                or set(item) != {"id", "split", "subject_id", "content", "recorded_at"}
                or item["split"] not in {"dev", "holdout"}
                or not all(isinstance(item[key], str) and item[key].strip()
                           for key in {"id", "subject_id", "content", "recorded_at"})
                or item["id"] in memory_ids
            ):
                raise ValueError
            datetime.fromisoformat(item["recorded_at"].replace("Z", "+00:00"))
            memory_ids.add(item["id"])
            memory_by_id[item["id"]] = item
        annotation_keys = set()
        for item in annotations:
            if (
                not isinstance(item, dict)
                or set(item) != {"id", "split", "left_id", "right_id", "relation"}
                or item["split"] not in {"dev", "holdout"}
                or not isinstance(item["id"], str)
                or not item["id"].strip()
                or item["left_id"] not in memory_ids
                or item["right_id"] not in memory_ids
                or item["left_id"] == item["right_id"]
            ):
                raise ValueError
            relation = SemanticRelation(item["relation"])
            left, right = memory_by_id[item["left_id"]], memory_by_id[item["right_id"]]
            pair_key = tuple(sorted((item["left_id"], item["right_id"])))
            if (
                item["id"] in annotation_keys
                or pair_key in annotation_keys
                or left["split"] != item["split"]
                or right["split"] != item["split"]
                or left["subject_id"] != right["subject_id"]
                or relation is SemanticRelation.UNCERTAIN
            ):
                raise ValueError
            annotation_keys.update((item["id"], pair_key))
        if {item["split"] for item in memories} != {"dev", "holdout"}:
            raise ValueError
        if {item["split"] for item in annotations} != {"dev", "holdout"}:
            raise ValueError
        return SemanticRelationDataset(
            payload["dataset_id"], tuple(memories), tuple(annotations), sha256(raw).hexdigest(),
        )
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ValueError("semantic_relation_dataset_invalid") from None


def evaluate_semantic_pairing(dataset, *, encoder, split, maximum_candidates=20):
    if split not in {"dev", "holdout"}:
        raise ValueError("semantic_relation_split_invalid")
    rows = [item for item in dataset.memories if item["split"] == split]
    memories = tuple(AtomicMemory(
        MemoryId(item["id"]), MemorySubjectId(item["subject_id"]), item["content"],
        datetime.fromisoformat(item["recorded_at"].replace("Z", "+00:00")),
    ) for item in rows)
    candidates = propose_semantic_relation_pairs(
        memories, encoder=encoder, maximum_candidates=maximum_candidates,
    )
    expected = {
        tuple(sorted((item["left_id"], item["right_id"]))): item["relation"]
        for item in dataset.annotations if item["split"] == split
    }
    found = {
        (item.pair.left_memory_id, item.pair.right_memory_id) for item in candidates
    }
    hits = set(expected).intersection(found)
    return {
        "dataset_id": dataset.dataset_id,
        "dataset_sha256": dataset.sha256,
        "split": split,
        "candidate_limit": maximum_candidates,
        "annotated_pair_count": len(expected),
        "annotated_pair_hits": len(hits),
        "annotated_pair_recall": len(hits) / len(expected) if expected else None,
        "unannotated_candidate_count": len(found - set(expected)),
        "candidates": [{
            "pair_id": item.pair.pair_id,
            "left_id": item.pair.left_memory_id,
            "right_id": item.pair.right_memory_id,
            "cosine_similarity": item.cosine_similarity,
            "expected_relation": expected.get((item.pair.left_memory_id, item.pair.right_memory_id)),
        } for item in candidates],
    }


def _annotated_pairs(dataset: SemanticRelationDataset, split: str):
    memories = {item["id"]: item for item in dataset.memories}
    selected = []
    expected = {}
    for annotation in dataset.annotations:
        if annotation["split"] != split:
            continue
        left, right = memories[annotation["left_id"]], memories[annotation["right_id"]]
        left, right = (left, right) if left["id"] <= right["id"] else (right, left)
        pair_id = annotation["id"]
        selected.append(SemanticRelationPair(
            pair_id, left["id"], right["id"], left["content"], right["content"],
            left["recorded_at"], right["recorded_at"],
        ))
        expected[pair_id] = annotation["relation"]
    return tuple(selected), expected


def run_semantic_relation_review(
    dataset: SemanticRelationDataset,
    reviewer,
    *,
    split: str = "dev",
    unlock_holdout: bool = False,
    output_root: Path | None = None,
    model_config: dict | None = None,
):
    if split not in {"dev", "holdout"} or (split == "holdout" and not unlock_holdout):
        raise ValueError("semantic_relation_split_locked")
    pairs, expected = _annotated_pairs(dataset, split)
    manifest = {
        "protocol": PROTOCOL,
        "started_at": datetime.now(UTC).isoformat(),
        "code": provenance(),
        "dataset_id": dataset.dataset_id,
        "dataset_sha256": dataset.sha256,
        "split": split,
        "pair_order": [item.pair_id for item in pairs],
        "reviewer_version": reviewer.version,
        "prompt_sha256": SEMANTIC_RELATION_PROMPT_SHA256,
        "model": model_config,
        "request_limit": 1,
        "retry_limit": 0,
        "limitations": [
            "synthetic_only", "annotated_pairs_only",
            "no_personal_database_access", "no_memory_writes",
        ],
    }
    report = {"manifest": manifest, "status": "running", "rows": [], "summary": {}}
    run_dir = None
    if output_root is not None:
        run_dir = output_root.resolve() / ("l1-semantic-relations-" + uuid4().hex)
        run_dir.mkdir(parents=True, exist_ok=False)

    def checkpoint():
        if run_dir is not None:
            temporary = run_dir / "report.json.tmp"
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(run_dir / "report.json")

    checkpoint()
    started = perf_counter()
    try:
        review = reviewer.review(pairs)
        rows = []
        confusion = {}
        for decision in review.decisions:
            expected_relation = expected[decision.pair_id]
            predicted = decision.relation.value
            confusion.setdefault(expected_relation, {}).setdefault(predicted, 0)
            confusion[expected_relation][predicted] += 1
            rows.append({
                "pair_id": decision.pair_id,
                "expected_relation": expected_relation,
                "predicted_relation": predicted,
                "exact": predicted == expected_relation,
                "decision": asdict(decision),
            })
        compatible_false_alarm = sum(
            row["expected_relation"] == "compatible"
            and row["predicted_relation"] in {"possible_conflict", "possible_change"}
            for row in rows
        )
        conflict_missed = sum(
            row["expected_relation"] == "possible_conflict"
            and row["predicted_relation"] not in {"possible_conflict", "uncertain"}
            for row in rows
        )
        report.update(status="completed", rows=rows, summary={
            "total": len(rows),
            "completed": len(rows),
            "exact": sum(row["exact"] for row in rows),
            "relation_accuracy": sum(row["exact"] for row in rows) / len(rows),
            "compatible_false_alarm": compatible_false_alarm,
            "conflict_missed": conflict_missed,
            "confusion": confusion,
            "request_attempts": 1,
        })
    except SemanticRelationError as error:
        report.update(status="completed_with_errors", rows=[], summary={
            "total": len(pairs), "completed": 0, "exact": 0,
            "relation_accuracy": None, "compatible_false_alarm": None,
            "conflict_missed": None, "request_attempts": 1,
            "error": str(error),
        })
    report["duration_ms"] = round((perf_counter() - started) * 1000, 3)
    report["finished_at"] = datetime.now(UTC).isoformat()
    checkpoint()
    return run_dir, report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="评估冻结 L1 配对的语义关系分类")
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
        dataset = load_semantic_relation_dataset(DEFAULT_DATASET)
        settings = ModelProfileStore(ROOT).settings(args.model_profile)
        reviewer = OpenAICompatibleSemanticRelationReviewer(settings)
        config = {
            "profile": args.model_profile,
            "provider": settings.provider,
            "model": settings.model,
            "timeout_seconds": settings.timeout_seconds,
            "endpoint_sha256": sha256(settings.base_url.encode()).hexdigest(),
        }
        print(f"将在冻结 {args.split} 合成集发出最多 1 次批量请求；不重试、不读个人库。")
        path, report = run_semantic_relation_review(
            dataset, reviewer, split=args.split, unlock_holdout=args.unlock_holdout,
            output_root=args.output_root, model_config=config,
        )
        summary = report["summary"]
        print(f"报告：{path / 'report.json'}")
        print(f"完成 {summary['completed']}/{summary['total']}；关系精确 "
              f"{summary['exact']}/{summary['total']}；可并存误报 "
              f"{summary['compatible_false_alarm']}；冲突漏判 {summary['conflict_missed']}。")
        return 0 if report["status"] == "completed" else 1
    except (OSError, ValueError, KeyError, TypeError):
        print("数据、模型配置或输出路径校验失败；未输出密钥和记忆正文。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
