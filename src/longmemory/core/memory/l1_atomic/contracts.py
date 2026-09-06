"""L1 原子记忆存储所需的抽象契约。"""

from datetime import datetime
from typing import Protocol

from longmemory.core.common.identifiers import MemoryId, MemorySubjectId
from longmemory.core.memory.l1_atomic.models import AtomicMemory, MemoryEvidence


class MemoryStore(Protocol):
    """核心层要求 L1 持久化实现提供的最小能力。"""

    def save(self, memory: AtomicMemory, evidence: MemoryEvidence) -> None: ...

    def add_evidence(self, evidence: MemoryEvidence) -> bool: ...

    def list_evidence(self, memory_id: MemoryId) -> tuple[MemoryEvidence, ...]: ...

    def get(self, memory_id: MemoryId) -> AtomicMemory | None: ...

    def find_by_content(
        self,
        content: str,
        *,
        subject_id: MemorySubjectId,
    ) -> AtomicMemory | None: ...

    def list_all(self) -> tuple[AtomicMemory, ...]: ...

    def list_active(self) -> tuple[AtomicMemory, ...]: ...

    def delete(self, memory_id: MemoryId) -> bool: ...

    def retire_as_superseded(
        self,
        memory_id: MemoryId,
        *,
        superseded_by_id: MemoryId,
        retired_at: datetime,
        valid_to: datetime | None = None,
    ) -> bool: ...
