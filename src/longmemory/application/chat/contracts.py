"""聊天应用层使用的外部能力契约。"""

from typing import Protocol


class AnswerGenerationError(RuntimeError):
    """回答服务失败；对外消息不得包含凭据或远程响应正文。"""

    def __init__(self, message: str, *, code: str = "model_request_failed"):
        super().__init__(message)
        # 只允许适配器给应用层一个固定诊断码；供应商正文和凭据不能跨越此边界。
        self.code = code


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
