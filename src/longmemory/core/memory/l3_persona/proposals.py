"""L3 模型草稿的严格预览契约；解析成功也不会写入数据库。"""

from dataclasses import dataclass
import json
from typing import Protocol

from longmemory.core.common.identifiers import MemorySubjectId
from .models import PersonaBasis, PersonaKind, PersonaSourceLayer


MAX_PROPOSAL_OUTPUT_CHARS = 16_000


class PersonaProposalError(ValueError):
    """固定错误边界，不携带模型原始响应或个人记忆正文。"""


@dataclass(frozen=True, slots=True)
class PersonaProposalEvidence:
    message_id: str
    content: str
    observation_day: str


@dataclass(frozen=True, slots=True)
class PersonaProposalInput:
    """一次显式预览允许模型看到的一个 L1/L2 及其用户 L0。"""

    source_layer: PersonaSourceLayer
    source_id: str
    subject_id: MemorySubjectId
    content: str
    user_evidence: tuple[PersonaProposalEvidence, ...]


@dataclass(frozen=True, slots=True)
class PersonaProposal:
    kind: PersonaKind
    basis: PersonaBasis
    label: str
    statement: str
    source_refs: tuple[tuple[PersonaSourceLayer, str], ...]


class PersonaProposalProducer(Protocol):
    def propose(
        self, *, basis: PersonaBasis, sources: tuple[PersonaProposalInput, ...],
    ) -> str: ...


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PersonaProposalError("persona_proposal_duplicate_field")
        result[key] = value
    return result


def parse_persona_proposal(
    raw: str, *, basis: PersonaBasis,
    allowed_source_refs: tuple[tuple[PersonaSourceLayer, str], ...],
) -> PersonaProposal | None:
    """只接受一个候选，且模型只能引用本次明确发送的来源。"""

    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_PROPOSAL_OUTPUT_CHARS:
        raise PersonaProposalError("persona_proposal_output_invalid")
    allowed = {(layer.value, source_id) for layer, source_id in allowed_source_refs}
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or set(data) != {"schema_version", "candidate"}:
            raise ValueError
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError
        candidate = data["candidate"]
        if candidate is None:
            return None
        if not isinstance(candidate, dict) or set(candidate) != {
            "kind", "label", "statement", "sources",
        }:
            raise ValueError
        label, statement, source_values = (
            candidate["label"], candidate["statement"], candidate["sources"]
        )
        kind = PersonaKind(candidate["kind"])
        if (not isinstance(label, str) or not 1 <= len(label.strip()) <= 120
                or not isinstance(statement, str) or not 1 <= len(statement.strip()) <= 1000
                or not isinstance(source_values, list) or not 1 <= len(source_values) <= 20):
            raise ValueError
        refs = []
        for item in source_values:
            if (not isinstance(item, dict) or set(item) != {"layer", "id"}
                    or not isinstance(item["layer"], str)
                    or not isinstance(item["id"], str)):
                raise ValueError
            ref = (item["layer"], item["id"])
            if ref not in allowed:
                raise ValueError
            refs.append((PersonaSourceLayer(item["layer"]), item["id"]))
        if len(set(refs)) != len(refs):
            raise ValueError
        return PersonaProposal(kind, basis, label.strip(), statement.strip(), tuple(refs))
    except (ValueError, TypeError, KeyError, RecursionError):
        raise PersonaProposalError("persona_proposal_schema_invalid") from None
