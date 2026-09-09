"""由明确 L1 事实派生的一次性跟进候选。

候选只表达“未来值得再问一次”，不是提醒已经启用，也不会绕过主动联系策略。
候选可由所有者在控制台创建，也可来自时间明确的对话请求；两者都不等于投递许可。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class FollowUpCandidateStatus(StrEnum):
    CANDIDATE = "candidate"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class FollowUpCandidate:
    id: str
    subject_id: str
    source_memory_id: str
    source_content_sha256: str
    prompt_text: str
    follow_up_at: datetime
    status: FollowUpCandidateStatus
    created_at: datetime
    updated_at: datetime
    revision: int = 1
    creation_kind: str = "owner_created"
    source_message_id: str | None = None

    def __post_init__(self) -> None:
        for value, name, maximum in (
            (self.id, "follow_up_id", 120),
            (self.subject_id, "follow_up_subject", 120),
            (self.source_memory_id, "follow_up_source", 128),
            (self.prompt_text, "follow_up_prompt", 160),
        ):
            if value != value.strip() or not value or len(value) > maximum:
                raise ValueError(f"{name}_invalid")
        if any(ord(character) < 32 for character in self.prompt_text):
            raise ValueError("follow_up_prompt_invalid")
        digest = self.source_content_sha256
        if (
            len(digest) != 64
            or digest != digest.lower()
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("follow_up_source_digest_invalid")
        for value, name in (
            (self.follow_up_at, "follow_up_at"),
            (self.created_at, "follow_up_created_at"),
            (self.updated_at, "follow_up_updated_at"),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name}_timezone_required")
        if self.follow_up_at <= self.created_at:
            raise ValueError("follow_up_time_not_future")
        if self.updated_at < self.created_at or self.revision < 1:
            raise ValueError("follow_up_revision_invalid")
        if self.creation_kind not in {"owner_created", "explicit_conversation_request"}:
            raise ValueError("follow_up_creation_kind_invalid")
        if self.source_message_id is not None and (
            not self.source_message_id.strip() or len(self.source_message_id) > 128
        ):
            raise ValueError("follow_up_source_message_invalid")
