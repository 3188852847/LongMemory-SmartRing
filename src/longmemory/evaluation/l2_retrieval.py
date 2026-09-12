"""冻结合成 L2 语料上的检索比较；不打开个人数据库或调用回答模型。"""

from dataclasses import dataclass
import argparse
from hashlib import sha256
import json
from pathlib import Path

from longmemory.core.memory.retrieval.service import keyword_overlap_score
from longmemory.core.memory.retrieval.vector import ExactVectorIndex, VectorDocument


@dataclass(frozen=True, slots=True)
class L2Corpus:
    dataset_id: str
    scenarios: tuple[dict, ...]
    cases: tuple[dict, ...]
    available_splits: tuple[str, ...]
    sha256: str


def load_l2_corpus(path: Path) -> L2Corpus:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    schema_version = payload.get("schema_version")
    dataset_id = payload.get("dataset_id")
    if ((schema_version == 1 and dataset_id != "l2-retrieval-v1")
            or (schema_version == 2 and dataset_id != "l2-retrieval-v2")
            or schema_version not in {1, 2}):
        raise ValueError("l2_retrieval_dataset_invalid")
    scenarios, cases = payload.get("scenarios"), payload.get("cases")
    if (not isinstance(scenarios, list) or not isinstance(cases, list)
            or not all(isinstance(item, dict) for item in scenarios + cases)
            or len({item.get("id") for item in scenarios}) != len(scenarios)
            or len({item.get("id") for item in cases}) != len(cases)):
        raise ValueError("l2_retrieval_dataset_invalid")
    known = {item.get("id") for item in scenarios}
    active = set()
    for item in scenarios:
        expected_keys = ({"id", "title", "summary"} if schema_version == 1
                         else {"id", "title", "summary", "status"})
        if set(item) != expected_keys or not all(
                isinstance(item[key], str) and item[key].strip()
                for key in {"id", "title", "summary"}):
            raise ValueError("l2_retrieval_dataset_invalid")
        status = item.get("status", "active")
        if status not in {"active", "expired"}:
            raise ValueError("l2_retrieval_dataset_invalid")
        if status == "active":
            active.add(item["id"])
    normalized_cases = []
    for case in cases:
        expected_keys = ({"id", "category", "query", "expected_ids"}
                         if schema_version == 1 else
                         {"id", "split", "category", "query", "expected_ids"})
        split = case.get("split", "legacy")
        if (set(case) != expected_keys
                or not isinstance(case["id"], str)
                or not case["id"].strip()
                or not isinstance(case["category"], str)
                or not case["category"].strip()
                or not isinstance(case["query"], str)
                or not case["query"].strip()
                or not isinstance(case["expected_ids"], list)
                or not all(isinstance(item_id, str) for item_id in case["expected_ids"])
                or len(case["expected_ids"]) != len(set(case["expected_ids"]))
                or not set(case["expected_ids"]) <= known
                or not set(case["expected_ids"]) <= active
                or split not in {"legacy", "dev", "holdout"}):
            raise ValueError("l2_retrieval_dataset_invalid")
        normalized_cases.append({**case, "split": split})
    available_splits = tuple(sorted({case["split"] for case in normalized_cases}))
    if schema_version == 2:
        if set(available_splits) != {"dev", "holdout"}:
            raise ValueError("l2_retrieval_dataset_invalid")
        for split in available_splits:
            split_cases = [case for case in normalized_cases if case["split"] == split]
            if (not any(case["expected_ids"] for case in split_cases)
                    or not any(not case["expected_ids"] for case in split_cases)):
                raise ValueError("l2_retrieval_dataset_invalid")
    return L2Corpus(dataset_id, tuple(scenarios), tuple(normalized_cases),
                    available_splits, sha256(raw).hexdigest())


