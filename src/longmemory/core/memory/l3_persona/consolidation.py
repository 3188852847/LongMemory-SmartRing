"""L3 低频整理的操作契约；这里只描述建议，不执行任何数据库写入。"""

from dataclasses import dataclass
from enum import Enum
import json
from typing import Protocol

from longmemory.core.common.identifiers import PersonaId

from .models import PersonaBasis, PersonaKind, PersonaMemory, PersonaStatus, PersonaSourceLayer
from .proposals import (
    MAX_PROPOSAL_OUTPUT_CHARS,
    PersonaProposal,
    PersonaProposalError,
    parse_persona_proposal,
    PersonaProposalInput,
)


class PersonaConsolidationOperation(str, Enum):
    """整理器只能建议新增、更新或保持不变，不能直接删除或接受画像。"""

    ADD = "ADD"
    UPDATE = "UPDATE"
    NOOP = "NOOP"


@dataclass(frozen=True, slots=True)
class PersonaConsolidationSuggestion:
    operation: PersonaConsolidationOperation
    candidate: PersonaProposal | None
    replaces: tuple[PersonaId, ...]


class PersonaConsolidationProducer(Protocol):
    def propose_consolidation(
        self,
        *,
        basis: PersonaBasis,
        sources: tuple[PersonaProposalInput, ...],
        active_personas: tuple[PersonaMemory, ...],
    ) -> str: ...


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PersonaProposalError("persona_consolidation_duplicate_field")
        result[key] = value
    return result


def parse_persona_consolidation(
    raw: str,
    *,
    basis: PersonaBasis,
    allowed_source_refs: tuple[tuple[PersonaSourceLayer, str], ...],
    active_personas: tuple[PersonaMemory, ...],
) -> PersonaConsolidationSuggestion:
    """解析一次整理建议，并把来源和可取代目标限制在调用方白名单内。

    解析成功仍不表示建议正确，更不会写入数据库。UPDATE 只能指向一条
    当前有效且同类型的画像；真正接受时仍由 V9 revision 检查再次防冲突。
    """

    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_PROPOSAL_OUTPUT_CHARS:
        raise PersonaProposalError("persona_consolidation_output_invalid")
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or set(data) != {
            "schema_version", "operation", "candidate", "replaces",
        }:
            raise ValueError
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError
        operation = PersonaConsolidationOperation(data["operation"])
        replaces_value = data["replaces"]
        if not isinstance(replaces_value, list) or any(
            not isinstance(item, str) or not item for item in replaces_value
        ):
            raise ValueError
        if len(set(replaces_value)) != len(replaces_value):
            raise ValueError

        if operation == PersonaConsolidationOperation.NOOP:
            if data["candidate"] is not None or replaces_value:
                raise ValueError
            return PersonaConsolidationSuggestion(operation, None, ())

        proposal = parse_persona_proposal(
            json.dumps(
                {"schema_version": 1, "candidate": data["candidate"]},
                ensure_ascii=False,
            ),
            basis=basis,
            allowed_source_refs=allowed_source_refs,
        )
        if proposal is None:
            raise ValueError
        if operation == PersonaConsolidationOperation.ADD:
            if replaces_value:
                raise ValueError
            return PersonaConsolidationSuggestion(operation, proposal, ())

        if len(replaces_value) != 1:
            raise ValueError
        active_by_id = {
            str(item.id): item for item in active_personas if item.status == PersonaStatus.ACTIVE
        }
        target = active_by_id.get(replaces_value[0])
        if target is None or target.kind != proposal.kind:
            raise ValueError
        return PersonaConsolidationSuggestion(
            operation, proposal, (PersonaId(replaces_value[0]),),
        )
    except PersonaProposalError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError):
        raise PersonaProposalError("persona_consolidation_schema_invalid") from None
