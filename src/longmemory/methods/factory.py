"""显式白名单装配；只注册已实现的方法，不动态加载任意代码。"""

from pathlib import Path

from longmemory.methods.contracts import MemoryMethod
from longmemory.methods.longmemory_v1.method import LongMemoryV1
from longmemory.methods.dialogue_chunks.method import DialogueChunks


def create_method(*, name: str, state_path: Path) -> MemoryMethod:
    # 先验证方法名，再接触状态目录；拼错名称不能导致创建或迁移数据库。
    if name == "longmemory_v1":
        return LongMemoryV1(state_path)
    if name == "dialogue_chunks_v1":
        return DialogueChunks(state_path)
    raise ValueError("未知或尚未实现的记忆方法。")
