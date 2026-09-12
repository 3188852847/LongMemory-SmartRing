"""召回之后的证据充分性门控契约。

该门控不决定“哪条文本语义相近”，只检查已召回候选是否真的
包含回答当前问题所需的信息。这使“主题相关”和“足以作答”不会
被一个相似度分数混为同一件事。
"""

from dataclasses import dataclass
import json
from typing import Protocol


MAX_SUFFICIENCY_OUTPUT_CHARS = 16_000
SUFFICIENCY_REASON_CODES = frozenset({
    "direct_support",
    "partial_support",
    "topic_only",
    "missing_attribute",
    "irrelevant",
    "conflicting_evidence",
})


class EvidenceSufficiencyError(ValueError):
    """固定失败边界，不携带模型原文或记忆正文。"""


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    item_id: str
    content: str

    def __post_init__(self) -> None:
        if not self.item_id.strip() or not self.content.strip():
            raise ValueError("evidence_sufficiency_candidate_invalid")


@dataclass(frozen=True, slots=True)
class EvidenceSufficiencyInput:
    query: str
    candidates: tuple[EvidenceCandidate, ...]

    def __post_init__(self) -> None:
        if (not self.query.strip() or not self.candidates
                or len({item.item_id for item in self.candidates}) != len(self.candidates)):
            raise ValueError("evidence_sufficiency_input_invalid")


@dataclass(frozen=True, slots=True)
class EvidenceSufficiencyDecision:
    item_id: str
    supports_answer: bool
    reason_code: str

    def __post_init__(self) -> None:
        if (not self.item_id.strip() or type(self.supports_answer) is not bool
                or self.reason_code not in SUFFICIENCY_REASON_CODES):
            raise ValueError("evidence_sufficiency_decision_invalid")
        if self.supports_answer and self.reason_code not in {
            "direct_support", "partial_support",
        }:
            raise ValueError("evidence_sufficiency_decision_inconsistent")
        if not self.supports_answer and self.reason_code in {
            "direct_support", "partial_support",
        }:
            raise ValueError("evidence_sufficiency_decision_inconsistent")


@dataclass(frozen=True, slots=True)
class EvidenceSufficiencyReview:
    decisions: tuple[EvidenceSufficiencyDecision, ...]
    reviewer_version: str

    def __post_init__(self) -> None:
        if (not self.reviewer_version.strip() or not self.decisions
                or len({item.item_id for item in self.decisions}) != len(self.decisions)):
            raise ValueError("evidence_sufficiency_review_invalid")

    @property
    def supported_ids(self) -> tuple[str, ...]:
        return tuple(item.item_id for item in self.decisions if item.supports_answer)


class EvidenceSufficiencyGate(Protocol):
    @property
    def version(self) -> str: ...

    def review(self, value: EvidenceSufficiencyInput) -> EvidenceSufficiencyReview: ...


def parse_evidence_sufficiency_review(
        raw: str, *, expected_ids: tuple[str, ...], reviewer_version: str,
) -> EvidenceSufficiencyReview:
    """只接受候选 ID 完整对齐的封闭 JSON；格式异常时失败关闭。"""

    if (not isinstance(raw, str) or not raw.strip()
            or len(raw) > MAX_SUFFICIENCY_OUTPUT_CHARS
            or not expected_ids or len(set(expected_ids)) != len(expected_ids)
            or not reviewer_version.strip()):
        raise EvidenceSufficiencyError("evidence_sufficiency_output_invalid")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceSufficiencyError("evidence_sufficiency_duplicate_field")
            result[key] = value
        return result

    try:
        data = json.loads(raw, object_pairs_hook=unique_object)
        if not isinstance(data, dict) or set(data) != {"schema_version", "decisions"}:
            raise ValueError
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError
        rows = data["decisions"]
        if not isinstance(rows, list) or len(rows) != len(expected_ids):
            raise ValueError
        decisions = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "id", "supports_answer", "reason_code",
            }:
                raise ValueError
            decisions.append(EvidenceSufficiencyDecision(
                item_id=row["id"],
                supports_answer=row["supports_answer"],
                reason_code=row["reason_code"],
            ))
        # 顺序也必须与输入一致，便于将审计结果与原排名稳定绑定。
        if tuple(item.item_id for item in decisions) != expected_ids:
            raise ValueError
        return EvidenceSufficiencyReview(tuple(decisions), reviewer_version)
    except EvidenceSufficiencyError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError):
        raise EvidenceSufficiencyError(
            "evidence_sufficiency_schema_invalid"
        ) from None
