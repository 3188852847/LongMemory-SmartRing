"""控制台应用边界的稳定公开错误。"""


class MemoryAccessError(Exception):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status
