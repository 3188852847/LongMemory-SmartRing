"""合成评估的可追溯词面初筛；不能替代人工语义判定。"""

import re


SCORER_VERSION = "lexical-v2"
_REFUSAL_PATTERNS = (
    r"不知道|不清楚|不确定|无法(?:确定|确认|回答)|不能确定",
    r"没有(?:找到|相关|提供|记录)|未(?:提供|记录)",
    # 限制在同一分句中匹配，避免将不同句子的“没有”和“信息”硬连起来。
    r"没有关于[^。！？!?；;\n]{0,80}(?:信息|记忆|记录)",
    r"(?:缺少|缺乏)[^。！？!?；;\n]{0,40}(?:信息|证据)",
)


def check_answer(answer: str, *, abstain: bool, answer_contains: str | None) -> dict:
    """两组共用真值。返回初筛原因，并显式保留人工复核要求。

    没有匹配到拒答措辞，不等于模型一定编造；匹配到了，也不能排除
    “先说不知道、后面又猜测”的混合回答。报告不得当作语义裁判。
    """

    refusal = any(re.search(pattern, answer) for pattern in _REFUSAL_PATTERNS)
    if abstain:
        passed = refusal
        reason = "refusal_phrase_matched" if passed else "no_refusal_phrase_matched"
    else:
        passed = bool(answer_contains) and answer_contains in answer and not refusal
        reason = "expected_text_without_refusal" if passed else "missing_expected_text_or_refusal"
    return {
        "answer_check_pass": passed,
        "answer_check_reason": reason,
        "answer_check_requires_review": True,
    }
