from uuid import uuid4

import pytest
pytest.importorskip("pydantic", reason="网页契约测试需要 uv sync --extra console")
from pydantic import ValidationError

from longmemory.entrypoints.api.contracts import ChatMessageRequest, ExplicitMemoryRequest


def test_chat_message_contract_normalizes_only_surrounding_whitespace():
    request_id = str(uuid4())
    value = ChatMessageRequest.model_validate({"text": "  合成消息  ", "request_id": request_id})
    assert value.text == "合成消息"
    assert value.request_id == request_id


@pytest.mark.parametrize("body", [
    {"text": "", "request_id": str(uuid4())},
    {"text": " " * 10, "request_id": str(uuid4())},
    {"text": "字" * 1001, "request_id": str(uuid4())},
    {"text": 1, "request_id": str(uuid4())},
    {"text": "消息", "request_id": uuid4()},
    {"text": "消息", "request_id": str(uuid4()).upper()},
    {"text": "消息", "request_id": str(uuid4()), "extra": True},
    {"text": "消息"},
    ["消息", str(uuid4())],
])
def test_chat_message_contract_rejects_old_invalid_shapes(body):
    with pytest.raises(ValidationError):
        ChatMessageRequest.model_validate(body)


def test_explicit_memory_contract_accepts_only_self_statements():
    assert ExplicitMemoryRequest.model_validate({"content": "  我的猫叫豆包。  "}).content == "我的猫叫豆包。"
    for body in ({"content": "豆包"}, {"content": "用户喜欢茶。"}, {"content": "你喜欢什么？"}, {"content": "我\n喜欢茶"},
                 {"content": "我喜欢茶", "extra": True}, {"content": 1}):
        with pytest.raises(ValidationError):
            ExplicitMemoryRequest.model_validate(body)
