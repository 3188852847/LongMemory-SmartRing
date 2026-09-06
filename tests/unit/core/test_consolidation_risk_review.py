"""独立风险复核必须严格解析并对缺失信息失败关闭。"""

import pytest

from longmemory.core.memory.consolidation.risk_review import (
    ConsolidationRiskReviewError,
    parse_consolidation_risk_review,
)


VALID = (
    '{"schema_version":1,"sensitive":false,'
    '"unresolved_conflict":false,"clarification_allowed":true,'
    '"reason_codes":["low_risk_preference"]}'
)


def test_complete_closed_schema_becomes_versioned_review():
    result = parse_consolidation_risk_review(
        VALID, reviewer_version="synthetic-review-v1",
    )
    assert result.assessment_complete is True
    assert result.sensitive is False
    assert result.reason_codes == ("low_risk_preference",)
    assert result.reviewer_version == "synthetic-review-v1"


@pytest.mark.parametrize("raw", [
    '{"schema_version":1,"sensitive":false,"unresolved_conflict":false,'
    '"clarification_allowed":true,"reason_codes":[],'
    '"assessment_complete":true}',
    '{"schema_version":1,"sensitive":"false","unresolved_conflict":false,'
    '"clarification_allowed":true,"reason_codes":[]}',
    '{"schema_version":1,"sensitive":false,"sensitive":true,'
    '"unresolved_conflict":false,"clarification_allowed":true,"reason_codes":[]}',
    '{"schema_version":2,"sensitive":false,"unresolved_conflict":false,'
    '"clarification_allowed":true,"reason_codes":[]}',
])
def test_incomplete_ambiguous_or_extra_output_is_rejected(raw):
    with pytest.raises(ConsolidationRiskReviewError):
        parse_consolidation_risk_review(raw, reviewer_version="synthetic-review-v1")
