from datetime import UTC, datetime, timedelta

import pytest

from longmemory.application.persona_management.profile import build_persona_profile
from longmemory.core.common.identifiers import MemorySubjectId, PersonaId
from longmemory.core.memory.l3_persona.models import (
    PersonaBasis,
    PersonaKind,
    PersonaMemory,
    PersonaStatus,
)


def assertion(
    identifier: str,
    kind: PersonaKind,
    *,
    status: PersonaStatus = PersonaStatus.ACTIVE,
    minute: int = 0,
) -> PersonaMemory:
    return PersonaMemory(
        PersonaId(identifier), MemorySubjectId("user:self"), kind,
        PersonaBasis.USER_DECLARED, identifier, f"{identifier} 的内容",
        datetime(2026, 9, 6, 10, minute, tzinfo=UTC), status,
        "synthetic", "1",
    )


def test_profile_groups_active_assertions_without_collapsing_identity():
    profile = build_persona_profile(MemorySubjectId("user:self"), (
        assertion("tea", PersonaKind.PREFERENCE),
        assertion("listen", PersonaKind.INTERACTION_STYLE, minute=1),
        assertion("quiet", PersonaKind.PREFERENCE, minute=2),
    ))

    assert profile.assertion_count == 3
    assert profile.updated_at == datetime(2026, 9, 6, 10, 2, tzinfo=UTC)
    assert [section.kind for section in profile.sections] == [
        PersonaKind.PREFERENCE, PersonaKind.INTERACTION_STYLE,
    ]
    assert [str(item.id) for item in profile.sections[0].assertions] == ["quiet", "tea"]


@pytest.mark.parametrize("invalid", [
    assertion("candidate", PersonaKind.HABIT, status=PersonaStatus.CANDIDATE),
    PersonaMemory(
        PersonaId("other"), MemorySubjectId("user:other"), PersonaKind.HABIT,
        PersonaBasis.USER_DECLARED, "other", "other 的内容",
        datetime(2026, 9, 6, tzinfo=UTC) + timedelta(minutes=1),
        PersonaStatus.ACTIVE, "synthetic", "1",
    ),
])
def test_profile_rejects_non_current_or_other_subject_assertions(invalid):
    with pytest.raises(ValueError):
        build_persona_profile(MemorySubjectId("user:self"), (invalid,))
