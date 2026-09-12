"""发现需要人工复核的 L1 重复与显式矛盾候选。

这里的分数只是文本启发式相似度，不是事实置信度，也不会触发任何写操作。
候选检测保持为纯函数，方便以后替换成向量模型或论文方法而不侵入存储层。
"""

from dataclasses import dataclass
from itertools import combinations
import unicodedata

from longmemory.core.memory.l1_atomic.models import AtomicMemory


_SUBJECT_PREFIXES = ("用户本人", "此人", "用户")
_TERMINAL_PUNCTUATION = frozenset("。.!！?？;；")
_NEGATION_PAIRS = (
    ("不喜欢", "喜欢"),
    ("不爱", "爱"),
    ("没有养", "养"),
    ("不喝", "喝"),
    ("不吃", "吃"),
)
DETECTOR_VERSION = "l1-quality-heuristic-v1"


@dataclass(frozen=True, slots=True)
class L1QualityCandidate:
    """一对需要人检查的 L1；kind 只陈述检测原因，不替人下结论。"""

    left: AtomicMemory
    right: AtomicMemory
    kind: str
    similarity: float
    reason: str


def canonicalize_l1_for_exact_dedup(text: str) -> str:
    """生成仅供写入时严格去重的保守键。

    这里只折叠不影响事实含义的表层差异：Unicode 形式、主体称呼、
    多余空白和句末标点。内部标点、数字和否定词全部保留，避免把可能
    不同的事实自动合并。
    """

    value = unicodedata.normalize("NFKC", text).casefold().strip()
    for prefix in _SUBJECT_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix):].lstrip()
            break
    value = " ".join(value.split())
    return value.rstrip("".join(_TERMINAL_PUNCTUATION)).rstrip()


def _canonical_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold().strip()
    for prefix in _SUBJECT_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    # 标点、空格和符号不决定两条事实是否是同一种表述；否定词必须保留。
    return "".join(
        character for character in value
        if not unicodedata.category(character).startswith(("P", "S", "Z"))
    )


def _bigrams(value: str) -> frozenset[str]:
    if len(value) < 2:
        return frozenset(value)
    return frozenset(value[index:index + 2] for index in range(len(value) - 1))


def _jaccard(left: str, right: str) -> float:
    left_parts, right_parts = _bigrams(left), _bigrams(right)
    union = left_parts | right_parts
    return len(left_parts & right_parts) / len(union) if union else 1.0


def _explicit_conflict(left: str, right: str) -> tuple[bool, str]:
    """只识别少量明确反义短语；不对时间变化或复杂语义作自动判断。"""

    for negative, positive in _NEGATION_PAIRS:
        left_negative = negative in left
        right_negative = negative in right
        if left_negative == right_negative:
            continue
        negative_text, positive_text = (left, right) if left_negative else (right, left)
        if positive not in positive_text:
            continue
        if negative_text.replace(negative, positive, 1) == positive_text:
            return True, f"检测到明确的“{positive}/{negative}”相反表述"
    return False, ""


def find_l1_quality_candidates(
    memories: tuple[AtomicMemory, ...], *, threshold: float = 0.72,
    maximum_candidates: int = 100,
) -> tuple[L1QualityCandidate, ...]:
    """在调用方提供的当前有效 L1 中进行有界两两检查。"""

    candidates: list[L1QualityCandidate] = []
    for left, right in combinations(memories, 2):
        if left.subject_id != right.subject_id:
            continue
        left_text, right_text = _canonical_text(left.content), _canonical_text(right.content)
        if not left_text or not right_text:
            continue
        conflict, conflict_reason = _explicit_conflict(left_text, right_text)
        similarity = _jaccard(left_text, right_text)
        if conflict:
            kind, reason = "possible_conflict", conflict_reason
        elif left_text == right_text:
            kind, reason = "normalized_duplicate", "忽略主体前缀、空格和标点后文本一致"
        elif min(len(left_text), len(right_text)) >= 6 and similarity >= threshold:
            kind, reason = "lexical_near_duplicate", "字符片段高度重合，需要人工判断是否重复"
        else:
            continue
        candidates.append(L1QualityCandidate(left, right, kind, similarity, reason))

    priority = {"possible_conflict": 0, "normalized_duplicate": 1,
                "lexical_near_duplicate": 2}
    candidates.sort(key=lambda item: (
        priority[item.kind], -item.similarity, str(item.left.id), str(item.right.id),
    ))
    return tuple(candidates[:maximum_candidates])
