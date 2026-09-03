"""小规模精确向量索引：编码器可替换，核心不依赖 Torch 或模型供应商。

索引只保存历史记忆向量；查询不写索引。这里的余弦分数不是事实可信度，
也不是答案存在的概率。默认只比较排名，不臆造已经校准的拒答阈值。
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Protocol, Sequence


class TextEncoder(Protocol):
    def encode_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...
    def encode_query(self, text: str) -> Sequence[float]: ...


@dataclass(frozen=True)
class VectorDocument:
    item_id: str
    content: str
    source_event_ids: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.item_id, str) or not self.item_id.strip():
            raise ValueError("索引条目 ID 无效。")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("索引正文为空。")
        if (not isinstance(self.source_event_ids, tuple) or not self.source_event_ids
                or any(not isinstance(s, str) or not s.strip() for s in self.source_event_ids)
                or len(set(self.source_event_ids)) != len(self.source_event_ids)):
            raise ValueError("索引必须保留不重复的来源 ID。")


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def unit_vector(values):
    vector = tuple(values)
    if not vector or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
        raise ValueError("向量必须为有限数值，不能有空向量、NaN 或无穷。")
    norm = math.hypot(*vector)
    if norm == 0 or not math.isfinite(norm):
        raise ValueError("零向量或溢出向量不可用于余弦检索。")
    return tuple(v / norm for v in vector)


class ExactVectorIndex:
    """O(ND) 扫描的研究起点，不冒称大规模向量数据库。"""

    def __init__(self, documents, vectors, *, encoder_id):
        self.documents = tuple(documents)
        self.vectors = tuple(unit_vector(v) for v in vectors)
        self.encoder_id = encoder_id
        if not isinstance(encoder_id, str) or not encoder_id.strip():
            raise ValueError("缺少编码器身份。")
        if len(self.documents) != len(self.vectors):
            raise ValueError("条目数和向量数不一致。")
        if len({d.item_id for d in self.documents}) != len(self.documents):
            raise ValueError("索引条目 ID 重复。")
        if len({len(v) for v in self.vectors}) > 1:
            raise ValueError("索引向量维度不一致。")

    @classmethod
    def build(cls, documents, encoder, *, encoder_id):
        documents = tuple(documents)
        vectors = encoder.encode_documents([d.content for d in documents]) if documents else ()
        return cls(documents, vectors, encoder_id=encoder_id)

    def search(self, query_vector, *, limit=5, min_score=None):
        if type(limit) is not int or limit < 1:
            raise ValueError("检索数量必须是正整数。")
        if min_score is not None and (type(min_score) not in (int, float)
                                     or not math.isfinite(min_score) or not -1 <= min_score <= 1):
            raise ValueError("余弦阈值必须在 [-1, 1]。")
        query = unit_vector(query_vector)
        if self.vectors and len(query) != len(self.vectors[0]):
            raise ValueError("查询与索引维度不同。")
        scored = [(document, max(-1.0, min(1.0, math.fsum(a * b for a, b in zip(query, vector)))))
                  for document, vector in zip(self.documents, self.vectors)]
        # 分数相同时保留冻结语料顺序，避免随机打破平局。
        scored.sort(key=lambda item: item[1], reverse=True)
        return tuple(item for item in scored if min_score is None or item[1] >= min_score)[:limit]

    def save(self, path: Path):
        payload = {"schema_version": 1, "encoder_id": self.encoder_id,
                   "documents": [asdict(d) for d in self.documents], "vectors": self.vectors}
        with path.open("x", encoding="utf-8") as stream:
            json.dump({"payload": payload, "sha256": fingerprint(payload)}, stream,
                      ensure_ascii=False, allow_nan=False)

    @classmethod
    def load(cls, path: Path, *, encoder_id):
        data = json.loads(path.read_text(encoding="utf-8"))
        payload = data["payload"]
        if (data["sha256"] != fingerprint(payload) or payload["schema_version"] != 1
                or payload["encoder_id"] != encoder_id):
            raise ValueError("索引损坏、版本不符或编码器发生变化。")
        documents = [VectorDocument(d["item_id"], d["content"], tuple(d["source_event_ids"]))
                     for d in payload["documents"]]
        return cls(documents, payload["vectors"], encoder_id=encoder_id)
