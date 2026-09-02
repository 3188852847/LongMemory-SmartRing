"""将 L0 输入规范化为可追溯的 L1 原子记忆。"""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from longmemory.core.common.identifiers import MemoryId, MemorySubjectId
from longmemory.core.conversation.models import (
    ConversationMessage,
    MessageRole,
)
from longmemory.core.memory.extraction.policy import RuleBasedMemoryPolicy
from longmemory.core.memory.models import (
    CURRENT_USER_SUBJECT_ID,
    AtomicMemory,
)


def _new_memory_id() -> MemoryId:
    """为正式运行生成全局唯一的记忆 ID。"""

    return MemoryId(str(uuid4()))


def _utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。"""

    return datetime.now(UTC)


class MemoryExtractionService:
    """根据提取策略，把 L0 用户消息转换成 L1 原子记忆。"""

    def __init__(
        self,
        policy: RuleBasedMemoryPolicy | None = None,
        id_factory: Callable[[], MemoryId] = _new_memory_id,
        clock: Callable[[], datetime] = _utc_now,
        subject_id: MemorySubjectId = CURRENT_USER_SUBJECT_ID,
    ) -> None:
        self._policy = (
            policy
            if policy is not None
            else RuleBasedMemoryPolicy()
        )
        self._id_factory = id_factory
        self._clock = clock
        self._subject_id = subject_id

    def extract(
        self,
        message: ConversationMessage,
    ) -> tuple[AtomicMemory, ...]:
        """从用户消息中生成带来源信息的原子记忆。"""

        # 助手也可能使用“我”说话，但不能把助手自己的陈述
        # 错误地保存为用户事实。
        if message.role != MessageRole.USER:
            return ()

        candidate_contents = self._policy.extract_contents(message.content)

        return tuple(
            AtomicMemory(
                id=self._id_factory(),
                subject_id=self._subject_id,
                content=content,
                recorded_at=self._clock(),
            )
            for content in candidate_contents
        )
