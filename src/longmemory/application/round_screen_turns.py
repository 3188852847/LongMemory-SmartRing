"""圆屏方法中立的召回凭据；层名属于各引擎，不进入平台协议。"""

from dataclasses import dataclass
from hashlib import sha256
import re


@dataclass(frozen=True)
class PlatformTurnCompletion:
    assistant_message_id: str
    created: bool


def memory_receipt(prepared):
    items = prepared.support.retrieved
    return {
        "retrieved_count": None if items is None else len(items),
        "retrieval_strategy": prepared.support.retrieval_strategy,
        "evidence": None if items is None else [
            {"item_id": item.item_id, "rank": rank,
             "content_sha256": sha256(item.content.encode("utf-8")).hexdigest(),
             "source_event_ids": (None if item.source_event_ids is None else list(item.source_event_ids))}
            for rank, item in enumerate(items, 1)
        ],
    }


def validate_receipt(value):
    """只验证中立证据结构；原始回执一致性仍由持久账本比较。"""
    invalid = ValueError("round_screen_retrieval_receipt_invalid")
    if not isinstance(value, dict) or set(value) != {"retrieved_count", "retrieval_strategy", "evidence"}:
        raise invalid
    count, evidence, strategy = value["retrieved_count"], value["evidence"], value["retrieval_strategy"]
    if strategy is not None and (not isinstance(strategy, str) or not 1 <= len(strategy.strip()) <= 240):
        raise invalid
    if count is None:
        if evidence is not None:
            raise invalid
        return
    if type(count) is not int or not 0 <= count <= 300 or not isinstance(evidence, list) or len(evidence) != count:
        raise invalid
    seen = set()
    for rank, item in enumerate(evidence, 1):
        if (not isinstance(item, dict) or set(item) != {"item_id", "rank", "content_sha256", "source_event_ids"}
                or not isinstance(item["item_id"], str) or not 1 <= len(item["item_id"]) <= 200
                or item["item_id"] in seen or type(item["rank"]) is not int or item["rank"] != rank
                or not isinstance(item["content_sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", item["content_sha256"]) is None):
            raise invalid
        ids = item["source_event_ids"]
        if ids is not None and (not isinstance(ids, list) or len(ids) > 300
                or any(not isinstance(source, str) or not 1 <= len(source) <= 200 for source in ids)):
            raise invalid
        seen.add(item["item_id"])
