"""HTTP 边界的数据契约。

这里只描述外部输入，不进入 Memory Core。路由负责把验证失败映射回已有错误码，
避免 Pydantic 的内部错误细节和框架默认状态码成为公开 API 的偶然契约。
"""

from datetime import datetime
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


class ProactivePolicyRequest(BaseModel):
    """完整替换主动联系设置；revision 防止旧页面覆盖新设置。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: int = Field(ge=0)
    enabled: bool
    utc_offset_minutes: int = Field(ge=-720, le=840)
    allowed_weekdays: list[int] = Field(min_length=1, max_length=7)
    allowed_start_minute: int = Field(ge=0, le=1439)
    allowed_end_minute: int = Field(ge=0, le=1439)
    daily_limit: int = Field(ge=1, le=20)
    minimum_interval_seconds: int = Field(ge=0, le=604800)
    maximum_lifetime_seconds: int = Field(ge=5, le=1800)
    quiet_until: datetime | None
    automatic_enabled: bool
    scheduled_minute: int = Field(ge=0, le=1439)
    greeting_text: str = Field(min_length=1, max_length=80)
    topic_enabled: bool

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
