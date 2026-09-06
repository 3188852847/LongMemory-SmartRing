"""把可追溯的 L3 原子断言组织成一份用户可见画像。"""

from dataclasses import dataclass
from datetime import datetime

from longmemory.core.common.identifiers import MemorySubjectId
from longmemory.core.memory.l3_persona.models import (
    PersonaKind,
    PersonaMemory,
    PersonaStatus,
)


PERSONA_SECTION_ORDER = (
    PersonaKind.PREFERENCE,
    PersonaKind.HABIT,
    PersonaKind.INTERACTION_STYLE,
    PersonaKind.BEHAVIOR_PATTERN,
)


@dataclass(frozen=True, slots=True)
class PersonaProfileSection:
    """统一画像中的一个栏目；条目仍保留各自身份和来源链。"""

    kind: PersonaKind
    assertions: tuple[PersonaMemory, ...]


@dataclass(frozen=True, slots=True)
class PersonaProfileSnapshot:
    """读取时生成的单用户画像快照，不是新的持久化记忆层。"""

    subject_id: MemorySubjectId
    sections: tuple[PersonaProfileSection, ...]
    updated_at: datetime | None

    @property
    def assertion_count(self) -> int:
        return sum(len(section.assertions) for section in self.sections)


def build_persona_profile(
    subject_id: MemorySubjectId,
    assertions: tuple[PersonaMemory, ...],
) -> PersonaProfileSnapshot:
    """只聚合当前有效断言，避免候选或已失效认识混入正式画像。"""

    for assertion in assertions:
        if assertion.subject_id != subject_id:
            raise ValueError("persona_profile_subject_mismatch")
        if assertion.status != PersonaStatus.ACTIVE:
            raise ValueError("persona_profile_requires_active_assertions")

    ordered = tuple(sorted(
        assertions,
        key=lambda item: (item.generated_at, str(item.id)),
        reverse=True,
    ))
    sections = tuple(
        PersonaProfileSection(kind, tuple(item for item in ordered if item.kind == kind))
        for kind in PERSONA_SECTION_ORDER
        if any(item.kind == kind for item in ordered)
    )
    updated_at = max((item.generated_at for item in ordered), default=None)
    return PersonaProfileSnapshot(subject_id, sections, updated_at)
