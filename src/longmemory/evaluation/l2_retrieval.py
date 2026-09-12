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
    sha256: str


def load_l2_corpus(path: Path) -> L2Corpus:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("schema_version") != 1 or payload.get("dataset_id") != "l2-retrieval-v1":
        raise ValueError("l2_retrieval_dataset_invalid")
    scenarios, cases = payload.get("scenarios"), payload.get("cases")
    if (not isinstance(scenarios, list) or not isinstance(cases, list)
            or len({item.get("id") for item in scenarios}) != len(scenarios)):
        raise ValueError("l2_retrieval_dataset_invalid")
    known = {item["id"] for item in scenarios}
    for item in scenarios:
        if set(item) != {"id", "title", "summary"} or not all(
                isinstance(item[key], str) and item[key].strip() for key in item):
            raise ValueError("l2_retrieval_dataset_invalid")
    for case in cases:
        if (set(case) != {"id", "category", "query", "expected_ids"}
                or not isinstance(case["query"], str)
                or not isinstance(case["expected_ids"], list)
                or not set(case["expected_ids"]) <= known):
            raise ValueError("l2_retrieval_dataset_invalid")
    return L2Corpus(payload["dataset_id"], tuple(scenarios), tuple(cases),
                    sha256(raw).hexdigest())


def evaluate_l2_retrieval(corpus: L2Corpus, *, encoder=None, limit: int = 3) -> dict:
    """比较关键词与可选稠密排名；无答案题不会被从分母删除。"""

    documents = tuple(VectorDocument(
        item["id"], item["title"] + " " + item["summary"], ("synthetic:" + item["id"],),
    ) for item in corpus.scenarios)
    index = (ExactVectorIndex.build(documents, encoder, encoder_id=encoder.identity)
             if encoder is not None else None)
    strategies = ["l2_keyword_v1"] + (["l2_dense_cosine"] if index else [])
    results = {name: [] for name in strategies}
    for case in corpus.cases:
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
            results[strategy].append({
                "case_id": case["id"], "category": case["category"],
                "expected_ids": case["expected_ids"], "retrieved": ranking,
                "hit_at_k": bool(expected and first is not None),
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
            "mean_reciprocal_rank": sum(row["reciprocal_rank"] for row in answerable) / len(answerable),
            "unanswerable": len(unknown),
            "correct_abstention": sum(row["correct_abstention"] for row in unknown),
        }
    return {"dataset_id": corpus.dataset_id, "dataset_sha256": corpus.sha256,
            "limit": limit, "summary": summary, "results": results}


def main() -> None:
    root = Path(__file__).parents[3]
    parser = argparse.ArgumentParser(description="隔离合成 L2 检索比较")
    parser.add_argument("--dataset", type=Path,
                        default=root / "datasets/synthetic/l2_retrieval_v1.json")
    parser.add_argument("--embedding-model-dir", type=Path)
    args = parser.parse_args()
    encoder = None
    if args.embedding_model_dir is not None:
        from longmemory.adapters.llm.local_embedding import LocalBGEEncoder
        encoder = LocalBGEEncoder(args.embedding_model_dir)
    report = evaluate_l2_retrieval(load_l2_corpus(args.dataset), encoder=encoder)
    print(json.dumps({
        "dataset_id": report["dataset_id"],
        "dataset_sha256": report["dataset_sha256"],
        "summary": report["summary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
