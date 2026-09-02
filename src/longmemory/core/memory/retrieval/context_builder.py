"""把检索结果组装为受控、可检查的模型上下文。"""

from collections.abc import Sequence

from longmemory.core.memory.models import AtomicMemory


def build_memory_context(
    memories: Sequence[AtomicMemory],
) -> str:
    """把检索到的记忆转换成可注入模型的文本上下文。

    没有检索结果时返回空字符串，避免给模型注入
    一个只有标题、没有实际内容的伪上下文。
    """

    if not memories:
        return ""

    memory_lines = "\n".join(
        f"- {memory.content}"
        for memory in memories
    )

    return (
        "以下是与当前问题相关的长期记忆：\n"
        f"{memory_lines}"
    )