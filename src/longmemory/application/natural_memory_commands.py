"""圆屏自然语言记忆操作：只执行边界明确且目标唯一的指令。"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import re

from longmemory.application.memory_management.service import MemoryManagementService
from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.conversation.contracts import ConversationStore
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.core.memory.l1_atomic.contracts import MemoryStore
from longmemory.core.memory.retrieval.service import keyword_overlap_score
from longmemory.methods.contracts import MemoryEvent, WriteTrace


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
_EXCLUDE_WITHOUT_CONTENT = frozenset({"这句不要记", "这句话不要记", "这件事不要记", "不要记住这句"})
_CONFIRM_DELETE = frozenset({"确认删除这条记忆", "确认删除", "是的，确认删除", "是的确认删除"})
_CANCEL_DELETE = frozenset({"取消删除", "不要删除了", "算了，不删了", "算了不删了"})


@dataclass(frozen=True, slots=True)
class NaturalMemoryCommandResult:
    """一次自然语言操作的可观察结果；None 表示普通聊天。"""

    kind: str
    status: str
    notice: str
    writes: tuple[WriteTrace, ...] = ()
    target_memory_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _PendingDelete:
    memory_id: MemoryId
    content: str
    expires_at: datetime


class NaturalMemoryCommandService:
    """识别少量高精度中文表达，并复用已有 L1 生命周期用例。

    这不是通用自然语言理解器。未命中固定契约的句子继续走普通提取；
    命中但目标不唯一时只归档 L0 并追问，不猜测要修改哪条记忆。
    """

    def __init__(self, *, memory_store: MemoryStore,
                 conversation_store: ConversationStore) -> None:
        self._memory_store = memory_store
        self._conversation_store = conversation_store
        self._management = MemoryManagementService(
            memory_store=memory_store, conversation_store=conversation_store,
        )
        self._pending_delete: _PendingDelete | None = None

    def handle(self, event: MemoryEvent) -> NaturalMemoryCommandResult | None:
        if event.role != "user":
            return None
        text = event.content.strip()
        normalized = text.rstrip("。！？!? ")

        if normalized in _CANCEL_DELETE and self._pending_delete is not None:
            self._archive(event)
            self._pending_delete = None
            return NaturalMemoryCommandResult("delete", "cancelled", "已取消删除，没有改动长期记忆。")

        if normalized in _CONFIRM_DELETE:
            return self._confirm_delete(event)

        if normalized in _EXCLUDE_WITHOUT_CONTENT:
            self._archive(event)
            return NaturalMemoryCommandResult(
                "exclude", "content_required",
                "没有改动上一轮已经形成的记忆。请用“不要记住：具体内容”明确指出本轮不生成 L1；"
                "原始对话 L0 仍会保留用于审计。",
            )

        exclusion = _EXCLUDE.fullmatch(text)
        if exclusion:
            self._archive(event)
            return NaturalMemoryCommandResult(
                "exclude", "applied",
                "本轮没有生成 L1 长期事实；原始对话 L0 仍保留用于审计。",
            )

        correction = _CORRECTION.fullmatch(text)
        if correction:
            return self._correct(event, correction.group("old"), correction.group("new"))

        change = _CHANGE.fullmatch(text)
        if change:
            return self._change(event, change.group("old"), change.group("new"))

        deletion = _DELETE.fullmatch(text)
        if deletion:
            return self._request_delete(event, deletion.group("topic"))

        source = _SOURCE.fullmatch(text)
        if source:
            return self._explain_source(event, source.group("topic"))
        return None

    def recognizes(self, event: MemoryEvent) -> bool:
        """在拿 SQLite 写锁前做纯语法判断，普通聊天不进入写事务。"""

        if event.role != "user":
            return False
        text = event.content.strip()
        normalized = text.rstrip("。！？!? ")
        # 删除确认只绑定紧接着的一轮。用户转而谈别的内容时即撤销暂存，
        # 避免稍后一句脱离上下文的“确认删除”误删旧目标。
        if (self._pending_delete is not None
                and normalized not in _CONFIRM_DELETE
                and normalized not in _CANCEL_DELETE):
            self._pending_delete = None
        return (
            normalized in _CONFIRM_DELETE
            or normalized in _EXCLUDE_WITHOUT_CONTENT
            or (normalized in _CANCEL_DELETE and self._pending_delete is not None)
            or _EXCLUDE.fullmatch(text) is not None
            or _CORRECTION.fullmatch(text) is not None
            or _CHANGE.fullmatch(text) is not None
            or _DELETE.fullmatch(text) is not None
            or _SOURCE.fullmatch(text) is not None
        )

    def _correct(self, event: MemoryEvent, old: str, new: str) -> NaturalMemoryCommandResult:
        old, new = old.strip(), new.strip()
        matches = tuple(memory for memory in self._memory_store.list_active()
                        if old.casefold() in memory.content.casefold())
        if len(matches) != 1:
            self._archive(event)
            return self._unresolved("correct", matches)
        target = matches[0]
        corrected = self._replace_once(target.content, old, new)
        source = self._message(event)
        result = self._management.correct_memory(
            target.id, corrected, occurred_at=event.occurred_at, source_message=source,
        )
        self._pending_delete = None
        return NaturalMemoryCommandResult(
            "correct", "applied",
            f"已把旧记忆“{target.content}”纠正为“{result.new_memory.content}”。",
            (WriteTrace("supersede", str(result.new_memory.id), (event.event_id,)),),
            (str(target.id), str(result.new_memory.id)),
        )

    def _change(self, event: MemoryEvent, old: str, new: str) -> NaturalMemoryCommandResult:
        old, new = old.strip(), new.strip()
        matches = tuple(memory for memory in self._memory_store.list_active()
                        if old.casefold() in memory.content.casefold())
        if len(matches) != 1:
            self._archive(event)
            return self._unresolved("change", matches)
        target = matches[0]
        changed_content = "用户" + new.rstrip("。.!！") + "。"
        source = self._message(event)
        result = self._management.record_memory_change(
            target.id, changed_content, effective_at=event.occurred_at,
            occurred_at=event.occurred_at, source_message=source,
        )
        self._pending_delete = None
        return NaturalMemoryCommandResult(
            "change", "applied",
            f"已记录情况变化：过去是“{target.content}”，现在是“{result.new_memory.content}”。",
            (WriteTrace("supersede", str(result.new_memory.id), (event.event_id,)),),
            (str(target.id), str(result.new_memory.id)),
        )

    def _request_delete(self, event: MemoryEvent, topic: str) -> NaturalMemoryCommandResult:
        self._archive(event)
        matches = self._best_matches(topic.strip())
        if len(matches) != 1:
            self._pending_delete = None
            return self._unresolved("delete", matches)
        target = matches[0]
        self._pending_delete = _PendingDelete(
            target.id, target.content, event.occurred_at + timedelta(minutes=2),
        )
        return NaturalMemoryCommandResult(
            "delete", "confirmation_required",
            f"我找到的长期记忆是“{target.content}”。如确实要删除，请紧接着在两分钟内说“确认删除这条记忆”；"
            "这只删除整理后的 L1，原始聊天记录仍会保留。",
            target_memory_ids=(str(target.id),),
        )

    def _confirm_delete(self, event: MemoryEvent) -> NaturalMemoryCommandResult:
        self._archive(event)
        pending = self._pending_delete
        self._pending_delete = None
        if pending is None or event.occurred_at > pending.expires_at:
            return NaturalMemoryCommandResult(
                "delete", "no_pending_confirmation",
                "没有仍在等待确认的删除请求。请先明确说要忘掉哪条记忆。",
            )
        current = self._memory_store.get(pending.memory_id)
        if current is None or current.retired_at is not None or current.content != pending.content:
            return NaturalMemoryCommandResult(
                "delete", "target_changed",
                "待删除的记忆已经发生变化，因此没有执行删除。请重新说明要忘掉的内容。",
                target_memory_ids=(str(pending.memory_id),),
            )
        if not self._management.delete_memory(pending.memory_id):
            raise RuntimeError("natural_memory_delete_race")
        return NaturalMemoryCommandResult(
            "delete", "applied", f"已删除长期记忆“{pending.content}”；原始聊天记录仍保留。",
            (WriteTrace("delete", str(pending.memory_id), (event.event_id,)),),
            (str(pending.memory_id),),
        )

    def _explain_source(self, event: MemoryEvent, topic: str) -> NaturalMemoryCommandResult:
        self._archive(event)
        matches = self._best_matches(topic.strip())
        if len(matches) != 1:
            return self._unresolved("source", matches)
        target = matches[0]
        originals = []
        for evidence in self._memory_store.list_evidence(target.id):
            message = self._conversation_store.get(evidence.source_message_id)
            if message is not None and message.role == MessageRole.USER:
                originals.append(message.content)
        if not originals:
            notice = f"这条记忆是“{target.content}”，但它的原始来源当前无法读取。"
        else:
            quoted = "；".join(f"“{item}”" for item in originals[:3])
            notice = f"因为你之前说过{quoted}，系统才形成了长期记忆“{target.content}”。"
        return NaturalMemoryCommandResult(
            "source", "explained", notice, target_memory_ids=(str(target.id),),
        )

    def _best_matches(self, query: str):
        scored = [(keyword_overlap_score(query, memory.content), memory)
                  for memory in self._memory_store.list_active()]
        scored = [item for item in scored if item[0] > 0]
        if not scored:
            return ()
        best = max(score for score, _memory in scored)
        return tuple(memory for score, memory in scored if score == best)

    @staticmethod
    def _replace_once(content: str, old: str, new: str) -> str:
        match = re.search(re.escape(old), content, flags=re.IGNORECASE)
        if match is None:
            raise RuntimeError("natural_memory_correction_target_changed")
        return content[:match.start()] + new + content[match.end():]

    def _archive(self, event: MemoryEvent) -> None:
        self._conversation_store.save(self._message(event))

    @staticmethod
    def _message(event: MemoryEvent) -> ConversationMessage:
        return ConversationMessage(
            MessageId(event.event_id), MessageRole.USER, event.content, event.occurred_at,
        )

    @staticmethod
    def _unresolved(kind: str, matches) -> NaturalMemoryCommandResult:
        if not matches:
            notice = "没有找到能唯一对应的当前记忆，请把原来的完整内容和新内容一起说清楚。"
            status = "target_not_found"
        else:
            notice = "找到了多条可能相关的记忆，为避免改错，请把要处理的原事实说得更完整。"
            status = "ambiguous"
        return NaturalMemoryCommandResult(
            kind, status, notice,
            target_memory_ids=tuple(str(memory.id) for memory in matches),
        )
