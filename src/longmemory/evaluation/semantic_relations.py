"""冻结合成 L1 上的语义配对覆盖评估；不读取个人数据库。"""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path

from longmemory.core.common.identifiers import MemoryId, MemorySubjectId
from longmemory.core.memory.l1_atomic.models import AtomicMemory
from longmemory.core.memory.quality.semantic_pairing import propose_semantic_relation_pairs
from longmemory.core.memory.quality.semantic_relations import SemanticRelation


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
