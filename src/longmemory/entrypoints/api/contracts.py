"""HTTP 边界的数据契约。

这里只描述外部输入，不进入 Memory Core。路由负责把验证失败映射回已有错误码，
避免 Pydantic 的内部错误细节和框架默认状态码成为公开 API 的偶然契约。
"""

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
