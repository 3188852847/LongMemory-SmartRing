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

    if result.reused_memories:
        lines.append(
            f"本轮复用了 {len(result.reused_memories)} 条已有记忆。"
        )

    return "\n".join(lines)


def format_memory_details(details: MemoryDetails) -> str:
    """格式化一条记忆及其来源。"""

    memory = details.memory

    if not details.sources:
        source_lines = ["来源：来源证据缺失"]
    else:
        source_lines = []

        for index, source in enumerate(details.sources, start=1):
            if source.source_message is None:
                source_content = "来源消息缺失"
            else:
                source_content = source.source_message.content

            source_lines.append(
                f"来源 {index}（{source.evidence.source_type.value}）："
                f"{source_content}"
            )

    return "\n".join(
        [
            f"记忆 ID：{memory.id}",
            f"主体：{memory.subject_id}",
            f"内容：{memory.content}",
            *source_lines,
            f"记录时间：{memory.recorded_at.isoformat()}",
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
