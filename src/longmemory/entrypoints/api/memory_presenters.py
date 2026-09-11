"""记忆管理 API 的只读 JSON 投影。

这里不打开数据库、不执行业务操作，只负责把 L1/L2/L3 领域对象转换成稳定的
网页契约。将展示逻辑从 MemoryBackend 移出，避免管理操作继续和响应格式耦合。
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json


def memory_json(memory):
    now = datetime.now(UTC)
    effective_state = (
        "retired" if memory.retired_at
        else "not_started" if memory.valid_from is not None and memory.valid_from > now
        else "expired" if memory.valid_to is not None and memory.valid_to <= now
        else "current"
    )
    return {
        "id": str(memory.id), "subject_id": str(memory.subject_id), "content": memory.content,
        **{key: getattr(memory, key).isoformat() if getattr(memory, key) else None
           for key in ("recorded_at", "valid_from", "valid_to", "retired_at")},
        "superseded_by_id": str(memory.superseded_by_id) if memory.superseded_by_id else None,
        "state": "retired" if memory.retired_at else "active",
        "effective_state": effective_state,
    }


def details_json(details):
    result = memory_json(details.memory)
    result["sources"] = [{
        "source_message_id": str(source.evidence.source_message_id),
        "source_type": source.evidence.source_type.value,
        "linked_at": source.evidence.linked_at.isoformat(),
        "message": None if source.source_message is None else {
            "role": source.source_message.role.value,
            "content": source.source_message.content,
            "created_at": source.source_message.created_at.isoformat(),
        },
    } for source in details.sources]
    return result


def revision(data):
    """生成删除/纠正前复核摘要；它不是鉴权令牌，也不替代 CSRF。"""
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def scenario_json(row):
    return {key: row[key] for key in (
        "id", "subject_id", "title", "summary", "generated_at", "valid_from",
        "valid_to", "status", "generator_name", "generator_version", "revision",
    )}


def persona_json(row):
    return {key: row[key] for key in (
        "id", "subject_id", "kind", "basis", "label", "statement",
        "generated_at", "valid_from", "valid_to", "status",
        "generator_name", "generator_version", "revision",
    )}


def persona_model_json(persona):
    return {
        "id": str(persona.id), "subject_id": str(persona.subject_id),
        "kind": persona.kind.value, "basis": persona.basis.value,
        "label": persona.label, "statement": persona.statement,
        "generated_at": persona.generated_at.isoformat(),
        "valid_from": persona.valid_from.isoformat() if persona.valid_from else None,
        "valid_to": persona.valid_to.isoformat() if persona.valid_to else None,
        "status": persona.status.value, "generator_name": persona.generator_name,
        "generator_version": persona.generator_version, "revision": persona.revision,
    }


def persona_replacement_json(replacement, related):
    return {
        "candidate_persona_id": str(replacement.candidate_persona_id),
        "replaced_persona_id": str(replacement.replaced_persona_id),
        "target_revision": replacement.target_revision,
        "linked_at": replacement.linked_at.isoformat(),
        "applied_at": replacement.applied_at.isoformat() if replacement.applied_at else None,
        "related": None if related is None else persona_model_json(related),
    }
