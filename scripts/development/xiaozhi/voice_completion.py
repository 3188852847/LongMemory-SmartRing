"""将提交时的不可变撤权证据带到聊天线程，保护普通回答的历史和完成回执。"""

from contextvars import Context, ContextVar, copy_context
from contextlib import contextmanager

_TURN = ContextVar("voice_completion_output_lease", default=None)


@contextmanager
def completion_guard(lease):
    """只覆盖pending原子领取；调用者必须把RPC留在此上下文之外。"""
    with lease.state.lock:
        yield lease.current()


def output_lease(connection):
    captured = _TURN.get()
    if captured is not None and captured[0] is connection:
        return captured[1]
    return _fresh_lease(connection)


def _fresh_lease(connection):
    if getattr(connection, "_longmemory_audio_revocation_installed", False) is not True:
        return None
    from voice_interruption import OutputLease, supported
    # 原生chat在进入后才产生UUID；这里绑定撤权代次，不借用前一轮UUID。
    return OutputLease(connection, None) if supported(connection) else None


class _CompletionExecutor:
    def __init__(self, connection, original):
        self._completion_connection, self.original = connection, original

    def __getattr__(self, name):
        return getattr(self.original, name)

    def submit(self, function, *args, **kwargs):
        wrapped = isinstance(getattr(function, "__self__", None), Context) and function.__name__ == "run"
        chat, values = (args[0], args[1:]) if wrapped and args else (function, args)
        if getattr(chat, "__self__", None) is self._completion_connection and getattr(chat, "__name__", None) == "chat":
            context = function.__self__.copy() if wrapped else copy_context()
            context.run(_TURN.set, (self._completion_connection, _fresh_lease(self._completion_connection)))
            # 保持Context.run(chat, ...)结构，既有诊断执行器和AE交接代理仍能识别实际chat。
            return self.original.submit(context.run, chat, *values, **kwargs)
        return self.original.submit(function, *args, **kwargs)


def install_completion_handoff(receive_module, asr_base_module):
    def wrap(original):
        if getattr(original, "_longmemory_completion_handoff", False):
            return original
        async def start(connection, text):
            executor = connection.executor
            if getattr(executor, "_completion_connection", None) is not connection:
                connection.executor = _CompletionExecutor(connection, executor)
            return await original(connection, text)
        start._longmemory_completion_handoff = True
        return start
    first, second = receive_module.startToChat, asr_base_module.startToChat
    receive_module.startToChat = wrap(first)
    asr_base_module.startToChat = receive_module.startToChat if first is second else wrap(second)
