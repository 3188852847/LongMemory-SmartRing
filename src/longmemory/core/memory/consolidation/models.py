"""低频记忆整理的运行账本模型。

这里只记录调度与审计元数据，不复制 L0/L1 正文。L1→L2 与 L2→L3
共用同一套账本，使自动整理可以限流、重启续跑并解释为什么没有运行。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ConsolidationStage(StrEnum):
    L1_TO_L2 = "l1_to_l2"
    L2_TO_L3 = "l2_to_l3"


class ConsolidationTrigger(StrEnum):
    NEW_EVIDENCE = "new_evidence"
    MANUAL = "manual"
    REBUILD = "rebuild"


class ConsolidationRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field}_timezone_required")


@dataclass(frozen=True, slots=True)
class ConsolidationCursor:
    """已成功处理到的来源高水位；时间相同时用 ID 保证稳定顺序。"""

    recorded_at: datetime
    source_id: str

    def __post_init__(self) -> None:
        _require_aware(self.recorded_at, "cursor_recorded_at")
        if not self.source_id.strip():
            raise ValueError("consolidation_cursor_source_required")


@dataclass(frozen=True, slots=True)
class ConsolidationRun:
    """一次运行的可审计状态；只有成功完成的运行可以携带新游标。"""

    id: str
    subject_id: str
    stage: ConsolidationStage
    trigger: ConsolidationTrigger
    status: ConsolidationRunStatus
    started_at: datetime
    source_count: int = 0
    model_call_count: int = 0
    finished_at: datetime | None = None
    outcome_code: str | None = None
    cursor: ConsolidationCursor | None = None
    risk_reviewer_version: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.subject_id.strip():
            raise ValueError("consolidation_run_identity_required")
        _require_aware(self.started_at, "started_at")
        if self.source_count < 0 or self.model_call_count < 0:
            raise ValueError("consolidation_run_count_invalid")
        terminal = self.status != ConsolidationRunStatus.RUNNING
        if terminal != (self.finished_at is not None and self.outcome_code is not None):
            raise ValueError("consolidation_run_terminal_fields_invalid")
        if self.finished_at is not None:
            _require_aware(self.finished_at, "finished_at")
            if self.finished_at < self.started_at:
                raise ValueError("consolidation_run_time_invalid")
        if self.outcome_code is not None and not self.outcome_code.strip():
            raise ValueError("consolidation_run_outcome_invalid")
        if self.risk_reviewer_version is not None:
            version = self.risk_reviewer_version.strip()
            if not version or len(version) > 120:
                raise ValueError("consolidation_risk_reviewer_version_invalid")
        if (self.status == ConsolidationRunStatus.COMPLETED) != (self.cursor is not None):
            raise ValueError("consolidation_completed_cursor_required")
        if self.status == ConsolidationRunStatus.COMPLETED and self.source_count < 1:
            raise ValueError("consolidation_completed_source_required")
