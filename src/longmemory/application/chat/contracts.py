"""聊天应用层使用的外部能力契约。"""


class AnswerGenerationError(RuntimeError):
    """回答服务失败；对外消息不得包含凭据或远程响应正文。"""

    def __init__(self, message: str, *, code: str = "model_request_failed"):
        super().__init__(message)
        # 只允许适配器给应用层一个固定诊断码；供应商正文和凭据不能跨越此边界。
        self.code = code
