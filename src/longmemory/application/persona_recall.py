"""L3 用户画像召回契约；与入口协议和 SQLite 解耦。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PersonaRecallItem:
    persona_id: str
    kind: str
    basis: str
    label: str
    statement: str
    source_refs: tuple[tuple[str, str], ...]
    source_message_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PersonaRecallResult:
    context: str
    items: tuple[PersonaRecallItem, ...]
    strategy: str = "l3_keyword_v1"


class PersonaRecallProvider(Protocol):
    def recall(self, query: str, *, limit: int = 3, max_chars: int = 1200) -> PersonaRecallResult: ...

    def close(self) -> None: ...
