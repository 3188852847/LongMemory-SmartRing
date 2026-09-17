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
    automatic_enabled: bool = False
    scheduled_minute: int = 13 * 60
    greeting_text: str = "下午好，今天过得怎么样？"
    topic_enabled: bool = False
    automatic_interval_seconds: int = 24 * 60 * 60
    dynamic_greeting_enabled: bool = False

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
        if not 0 <= self.scheduled_minute < 24 * 60:
            raise ValueError("proactive_settings_scheduled_minute_invalid")
        if (
            not 60 <= self.automatic_interval_seconds <= 24 * 60 * 60
            or self.automatic_interval_seconds % 60 != 0
        ):
            raise ValueError("proactive_settings_automatic_interval_invalid")
        if (
            self.greeting_text != self.greeting_text.strip()
            or not 1 <= len(self.greeting_text) <= 80
            or any(ord(character) < 32 for character in self.greeting_text)
        ):
            raise ValueError("proactive_settings_greeting_invalid")
        start = self.config.allowed_start_minute
        end = self.config.allowed_end_minute
        inside_window = (
            start <= self.scheduled_minute < end
            if start < end
            else self.scheduled_minute >= start or self.scheduled_minute < end
        )
        if self.automatic_enabled and (
            not self.config.enabled or not inside_window
        ):
            raise ValueError("proactive_settings_automatic_boundary_invalid")
        if self.topic_enabled and not self.automatic_enabled:
            raise ValueError("proactive_settings_topic_boundary_invalid")
        if self.dynamic_greeting_enabled and not self.topic_enabled:
            raise ValueError("proactive_settings_dynamic_greeting_boundary_invalid")
