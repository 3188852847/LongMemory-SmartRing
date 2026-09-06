"""会话消息和长期记忆使用的稳定标识符类型。"""

from typing import NewType


# 虽然底层仍然是字符串，但类型检查器能够区分消息 ID 和记忆 ID，
# 避免以后把两种 ID 错误地传给数据库或业务接口。
MessageId = NewType("MessageId", str)
MemoryId = NewType("MemoryId", str)
MemorySubjectId = NewType("MemorySubjectId", str)
ScenarioId = NewType("ScenarioId", str)
ScenarioAuditId = NewType("ScenarioAuditId", str)
ScenarioReviewId = NewType("ScenarioReviewId", str)
ScenarioLifecycleEventId = NewType("ScenarioLifecycleEventId", str)
