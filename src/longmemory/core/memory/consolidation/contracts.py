"""低频记忆整理账本的技术中立存储契约。"""

from datetime import datetime
from typing import Protocol

from .models import ConsolidationCursor, ConsolidationRun, ConsolidationStage


class ConsolidationRunStore(Protocol):
    def start(self, run: ConsolidationRun) -> None: ...

    def finish(self, run: ConsolidationRun) -> None: ...

    def latest_cursor(
        self, subject_id: str, stage: ConsolidationStage,
    ) -> ConsolidationCursor | None: ...

    def has_running(self, subject_id: str, stage: ConsolidationStage) -> bool: ...

    def model_calls_since(
        self, subject_id: str, stage: ConsolidationStage, since: datetime,
    ) -> int: ...

    def list_recent(
        self, subject_id: str, stage: ConsolidationStage, *, limit: int = 20,
    ) -> tuple[ConsolidationRun, ...]: ...
