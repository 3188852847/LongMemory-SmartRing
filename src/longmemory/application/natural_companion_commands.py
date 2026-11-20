"""圆屏可直接表达的高精度陪伴控制命令。"""

from longmemory.methods.contracts import MemoryEvent
from longmemory.application.follow_up_suggestions import (
    parse_follow_up_time_change,
)
from longmemory.application.proactive_frequency import (
    parse_proactive_frequency,
)


_REJECT_TOPIC = frozenset({
    "以后不要主动聊这个话题",
    "不要再主动聊这个话题",
    "别再主动聊这个话题",
})
_CANCEL_FOLLOW_UP = frozenset({
    "取消刚才的跟进",
    "取消刚才的提醒",
    "不用到时候问我了",
    "到时候不用问我了",
})


def recognizes_companion_command(event: MemoryEvent) -> bool:
    normalized = event.content.strip().rstrip("。！？!? ")
    return event.role == "user" and (
        normalized in (_REJECT_TOPIC | _CANCEL_FOLLOW_UP)
        or parse_follow_up_time_change(normalized) is not None
        or parse_proactive_frequency(normalized) is not None
    )
