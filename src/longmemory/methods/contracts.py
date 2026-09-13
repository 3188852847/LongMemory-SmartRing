"""外置显式记忆的最小契约，版本 1。

这里只使用标准库类型，不依赖 AtomicMemory、SQLite 或小智。
这是阶段 A 的基础契约，不承诺任意论文、冻结协议或多用户支持。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol


class UnsupportedCapabilityError(ValueError):
    """拒绝无法忠实执行的操作，而不是静默降级或丢弃元数据。"""


@dataclass(frozen=True, slots=True)
class MethodCapabilities:
    source_trace: bool = False
    session_metadata: bool = False
    feedback_learning: bool = False
    frozen_evaluation: bool = False
    # 日常圆屏入口可先归档 L0，待回答已经进入语音链路后再派生 L1。
    # 只有明确实现两阶段接口的方法才能声明，不能用名字猜测能力。
    deferred_observation: bool = False
    # 允许所有者对已有 L0 的失败/中断提取进行一次显式恢复。该能力不表示
    # 可以重跑正常 NOOP，更不表示后台会自动重试模型请求。
    failed_observation_recovery: bool = False


@dataclass(frozen=True, slots=True)
class MemoryEvent:
    """协议允许交给方法的原始消息；不包含测试答案或评分标签。"""

    event_id: str
    role: Literal["user", "assistant"]
    content: str
    occurred_at: datetime
    session_id: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.content.strip():
            raise ValueError("消息 ID 和正文不能为空。")
        if self.role not in ("user", "assistant"):
            raise ValueError("当前消息契约仅支持 user/assistant。")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("历史时间必须包含时区，不能猜测本地时区。")
        if self.session_id is not None and not self.session_id.strip():
            raise ValueError("提供会话 ID 时不得为空。")


@dataclass(frozen=True, slots=True)
class WriteTrace:
    """方法自己命名的操作标签，仅供检查，不是跨方法质量分数。"""

    operation: str
    item_id: str
    source_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObservationResult:
    event_id: str
    # None 表示没有内部记录能力；空元组表示有记录但没有记忆操作。
    writes: tuple[WriteTrace, ...] | None = None
    # source_only 表示 L0 已可靠归档，但派生 L1 没有完成。它与正常的
    # “判断为不该记（completed + 空 writes）”不同，调用方必须能看见。
    processing_status: Literal["completed", "source_only"] = "completed"
    warning_code: str | None = None

    def __post_init__(self) -> None:
        if (self.processing_status == "source_only") != (self.warning_code is not None):
            raise ValueError("只有 source_only 结果必须带非空 warning_code。")


@dataclass(frozen=True, slots=True)
class RetrievedTrace:
    item_id: str
    content: str
    source_event_ids: tuple[str, ...] | None = None
    # 三种分数的量纲不同：词项重合数、余弦相似度与 RRF 融合分。
    # None 明确表示当前策略或历史记录没有产生该分数，不能按 0 解释。
    keyword_score: int | None = None
    dense_score: float | None = None
    fused_score: float | None = None
    # 历史事实问答会把已退役、但属于明确事实变化链的 L1 作为附加证据。
    # 该标记防止控制台把旧事实伪装成当前召回结果；普通召回保持 None。
    temporal_role: Literal["historical"] | None = None
    valid_from: str | None = None
    valid_to: str | None = None


@dataclass(frozen=True, slots=True)
class MemorySupport:
    call_id: str
    context: str
    # 不要求每种方法暴露条目，不强迫摘要/图结构伪装成原子事实。
    retrieved: tuple[RetrievedTrace, ...] | None = None
    retrieval_strategy: str | None = None
    warning_code: str | None = None


class MemoryMethod(Protocol):
    name: str
    implementation_version: str
    capabilities: MethodCapabilities

    def observe(self, event: MemoryEvent) -> ObservationResult: ...

    def archive(self, event: MemoryEvent) -> ObservationResult:
        """只归档来源事件，不生成派生长期记忆。"""
        ...

    def wait_until_ready(self) -> None: ...

    def recall(self, query: str) -> MemorySupport: ...

    def close(self) -> None: ...


def require_capability(method: MemoryMethod, capability: str) -> None:
    """协议运行前检查能力；不以调用成功推测方法是否支持冻结或学习。"""
    if capability not in MethodCapabilities.__dataclass_fields__:
        raise ValueError("未知的方法能力名称。")
    if not getattr(method.capabilities, capability):
        raise UnsupportedCapabilityError(f"方法不支持能力：{capability}")
