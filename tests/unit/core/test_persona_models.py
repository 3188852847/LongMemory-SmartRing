"""L3 用户画像候选必须区分明确声明和系统推断。"""

from datetime import UTC, datetime

import pytest

from longmemory.core.common.identifiers import (
    MemorySubjectId,
    PersonaAuditId,
    PersonaId,
    PersonaReviewId,
)
from longmemory.core.memory.l3_persona import (
    PersonaBasis,
    PersonaGenerationAudit,
    PersonaKind,
    PersonaMemory,
    PersonaReview,
    PersonaReviewDecision,
    PersonaReviewerType,
    PersonaStatus,
)


NOW = datetime(2026, 9, 6, 16, 30, tzinfo=UTC)


def test_user_declared_preference_can_keep_one_direct_source() -> None:
    persona = PersonaMemory(
        id=PersonaId("persona-tea"),
        subject_id=MemorySubjectId("user:self"),
        kind=PersonaKind.PREFERENCE,
        basis=PersonaBasis.USER_DECLARED,
        label="饮品偏好",
        statement="用户明确表示更喜欢茉莉花茶。",
        generated_at=NOW,
        status=PersonaStatus.CANDIDATE,
        generator_name="manual_console",
        generator_version="1",
    )
    audit = PersonaGenerationAudit(
        id=PersonaAuditId("audit-tea"),
        persona_id=persona.id,
        basis=persona.basis,
        generator_name="manual_console",
        generator_version="1",
        generated_at=NOW,
        source_count=1,
        source_message_count=1,
        observation_day_count=1,
    )

    assert persona.basis == PersonaBasis.USER_DECLARED
    assert audit.source_message_count == 1


@pytest.mark.parametrize(
    ("source_count", "message_count", "day_count"),
    ((1, 3, 2), (2, 2, 2), (2, 3, 1)),
)
def test_system_inferred_pattern_requires_repeated_cross_day_evidence(
    source_count: int,
    message_count: int,
    day_count: int,
) -> None:
    with pytest.raises(
        ValueError, match="persona_inference_evidence_threshold_not_met"
    ):
        PersonaGenerationAudit(
            id=PersonaAuditId("audit-habit"),
            persona_id=PersonaId("persona-habit"),
            basis=PersonaBasis.SYSTEM_INFERRED,
            generator_name="synthetic",
            generator_version="1",
            generated_at=NOW,
            source_count=source_count,
            source_message_count=message_count,
            observation_day_count=day_count,
        )


def test_system_inferred_pattern_accepts_minimum_conservative_evidence() -> None:
    audit = PersonaGenerationAudit(
        id=PersonaAuditId("audit-habit"),
        persona_id=PersonaId("persona-habit"),
        basis=PersonaBasis.SYSTEM_INFERRED,
        generator_name="synthetic",
        generator_version="1",
        generated_at=NOW,
        source_count=2,
        source_message_count=3,
        observation_day_count=2,
    )

    assert audit.observation_day_count == 2


def test_policy_review_requires_auditable_acceptance_metadata() -> None:
    review = PersonaReview(
        PersonaReviewId("review-policy"), PersonaId("persona-tea"),
        PersonaReviewDecision.ACCEPTED, NOW, 1, PersonaReviewerType.POLICY,
        "persona-activation-v1", "declared_low_risk",
    )
    assert review.reviewer_type == PersonaReviewerType.POLICY

    with pytest.raises(ValueError, match="persona_policy_review_must_accept"):
        PersonaReview(
            PersonaReviewId("review-reject"), PersonaId("persona-tea"),
            PersonaReviewDecision.REJECTED, NOW, 1, PersonaReviewerType.POLICY,
            "persona-activation-v1", "sensitive_content",
        )
    with pytest.raises(ValueError, match="persona_user_review_policy_metadata_forbidden"):
        PersonaReview(
            PersonaReviewId("review-user"), PersonaId("persona-tea"),
            PersonaReviewDecision.ACCEPTED, NOW, 1, PersonaReviewerType.USER,
            "persona-activation-v1", "declared_low_risk",
        )
