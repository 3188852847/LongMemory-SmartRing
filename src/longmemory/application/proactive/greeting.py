"""在已获公开播报许可的话题上生成自然问候；不扩大记忆访问范围。"""

import asyncio
from dataclasses import dataclass

from longmemory.application.chat.contracts import AnswerGenerationError


PROMPT_VERSION = "proactive-approved-topic-rewrite-v1"


@dataclass(frozen=True, slots=True)
class GreetingComposition:
    text: str
    outcome: str


class ProactiveGreetingComposer:
    """只改写所有者批准的短句，并用严格格式把失败降级为原文。"""

    def __init__(self, generator, *, timeout_seconds: float = 3.0) -> None:
        self._generator = generator
        self._timeout_seconds = timeout_seconds

    async def compose(self, approved_text: str) -> GreetingComposition:
        query = (
            "把已批准公开播报的短句改成一句自然、温和、不说教的中文问候。"
            "必须逐字完整保留该短句，不得添加任何关于用户的新事实；只输出一行，"
            "总长度不超过80个字符。"
        )
        try:
            value = await asyncio.wait_for(
                asyncio.to_thread(
                    self._generator.generate,
                    query=query,
                    memory_context=f"已批准公开播报短句：{approved_text}",
                ),
                timeout=self._timeout_seconds,
            )
        except (TimeoutError, AnswerGenerationError, OSError):
            return GreetingComposition(approved_text, "model_fallback")
        value = value.strip()
        if (
            not value
            or len(value) > 80
            or any(ord(character) < 32 for character in value)
            or approved_text not in value
        ):
            return GreetingComposition(approved_text, "model_fallback")
        return GreetingComposition(value, "model_generated")
