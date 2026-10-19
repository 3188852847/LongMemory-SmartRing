"""新后端的保守自然管理边界；没有忠实适配就明确拒绝。"""

from longmemory.application.natural_memory_commands import (
    NaturalMemoryCommandResult, classify_memory_command,
)
from longmemory.application.follow_up_suggestions import parse_explicit_follow_up
from longmemory.application.natural_companion_commands import NaturalCompanionCommandService


class UnsupportedBackendCommands:
    def __init__(self, method):
        self.method = method

    def handle_memory(self, event, *, write_enabled=True):
        kind = classify_memory_command(event.content)
        if kind is None:
            return None
        self.method.archive(event)
        if kind == "exclude":
            return NaturalMemoryCommandResult(kind, "applied",
                "本轮只保留原始对话，没有交给长期记忆引擎。")
        return NaturalMemoryCommandResult(kind, "unsupported",
            "当前记忆引擎尚不支持这类自然管理命令，本轮只归档原文，没有执行记忆修改。请查看引擎管理能力。")

    def handle_companion(self, event):
        offset = int(event.occurred_at.astimezone().utcoffset().total_seconds() // 60)
        try:
            follow_up = parse_explicit_follow_up(event.content, occurred_at=event.occurred_at,
                                                utc_offset_minutes=offset)
        except ValueError:
            follow_up = None
        if NaturalCompanionCommandService.recognizes(event) or follow_up is not None:
            self.method.archive(event)
            return NaturalMemoryCommandResult("companion", "unsupported",
                "当前引擎尚未接入可追溯的陪伴控制和跟进安排，本轮没有修改设置或安排主动联系。")
        return None

    def close(self):
        pass
