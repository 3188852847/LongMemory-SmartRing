"""自动整理候选的独立风险复核契约。

生成模型的原始回答不能自报“安全”。整理服务把已经通过来源白名单校验的
候选与证据重新封装后，交给独立复核步骤；任何缺失、截断或格式异常都失败
关闭，不能把“没有结果”解释为低风险。
"""

from dataclasses import dataclass
import json
from typing import Protocol

from .models import ConsolidationStage


MAX_RISK_REVIEW_OUTPUT_CHARS = 8_000


class ConsolidationRiskReviewError(ValueError):
    """固定错误边界，不携带模型原文或个人记忆正文。"""


@dataclass(frozen=True, slots=True)
class ConsolidationRiskEvidence:
    """只在单次复核期间存在的、已确认来自用户链路的证据。"""

    source_id: str
    content: str

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.content.strip():
            raise ValueError("consolidation_risk_evidence_invalid")


@dataclass(frozen=True, slots=True)
class ConsolidationRiskReviewInput:
    stage: ConsolidationStage
    operation: str
    candidate: str
    evidence: tuple[ConsolidationRiskEvidence, ...]
    current_memories: tuple[ConsolidationRiskEvidence, ...] = ()

    def __post_init__(self) -> None:
        if not self.operation.strip() or not self.candidate.strip() or not self.evidence:
            raise ValueError("consolidation_risk_input_invalid")
        if len({item.source_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("consolidation_risk_evidence_duplicate")


@dataclass(frozen=True, slots=True)
class ConsolidationRiskReview:
    """严格解析后的语义风险信号；完整只表示所有规定字段都已回答。"""

    sensitive: bool
    unresolved_conflict: bool
    clarification_allowed: bool
    reason_codes: tuple[str, ...]
    reviewer_version: str
    assessment_complete: bool = True

    def __post_init__(self) -> None:
        if not self.reviewer_version.strip() or not self.assessment_complete:
            raise ValueError("consolidation_risk_review_incomplete")
        if any(not code.strip() or len(code) > 80 for code in self.reason_codes):
            raise ValueError("consolidation_risk_reason_invalid")


class ConsolidationRiskReviewer(Protocol):
    """由应用装配的独立复核边界；不能复用候选响应中的自报字段。"""

    @property
    def ready(self) -> bool: ...

    @property
    def version(self) -> str: ...

    def review(self, value: ConsolidationRiskReviewInput) -> ConsolidationRiskReview: ...


def parse_consolidation_risk_review(
    raw: str, *, reviewer_version: str,
) -> ConsolidationRiskReview:
    """只接受封闭 JSON；字段遗漏、重复、额外字段和非布尔值全部拒绝。"""

    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_RISK_REVIEW_OUTPUT_CHARS:
        raise ConsolidationRiskReviewError("consolidation_risk_review_output_invalid")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ConsolidationRiskReviewError("consolidation_risk_review_duplicate_field")
            result[key] = value
        return result

    try:
        data = json.loads(raw, object_pairs_hook=unique_object)
        if not isinstance(data, dict) or set(data) != {
            "schema_version", "sensitive", "unresolved_conflict",
            "clarification_allowed", "reason_codes",
        }:
            raise ValueError
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError
        flags = (
            data["sensitive"], data["unresolved_conflict"],
            data["clarification_allowed"],
        )
        reasons = data["reason_codes"]
        if any(type(value) is not bool for value in flags):
            raise ValueError
        if (
            not isinstance(reasons, list)
            or len(reasons) > 8
            or any(not isinstance(code, str) for code in reasons)
            or len(set(reasons)) != len(reasons)
        ):
            raise ValueError
        return ConsolidationRiskReview(
            sensitive=flags[0],
            unresolved_conflict=flags[1],
            clarification_allowed=flags[2],
            reason_codes=tuple(reasons),
            reviewer_version=reviewer_version,
        )
    except ConsolidationRiskReviewError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ConsolidationRiskReviewError(
            "consolidation_risk_review_schema_invalid"
        ) from None
