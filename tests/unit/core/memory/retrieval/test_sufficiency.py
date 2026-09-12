import pytest

from longmemory.core.memory.retrieval.sufficiency import (
    EvidenceSufficiencyError,
    parse_evidence_sufficiency_review,
)


def test_strict_sufficiency_review_accepts_complete_ordered_decisions():
    review = parse_evidence_sufficiency_review(
        '{"schema_version":1,"decisions":['
        '{"id":"cat","supports_answer":false,"reason_code":"missing_attribute"},'
        '{"id":"tea","supports_answer":true,"reason_code":"partial_support"}]}',
        expected_ids=("cat", "tea"), reviewer_version="synthetic-gate-v1",
    )

    assert review.supported_ids == ("tea",)
    assert review.reviewer_version == "synthetic-gate-v1"


@pytest.mark.parametrize("raw", [
    '{"schema_version":1,"decisions":[]}',
    '{"schema_version":1,"decisions":['
    '{"id":"other","supports_answer":false,"reason_code":"irrelevant"}]}',
    '{"schema_version":1,"decisions":['
    '{"id":"cat","supports_answer":true,"reason_code":"missing_attribute"}]}',
    '{"schema_version":1,"decisions":['
    '{"id":"cat","supports_answer":false,"reason_code":"unknown"}]}',
    '```json\n{"schema_version":1,"decisions":[]}\n```',
])
def test_sufficiency_review_rejects_incomplete_or_inconsistent_output(raw):
    with pytest.raises(EvidenceSufficiencyError):
        parse_evidence_sufficiency_review(
            raw, expected_ids=("cat",), reviewer_version="synthetic-gate-v1",
        )