def evaluate_l2_retrieval(
        corpus: L2Corpus, *, encoder=None, limit: int = 3, split: str | None = None,
) -> dict:
    """比较关键词与可选稠密排名；无答案题不会被从分母删除。"""

    if split is not None and split not in corpus.available_splits:
        raise ValueError("l2_retrieval_split_invalid")
    selected_cases = tuple(
        case for case in corpus.cases if split is None or case["split"] == split
    )
    if not selected_cases:
        raise ValueError("l2_retrieval_split_empty")

    documents = tuple(VectorDocument(
        item["id"], item["title"] + " " + item["summary"], ("synthetic:" + item["id"],),
    ) for item in corpus.scenarios if item.get("status", "active") == "active")
    index = (ExactVectorIndex.build(documents, encoder, encoder_id=encoder.identity)
             if encoder is not None else None)
    strategies = ["l2_keyword_v1"] + (["l2_dense_cosine"] if index else [])
    results = {name: [] for name in strategies}
    for case in selected_cases:
        keyword = sorted(
            ((doc.item_id, keyword_overlap_score(case["query"], doc.content))
             for doc in documents), key=lambda item: (-item[1], item[0]),
        )
        keyword = [item for item in keyword if item[1] > 0][:limit]
        rankings = {"l2_keyword_v1": keyword}
        if index is not None:
            rankings["l2_dense_cosine"] = [
                (doc.item_id, score)
                for doc, score in index.search(encoder.encode_query(case["query"]), limit=limit)
            ]
        expected = set(case["expected_ids"])
        for strategy, ranking in rankings.items():
            ids = [item[0] for item in ranking]
            first = next((rank for rank, item_id in enumerate(ids, 1) if item_id in expected), None)
            evidence_recall = (0.0 if not expected else
                               len(expected.intersection(ids)) / len(expected))
            results[strategy].append({
                "case_id": case["id"], "split": case["split"],
                "category": case["category"],
                "expected_ids": case["expected_ids"], "retrieved": ranking,
                "hit_at_k": bool(expected and first is not None),
                "evidence_recall_at_k": evidence_recall,
                "full_coverage_at_k": bool(expected and evidence_recall == 1.0),
                "reciprocal_rank": 0.0 if first is None else 1.0 / first,
                "correct_abstention": not expected and not ids,
            })
    summary = {}
    for strategy, rows in results.items():
        answerable = [row for row in rows if row["expected_ids"]]
        unknown = [row for row in rows if not row["expected_ids"]]
        summary[strategy] = {
            "answerable": len(answerable),
            "hit_at_k": sum(row["hit_at_k"] for row in answerable),
            "full_coverage_at_k": sum(row["full_coverage_at_k"] for row in answerable),
            "mean_evidence_recall_at_k": (
                sum(row["evidence_recall_at_k"] for row in answerable) / len(answerable)
            ),
            "mean_reciprocal_rank": sum(row["reciprocal_rank"] for row in answerable) / len(answerable),
            "unanswerable": len(unknown),
            "correct_abstention": sum(row["correct_abstention"] for row in unknown),
        }
    return {"dataset_id": corpus.dataset_id, "dataset_sha256": corpus.sha256,
            "split": split or "all", "available_splits": corpus.available_splits,
            "eligible_scenarios": len(documents),
            "excluded_scenarios": len(corpus.scenarios) - len(documents),
            "limit": limit, "summary": summary, "results": results}


def main() -> None:
    root = Path(__file__).parents[3]
    parser = argparse.ArgumentParser(description="隔离合成 L2 检索比较")
    parser.add_argument("--dataset", type=Path,
                        default=root / "datasets/synthetic/l2_retrieval_v2.json")
    parser.add_argument("--split", choices=("dev", "holdout", "all"), default="dev",
                        help="默认只运行开发集；留出集必须显式指定")
    parser.add_argument("--embedding-model-dir", type=Path)
    args = parser.parse_args()
    encoder = None
    if args.embedding_model_dir is not None:
        from longmemory.adapters.llm.local_embedding import LocalBGEEncoder
        encoder = LocalBGEEncoder(args.embedding_model_dir)
    corpus = load_l2_corpus(args.dataset)
    split = None if args.split == "all" else args.split
    report = evaluate_l2_retrieval(corpus, encoder=encoder, split=split)
    print(json.dumps({
        "dataset_id": report["dataset_id"],
        "dataset_sha256": report["dataset_sha256"],
        "split": report["split"],
        "eligible_scenarios": report["eligible_scenarios"],
        "excluded_scenarios": report["excluded_scenarios"],
        "summary": report["summary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
