"""实验专用生命周期，不把冻结/会话能力错误标到旧日常方法上。"""

from dataclasses import replace
import hashlib
from pathlib import Path

from longmemory.methods.longmemory_v1.method import LongMemoryV1
from longmemory.methods.dialogue_chunks.method import DialogueChunks

METHODS = ("longmemory_v1", "dialogue_chunks_v1")


def open_method(name: str, directory: Path, *, frozen: bool):
    if name not in METHODS:
        raise ValueError("未注册的比较方法。")
    if name == "dialogue_chunks_v1":
        return DialogueChunks(directory / "chunks.json", read_only=frozen)
    return LongMemoryV1(directory / "memory.db", existing_only=frozen, read_only=frozen)


def observe_history(method, event):
    # 基线算法忽略会话分组；完整事件由平台 history.json 保留。明确的
    # 元数据适配不改提取规则，也不冒称原 V3 表已有 session_id 列。
    # 分块方法则实际用会话边界形成不同的记忆结构。
    return method.observe(replace(event, session_id=None) if method.name == "longmemory_v1" else event)


def state_digest(directory: Path):
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("实验状态不允许符号链接。")
        if path.is_file():
            digest.update(path.relative_to(directory).as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()
