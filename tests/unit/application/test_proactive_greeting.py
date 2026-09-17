import asyncio

from longmemory.application.chat.contracts import AnswerGenerationError
from longmemory.application.proactive.greeting import ProactiveGreetingComposer


class Generator:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    def generate(self, *, query, memory_context):
        assert "不得添加任何关于用户的新事实" in query
        assert memory_context == "已批准公开播报短句：项目准备得怎么样了？"
        if self.error:
            raise self.error
        return self.value


def test_model_rewrite_must_keep_the_approved_phrase_verbatim():
    result = asyncio.run(ProactiveGreetingComposer(Generator(
        "突然想问问你，项目准备得怎么样了？"
    )).compose("项目准备得怎么样了？"))

    assert result.text == "突然想问问你，项目准备得怎么样了？"
    assert result.outcome == "model_generated"


def test_invalid_or_failed_rewrite_falls_back_to_approved_phrase():
    invalid = asyncio.run(ProactiveGreetingComposer(Generator(
        "听说你的项目已经完成了。"
    )).compose("项目准备得怎么样了？"))
    failed = asyncio.run(ProactiveGreetingComposer(Generator(
        error=AnswerGenerationError("失败")
    )).compose("项目准备得怎么样了？"))

    assert invalid.text == failed.text == "项目准备得怎么样了？"
    assert invalid.outcome == failed.outcome == "model_fallback"
