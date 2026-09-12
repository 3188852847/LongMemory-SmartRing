"""D1 候选提取边界；尚未接入正式写库或替换 V0.1 规则。

模型只能提交候选内容与原文摘录。来源身份由程序绑定，不能由模型
指定消息 ID、执行 SQL 或更新既有事实。结构/摘录校验不是语义证明。
"""

from dataclasses import dataclass
import json
import re
from typing import Literal, Protocol

from longmemory.core.common.text import looks_like_question
from longmemory.core.conversation.models import ConversationMessage, MessageRole

MAX_SOURCE_CHARS = 16000
MAX_OUTPUT_CHARS = 64000
MAX_CANDIDATES = 8
PREPROCESSOR_VERSION = "user-message-safety-gate-v3"
_TRAILING_RECIPROCAL_QUESTION = re.compile(
    r"^(?P<statement>.+?)[，,。；;]\s*你呢\s*[?？]\s*$",
    re.DOTALL,
)
_META_INSTRUCTION = re.compile(
    r"(?:忽略|无视|绕过).{0,16}(?:系统|提示|要求|规则|指令)"
    r"|(?:输出|返回).{0,12}(?:ADD|NOOP|JSON)"
    r"|保存为(?:一条)?长期记忆",
    re.IGNORECASE | re.DOTALL,
)


class CandidateExtractionError(ValueError):
    """不携带模型原始响应或消息正文的提取失败。"""


class CandidateProducer(Protocol):
    def propose(self, *, source_text: str) -> str:
        """返回严格 JSON；不接收数据库、评价标签或任意历史角色。"""
        ...


@dataclass(frozen=True, slots=True)
class FactCandidate:
    content: str
    source_message_id: str
    source_quote: str
    source_type: Literal["user_stated"] = "user_stated"


@dataclass(frozen=True, slots=True)
class ExtractionProposal:
    operation: Literal["ADD", "NOOP"]
    candidates: tuple[FactCandidate, ...]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CandidateExtractionError("候选 JSON 含重复字段。")
        result[key] = value
    return result


def parse_proposal(raw: str, message: ConversationMessage) -> ExtractionProposal:
    """先验证整批再返回；第二条非法时不能留下第一条已写入的记忆。

    此函数自身完全不写库。后续集成仍需把整批持久化放进一个事务，
    且把模型网络请求放在事务外，不能用这一层冒称已有持久化保证。
    """
    if message.role != MessageRole.USER or not str(message.id).strip():
        raise CandidateExtractionError("候选必须来自明确的用户消息。")
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_OUTPUT_CHARS:
        raise CandidateExtractionError("候选响应为空或超过字符限制。")
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
        if (not isinstance(data, dict) or set(data) != {"schema_version", "operation", "facts"}
                or type(data["schema_version"]) is not int or data["schema_version"] != 1):
            raise ValueError
        operation, facts = data["operation"], data["facts"]
        if not isinstance(facts, list) or len(facts) > MAX_CANDIDATES:
            raise ValueError
        if operation == "NOOP" and not facts:
            return ExtractionProposal("NOOP", ())
        if operation != "ADD" or not facts:
            raise ValueError
        candidates, seen = [], set()
        for fact in facts:
            if not isinstance(fact, dict) or set(fact) != {"content", "quote"}:
                raise ValueError
            content, quote = fact["content"], fact["quote"]
            if (not isinstance(content, str) or not content.strip() or len(content) > 1000
                    or not isinstance(quote, str) or not quote.strip() or len(quote) > 4000
                    or quote not in message.content or content.strip() in seen):
                raise ValueError
            seen.add(content.strip())
            # 原文包含该摘录只证明存在，不证明候选是正确改写；仍需评估。
            candidates.append(FactCandidate(content.strip(), str(message.id), quote))
        return ExtractionProposal("ADD", tuple(candidates))
    except (ValueError, TypeError, KeyError, RecursionError):
        raise CandidateExtractionError("候选格式、操作或来源摘录无效；整批拒绝。") from None


class CandidateExtractionService:
    """可注入离线替身或将来的模型适配器，与存储/回答模型解耦。"""

    def __init__(self, producer: CandidateProducer):
        self._producer = producer

    def extract(self, message: ConversationMessage) -> ExtractionProposal:
        if message.role != MessageRole.USER:
            return ExtractionProposal("NOOP", ())
        if not message.content.strip():
            return ExtractionProposal("NOOP", ())
        if not str(message.id).strip() or len(message.content) > MAX_SOURCE_CHARS:
            raise CandidateExtractionError("用户消息缺少来源 ID 或超过字符限制。")
        # 模型提示已声明正文只是数据，但真实开发集证明模型仍可能服从正文中的
        # 明确元指令。这里先拦截可确定识别的协议操纵语句；普通“请记住，
        # 我的……”不命中。该规则只是有限纵深防护，不冒充通用注入检测器。
        if _META_INSTRUCTION.search(message.content):
            return ExtractionProposal("NOOP", ())
        source_text = message.content
        if looks_like_question(message.content):
            # 只放开非常窄的“用户自述，你呢？”结构。它是日常对话里常见的
            # 互惠追问，但前半句仍是明确自述。其他混合问句继续保守跳过，
            # 避免把“我想知道，你喜欢什么”等疑问片段误存成用户事实。
            reciprocal = _TRAILING_RECIPROCAL_QUESTION.fullmatch(message.content.strip())
            if reciprocal is None or looks_like_question(reciprocal.group("statement")):
                return ExtractionProposal("NOOP", ())
            source_text = reciprocal.group("statement").strip()
        try:
            raw = self._producer.propose(source_text=source_text)
        except Exception:
            # 不自动重试、不静默降级为规则，不向日志传播供应商/用户正文。
            raise CandidateExtractionError("候选生成失败；未产生可写入结果。") from None
        return parse_proposal(raw, message)
