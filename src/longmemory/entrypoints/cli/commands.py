"""查看、删除、帮助和退出等 CLI 管理命令。"""

from dataclasses import dataclass
from typing import Protocol

from longmemory.application.memory_management.dto import MemoryDetails
from longmemory.core.common.identifiers import MemoryId
from longmemory.entrypoints.cli.presenter import format_memory_list


HELP_TEXT = """可用命令：
  /memories          查看全部长期记忆及其来源
  /delete <记忆ID>   删除指定 L1 记忆
  /help              显示帮助
  /exit              退出程序

不以 / 开头的文本会作为普通聊天消息发送。"""


class CliMemoryApplication(Protocol):
    """CLI 管理命令需要的最小应用能力。"""

    def list_memories(self) -> tuple[MemoryDetails, ...]:
        """列出全部记忆。"""
        ...

    def delete_memory(self, memory_id: MemoryId) -> bool:
        """删除指定记忆。"""
        ...


@dataclass(frozen=True, slots=True)
class CommandResult:
    """一次 CLI 管理命令的处理结果。"""

    handled: bool
    should_exit: bool = False
    output: str | None = None


def execute_command(
    text: str,
    application: CliMemoryApplication,
) -> CommandResult:
    """尝试处理一条斜杠命令。

    非斜杠输入返回 handled=False，交给聊天流程处理。
    """

    stripped_text = text.strip()

    if not stripped_text.startswith("/"):
        return CommandResult(handled=False)

    parts = stripped_text.split(maxsplit=1)
    command_name = parts[0].lower()

    if command_name in {"/exit", "/quit"}:
        return CommandResult(
            handled=True,
            should_exit=True,
            output="已退出 LongMemory。",
        )

    if command_name == "/help":
        return CommandResult(
            handled=True,
            output=HELP_TEXT,
        )

    if command_name == "/memories":
        return CommandResult(
            handled=True,
            output=format_memory_list(
                application.list_memories()
            ),
        )

    if command_name == "/delete":
        if len(parts) != 2 or not parts[1].strip():
            return CommandResult(
                handled=True,
                output="用法：/delete <记忆ID>",
            )

        memory_id = MemoryId(parts[1].strip())
        deleted = application.delete_memory(memory_id)

        if deleted:
            output = f"已删除记忆：{memory_id}"
        else:
            output = f"没有找到记忆：{memory_id}"

        return CommandResult(
            handled=True,
            output=output,
        )

    return CommandResult(
        handled=True,
        output=(
            f"未知命令：{command_name}\n"
            "输入 /help 查看可用命令。"
        ),
    )