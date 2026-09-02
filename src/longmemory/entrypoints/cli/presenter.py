"""将领域和应用结果转换为易读的终端输出。"""

from collections.abc import Sequence

from longmemory.application.chat.dto import ChatResult
from longmemory.application.memory_management.dto import MemoryDetails


def format_chat_result(result: ChatResult) -> str:
    """格式化一轮聊天结果。"""

    lines = [f"助手：{result.answer}"]

    if result.saved_memories:
        lines.append(
            f"本轮保存了 {len(result.saved_memories)} 条长期记忆。"
        )

    return "\n".join(lines)


def format_memory_details(details: MemoryDetails) -> str:
    """格式化一条记忆及其来源。"""

    memory = details.memory

    if details.source_message is None:
        source_content = "来源消息缺失"
    else:
        source_content = details.source_message.content

    return "\n".join(
        [
            f"记忆 ID：{memory.id}",
            f"内容：{memory.content}",
            f"来源：{source_content}",
            f"创建时间：{memory.created_at.isoformat()}",
        ]
    )


def format_memory_list(
    memories: Sequence[MemoryDetails],
) -> str:
    """格式化记忆列表。"""

    if not memories:
        return "当前没有保存的长期记忆。"

    return "\n\n".join(
        format_memory_details(details)
        for details in memories
    )