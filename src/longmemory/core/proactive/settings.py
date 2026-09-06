"""主动联系的持久设置；与一次候选及其投递事件分离。"""

from dataclasses import dataclass
from datetime import datetime

from .policy import OutreachPolicyConfig


@dataclass(frozen=True, slots=True)
class ProactivePolicySettings:
    subject_id: str
    config: OutreachPolicyConfig
    quiet_until: datetime | None = None
    revision: int = 0
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.subject_id != self.subject_id.strip() or not 1 <= len(self.subject_id) <= 120:
            raise ValueError("proactive_settings_subject_invalid")
        if self.quiet_until is not None and (
            self.quiet_until.tzinfo is None or self.quiet_until.utcoffset() is None
        ):
            raise ValueError("proactive_settings_quiet_until_timezone_required")
        if self.revision < 0 or (self.revision == 0) != (self.updated_at is None):
            raise ValueError("proactive_settings_revision_invalid")
        if self.updated_at is not None and (
            self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None
        ):
            raise ValueError("proactive_settings_updated_at_timezone_required")
