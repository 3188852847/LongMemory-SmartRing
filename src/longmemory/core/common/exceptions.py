"""与数据库、CLI 和模型供应商无关的领域异常。"""


class EmptyMessageError(ValueError):
    """用户提交了空白聊天消息。"""