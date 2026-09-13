"""L1 语义关系复核的严格领域契约。

向量相似度只能产生待检查配对；模型也只能给出候选关系，不能决定哪条事实为真，
更不能在这里执行纠正、事实变化、取代或删除。
"""

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Protocol


MAX_RELATION_PAIRS = 20
MAX_RELATION_OUTPUT_CHARS = 32_000


class SemanticRelationError(ValueError):
    """不携带模型原始响应或个人记忆正文的稳定失败边界。"""


class SemanticRelation(StrEnum):
    EQUIVALENT = "equivalent"
    POSSIBLE_CONFLICT = "possible_conflict"
    POSSIBLE_CHANGE = "possible_change"
    COMPATIBLE = "compatible"
    UNCERTAIN = "uncertain"


class SemanticRelationReason(StrEnum):
    SAME_CLAIM = "same_claim"
    OPPOSITE_POLARITY = "opposite_polarity"
    DIFFERENT_VALUE_SAME_ATTRIBUTE = "different_value_same_attribute"
    EXPLICIT_CHANGE_OVER_TIME = "explicit_change_over_time"
    COEXISTING_CLAIMS = "coexisting_claims"
    DIFFERENT_ATTRIBUTE = "different_attribute"
    INSUFFICIENT_CONTEXT = "insufficient_context"


_ALLOWED_REASONS = {
    SemanticRelation.EQUIVALENT: {SemanticRelationReason.SAME_CLAIM},
    SemanticRelation.POSSIBLE_CONFLICT: {
        SemanticRelationReason.OPPOSITE_POLARITY,
        SemanticRelationReason.DIFFERENT_VALUE_SAME_ATTRIBUTE,
    },
    SemanticRelation.POSSIBLE_CHANGE: {
        SemanticRelationReason.EXPLICIT_CHANGE_OVER_TIME,
    },
    SemanticRelation.COMPATIBLE: {
        SemanticRelationReason.COEXISTING_CLAIMS,
        SemanticRelationReason.DIFFERENT_ATTRIBUTE,
    },
    SemanticRelation.UNCERTAIN: {SemanticRelationReason.INSUFFICIENT_CONTEXT},
}


@dataclass(frozen=True, slots=True)
class SemanticRelationPair:
    """同一主体下由前级召回器提出的一对当前 L1。"""

    pair_id: str
    left_memory_id: str
    right_memory_id: str
    left_content: str
    right_content: str
    left_recorded_at: str
    right_recorded_at: str


@dataclass(frozen=True, slots=True)
class SemanticRelationDecision:
    pair_id: str
    relation: SemanticRelation
    reason: SemanticRelationReason
    left_quote: str
    right_quote: str


@dataclass(frozen=True, slots=True)
class SemanticRelationReview:
    reviewer_version: str
    decisions: tuple[SemanticRelationDecision, ...]


class SemanticRelationReviewer(Protocol):
    @property
    def version(self) -> str: ...

    def review(
        self, pairs: tuple[SemanticRelationPair, ...],
    ) -> SemanticRelationReview: ...


def validate_semantic_relation_pairs(
    pairs: tuple[SemanticRelationPair, ...],
) -> None:
    """限制单次模型暴露范围，并保证配对身份没有歧义。"""

    if not 1 <= len(pairs) <= MAX_RELATION_PAIRS:
        raise SemanticRelationError("semantic_relation_pair_count_invalid")
    pair_ids = [item.pair_id for item in pairs]
    if len(set(pair_ids)) != len(pair_ids):
        raise SemanticRelationError("semantic_relation_pair_id_duplicate")
    for item in pairs:
        if (
            not item.pair_id
            or not item.left_memory_id
            or not item.right_memory_id
            or item.left_memory_id == item.right_memory_id
            or not item.left_content.strip()
            or not item.right_content.strip()
        ):
            raise SemanticRelationError("semantic_relation_pair_invalid")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SemanticRelationError("semantic_relation_duplicate_field")
        result[key] = value
    return result


def parse_semantic_relation_review(
    raw: str,
    *,
    pairs: tuple[SemanticRelationPair, ...],
    reviewer_version: str,
) -> SemanticRelationReview:
    """只接受完整、顺序一致且摘录可在输入原文中定位的封闭分类。"""

    validate_semantic_relation_pairs(pairs)
    if (
        not isinstance(raw, str)
        or not raw.strip()
        or len(raw) > MAX_RELATION_OUTPUT_CHARS
        or not reviewer_version.strip()
    ):
        raise SemanticRelationError("semantic_relation_output_invalid")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(payload, dict) or set(payload) != {"schema_version", "decisions"}:
            raise ValueError
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            raise ValueError
        rows = payload["decisions"]
        if not isinstance(rows, list) or len(rows) != len(pairs):
            raise ValueError
        decisions = []
        for expected, row in zip(pairs, rows, strict=True):
            if not isinstance(row, dict) or set(row) != {
                "pair_id", "relation", "reason_code", "left_quote", "right_quote",
            }:
                raise ValueError
            if row["pair_id"] != expected.pair_id:
                raise ValueError
            relation = SemanticRelation(row["relation"])
            reason = SemanticRelationReason(row["reason_code"])
            left_quote, right_quote = row["left_quote"], row["right_quote"]
            if (
                reason not in _ALLOWED_REASONS[relation]
                or not isinstance(left_quote, str)
                or not left_quote.strip()
                or left_quote not in expected.left_content
                or not isinstance(right_quote, str)
                or not right_quote.strip()
                or right_quote not in expected.right_content
            ):
                raise ValueError
            decisions.append(SemanticRelationDecision(
                expected.pair_id, relation, reason, left_quote, right_quote,
            ))
        return SemanticRelationReview(reviewer_version, tuple(decisions))
    except SemanticRelationError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError):
        raise SemanticRelationError("semantic_relation_schema_invalid") from None
