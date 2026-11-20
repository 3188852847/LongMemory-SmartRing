"""圆屏自然语言记忆操作：只执行边界明确且目标唯一的指令。"""

from dataclasses import dataclass
import re
from longmemory.methods.contracts import WriteTrace


_CORRECTION = re.compile(
    r"^(?:(?:不对|更正一下|我说错了|之前说错了)[，,：:\s]*)?"
    r"不是(?P<old>[^，,。！？!?]{1,60})[，,\s]*(?:而是|应该是|是)"
    r"(?P<new>[^。！？!?]{1,120})[。！？!?]*$"
)
_CHANGE = re.compile(
    r"^我(?:以前|之前)(?P<old>[^，,。！？!?]{1,100})[，,\s]*"
    r"(?:但|不过|可是)?现在(?:我)?(?P<new>[^。！？!?]{1,120})[。！？!?]*$"
)
_DELETE = re.compile(
    r"^(?:请)?(?:忘掉|删除|删掉|别再记得|不要再记得)(?:关于)?"
    r"(?P<topic>[^。！？!?]{1,120})[。！？!?]*$"
)
_SOURCE = re.compile(
    r"^(?:你)?(?:为什么|怎么)(?:会)?(?:知道|记得)(?P<topic>[^。！？!?]{1,160})[？?。！!]*$"
)
_EXCLUDE = re.compile(
    r"^(?:请)?(?:不要|别)(?:长期)?记(?:住|录)?[：:\s]+"
    r"(?P<content>[^。！？!?].{0,998})[。！？!?]*$"
)
_INCLUDE = re.compile(
    r"^(?:请)?记住[：:\s]+(?P<content>.{1,1000})$"
)
_EXCLUDE_WITHOUT_CONTENT = frozenset({"这句不要记", "这句话不要记", "这件事不要记", "不要记住这句"})
_CONFIRM_DELETE = frozenset({"确认删除这条记忆", "确认删除", "是的，确认删除", "是的确认删除"})
_CANCEL_DELETE = frozenset({"取消删除", "不要删除了", "算了，不删了", "算了不删了"})


def classify_memory_command(text: str) -> str | None:
    """只识别既有严格语法，供不支持旧自然管理的新后端明确拒绝。"""
    text = text.strip()
    normalized = text.rstrip("。！？!? ")
    if normalized in _CONFIRM_DELETE or normalized in _CANCEL_DELETE:
        return "delete"
    if normalized in _EXCLUDE_WITHOUT_CONTENT or _EXCLUDE.fullmatch(text):
        return "exclude"
    for kind, pattern in (("include", _INCLUDE), ("correct", _CORRECTION),
                          ("change", _CHANGE), ("delete", _DELETE), ("source", _SOURCE)):
        if pattern.fullmatch(text):
            return kind
    return None


@dataclass(frozen=True, slots=True)
class NaturalMemoryCommandResult:
    """一次自然语言操作的可观察结果；None 表示普通聊天。"""

    kind: str
    status: str
    notice: str
    writes: tuple[WriteTrace, ...] = ()
    target_memory_ids: tuple[str, ...] = ()
