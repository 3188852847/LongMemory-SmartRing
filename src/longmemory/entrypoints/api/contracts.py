"""HTTP 边界的数据契约。

这里只描述外部输入，不进入 Memory Core。路由负责把验证失败映射回已有错误码，
避免 Pydantic 的内部错误细节和框架默认状态码成为公开 API 的偶然契约。
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatMessageRequest(BaseModel):
    """一次聊天提交；规范化正文，但保留请求 UUID 的严格规范形式。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=1000)
    request_id: str

    @field_validator("text")
    @classmethod
    def non_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("blank text")
        return value

    @field_validator("request_id")
    @classmethod
    def canonical_uuid(cls, value: str) -> str:
        # 继续沿用旧接口的 canonical UUID 约束，避免迁移悄悄接受新格式。
        if str(UUID(value)) != value:
            raise ValueError("non-canonical UUID")
        return value


class ChatMemoryFeedbackRequest(BaseModel):
    """所有者对某一轮回答的记忆表现复核；不触发记忆或模型操作。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["memory_ok", "recall_miss", "wrong_memory", "memory_irrelevant"]
    expected_revision: int = Field(ge=0, le=32)


class MemoryFeedbackReviewRequest(BaseModel):
    """所有者管理诊断队列；只提交固定动作和原因，不携带对话正文。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    source: Literal["web_chat", "round_screen"]
    target_id: str = Field(min_length=1, max_length=200)
    feedback_revision: int = Field(ge=1, le=32)
    action: Literal["resolve", "dismiss", "reopen"]
    reason_code: Literal[
        "memory_corrected", "retrieval_fixed", "answer_behavior_fixed",
        "false_positive", "not_memory_issue", "other", "needs_follow_up",
    ]
    expected_review_revision: int = Field(ge=0)

    @field_validator("target_id")
    @classmethod
    def clean_target_id(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("invalid target id")
        return value


class SufficiencyShadowReviewRequest(BaseModel):
    """所有者评价一整轮影子门控；不携带问题或场景正文。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    verdict: Literal["correct", "incorrect", "uncertain"]
    reason_code: Literal[
        "agreement", "missed_support", "false_support", "ambiguous_query",
        "stale_content", "other",
    ]
    expected_review_revision: int = Field(ge=0)


def _support_ids_are_unique_and_clean(value: list[str] | None):
    if value is None:
        return value
    if (len(value) != len(set(value))
            or any(not item.strip() or len(item) > 200
                   or any(ord(character) < 32 for character in item)
                   for item in value)):
        raise ValueError("invalid support ids")
    return value


class L2SufficiencyShadowReviewRequest(SufficiencyShadowReviewRequest):
    """L2 复核额外冻结人工认为真正支持回答的场景。"""

    expected_supported_scenario_ids: list[str] | None = Field(
        default=None, max_length=100,
    )

    _validate_support_ids = field_validator(
        "expected_supported_scenario_ids",
    )(_support_ids_are_unique_and_clean)


class L1SufficiencyShadowReviewRequest(SufficiencyShadowReviewRequest):
    """L1 复核额外冻结人工认为真正支持回答的候选集合。"""

    expected_supported_memory_ids: list[str] | None = Field(
        default=None, max_length=100,
    )

    _validate_support_ids = field_validator(
        "expected_supported_memory_ids",
    )(_support_ids_are_unique_and_clean)


class L1ExtractionRetryRequest(BaseModel):
    """重试最新失败尝试；attempt ID 防止旧页面或双击重复调用模型。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_attempt_id: str

    @field_validator("expected_attempt_id")
    @classmethod
    def canonical_attempt_id(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("non-canonical UUID")
        return value


class ExplicitMemoryRequest(BaseModel):
    """控制台手工声明的一条自指事实；仍交由统一记忆命令处理。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    content: str = Field(min_length=1, max_length=1000)

    @field_validator("content")
    @classmethod
    def complete_single_statement(cls, value: str) -> str:
        value = value.strip()
        if (
            not value
            or any(ord(character) < 32 for character in value)
            or not value.startswith("我")
        ):
            raise ValueError("explicit self statement required")
        return value


class ProactivePolicyRequest(BaseModel):
    """完整替换主动联系设置；revision 防止旧页面覆盖新设置。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: int = Field(ge=0)
    enabled: bool
    utc_offset_minutes: int = Field(ge=-720, le=840)
    allowed_weekdays: list[int] = Field(min_length=1, max_length=7)
    allowed_start_minute: int = Field(ge=0, le=1439)
    allowed_end_minute: int = Field(ge=0, le=1439)
    daily_limit: int = Field(ge=1, le=1440)
    minimum_interval_seconds: int = Field(ge=0, le=604800)
    maximum_lifetime_seconds: int = Field(ge=5, le=1800)
    quiet_until: datetime | None
    automatic_enabled: bool
    scheduled_minute: int = Field(ge=0, le=1439)
    greeting_text: str = Field(min_length=1, max_length=80)
    topic_enabled: bool
    # 旧控制台省略字段时由后端保留当前值，避免覆盖语音刚设置的周期。
    automatic_interval_seconds: int | None = Field(
        default=None, ge=60, le=86400, multiple_of=60,
    )

    @field_validator("allowed_weekdays")
    @classmethod
    def weekdays_are_unique(cls, value: list[int]) -> list[int]:
        if any(type(day) is not int or day not in range(7) for day in value) or len(set(value)) != len(value):
            raise ValueError("invalid weekdays")
        return value

    @field_validator("quiet_until", mode="before")
    @classmethod
    def quiet_time_is_aware(cls, value) -> datetime | None:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timezone required")
        return value

    @field_validator("greeting_text")
    @classmethod
    def greeting_is_single_line(cls, value: str) -> str:
        if (
            value != value.strip()
            or not value
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("invalid greeting")
        return value


class ProactiveTestRequest(BaseModel):
    """用户显式点击的一次短文本验证；request_id 防止重复播报。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=80)
    request_id: str
    expected_policy_revision: int = Field(ge=0)

    @field_validator("text")
    @classmethod
    def single_line_text(cls, value: str) -> str:
        if (value != value.strip() or not value
                or any(ord(character) < 32 for character in value)):
            raise ValueError("invalid announcement")
        return value

    @field_validator("request_id")
    @classmethod
    def canonical_request_id(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("non-canonical UUID")
        return value


class ProactiveScheduleOverrideArmRequest(BaseModel):
    """显式授权当前设置对应的下一次开发定时验证。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_policy_revision: int = Field(ge=1)
    confirm_action: bool

    @field_validator("confirm_action")
    @classmethod
    def confirmation_required(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("confirmation required")
        return value


class ProactiveScheduleOverrideCancelRequest(BaseModel):
    """撤销尚未被后台消费的一次性授权。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: int = Field(ge=1)


class ProactivePlaybackConfirmationRequest(BaseModel):
    """所有者确认实际听到，不允许页面用旧 revision 覆盖新状态。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: int = Field(ge=1)


class ProactiveTopicSeedRequest(BaseModel):
    """把明确核对过的安全短句绑定到一个当前 L2 场景。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    scenario_id: str = Field(min_length=1, max_length=128)
    expected_scenario_revision: int = Field(ge=1)
    prompt_text: str = Field(min_length=1, max_length=120)
    request_id: str

    @field_validator("scenario_id", "prompt_text")
    @classmethod
    def clean_single_line(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("invalid text")
        return value

    @field_validator("request_id")
    @classmethod
    def canonical_topic_request_id(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("non-canonical UUID")
        return value


class ProactiveTopicDisableRequest(BaseModel):
    """停用话题素材；revision 防止旧页面覆盖新状态。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: int = Field(ge=1)


class FollowUpCandidateRequest(BaseModel):
    """从当前 L1 建立一次性跟进候选；保存本身不授权投递。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    source_memory_id: str = Field(min_length=1, max_length=128)
    expected_memory_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_text: str = Field(min_length=1, max_length=160)
    follow_up_at: datetime
    request_id: str

    @field_validator("source_memory_id", "prompt_text")
    @classmethod
    def clean_follow_up_text(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("invalid follow-up text")
        return value

    @field_validator("follow_up_at", mode="before")
    @classmethod
    def follow_up_time_is_aware(cls, value) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone required")
        return value

    @field_validator("request_id")
    @classmethod
    def canonical_follow_up_request_id(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("non-canonical UUID")
        return value


class FollowUpCandidateCancelRequest(BaseModel):
    """取消尚未生效的跟进候选。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: int = Field(ge=1)


class FollowUpCandidateArmRequest(BaseModel):
    """把已核对候选转换为未来一次性账本；仍受 P4 总许可约束。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: int = Field(ge=1)
    expected_policy_revision: int = Field(ge=0)


class CompanionStrategyDismissRequest(BaseModel):
    """忽略一个尚未生效的策略候选；不会修改当前主动联系设置。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: int = Field(ge=1)


class CompanionAbsenceVersionDraftRequest(BaseModel):
    """从仍有效的日常时段候选生成不可变离线验证草案。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    candidate_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    expected_candidate_revision: int = Field(ge=1)


class CompanionAbsenceSelectionRequest(BaseModel):
    """显式激活或回滚到一个已通过离线门控的版本。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    version_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    expected_revision: int = Field(ge=0)


class CompanionAbsenceDeactivateRequest(BaseModel):
    """显式停用当前缺席策略，同时保留指针修订历史。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: int = Field(ge=1)
