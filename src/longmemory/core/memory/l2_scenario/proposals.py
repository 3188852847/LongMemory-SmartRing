"""L2 模型候选的严格预览契约；解析成功也不代表已经写入数据库。"""

from dataclasses import dataclass
import json
from typing import Protocol

from longmemory.core.common.identifiers import MemoryId, MemorySubjectId


MAX_PROPOSAL_OUTPUT_CHARS = 16_000


class ScenarioProposalError(ValueError):
    """不携带模型原始响应或个人记忆正文的固定失败边界。"""


@dataclass(frozen=True, slots=True)
class ScenarioProposalInput:
    """一次显式预览允许模型看到的最小 L1 集合。"""

    memory_id: MemoryId
    subject_id: MemorySubjectId
    content: str
    source_message_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScenarioProposal:
    title: str
    summary: str
    source_memory_ids: tuple[MemoryId, ...]


class ScenarioProposalProducer(Protocol):
    def propose(self, *, sources: tuple[ScenarioProposalInput, ...]) -> str: ...


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ScenarioProposalError("scenario_proposal_duplicate_field")
        result[key] = value
    return result


def parse_scenario_proposal(
    raw: str,
    *,
    allowed_source_ids: tuple[MemoryId, ...],
) -> ScenarioProposal | None:
    """只接受一个候选，并禁止模型引用未发送给它的 L1。"""

    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_PROPOSAL_OUTPUT_CHARS:
        raise ScenarioProposalError("scenario_proposal_output_invalid")
    allowed = {str(value) for value in allowed_source_ids}
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or set(data) != {"schema_version", "candidate"}:
            raise ValueError
        version = data["schema_version"]
        if type(version) is not int or version not in {1, 2}:
            raise ValueError
        candidate = data["candidate"]
        # V2 允许模型明确表示当前输入没有可靠场景。V1 保持兼容，
        # 但不能用 null 绕过旧契约。
        if candidate is None:
            if version != 2:
                raise ValueError
            return None
        if not isinstance(candidate, dict) or set(candidate) != {
            "title", "summary", "source_memory_ids"
        }:
            raise ValueError
        title, summary, ids = candidate["title"], candidate["summary"], candidate["source_memory_ids"]
        if (not isinstance(title, str) or not 1 <= len(title.strip()) <= 120
                or not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 2000
                or not isinstance(ids, list) or not 2 <= len(ids) <= 20
                or any(not isinstance(value, str) or value not in allowed for value in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError
        return ScenarioProposal(
            title.strip(), summary.strip(), tuple(MemoryId(value) for value in ids)
        )
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ScenarioProposalError("scenario_proposal_schema_invalid") from None
