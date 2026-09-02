"""聊天应用层使用的外部能力契约。"""

from typing import Protocol


class AnswerGenerator(Protocol):
    """聊天用例所依赖的回答生成接口。

    应用层只依赖这个接口，不关心回答来自真实 LLM、
    本地模型还是用于自动化测试的确定性实现。
    """

    def generate(
        self,
        *,
        query: str,
        memory_context: str,
    ) -> str:
        """结合当前输入和记忆上下文生成回答。"""
        ...