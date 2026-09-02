"""中文文本基线规则；不是通用的语义或意图分类器。"""

import re


_QUESTION_WORDS = re.compile(r"什么|怎么|怎样|如何|为何|为什么|哪里|哪儿|哪个|哪些|哪种|多少|几岁|几点|几月|几号|何时|谁|是否")
_YES_NO = re.compile(r"是不是|有没有|能不能|可不可以|要不要|会不会|对不对|好不好")
_DECLARATIVE_PREFIX = re.compile(r"^我(?:也|还|已经)?(?:不知道|不清楚|知道|记得|不记得|忘了|忘记了)")
_FREE_CHOICE = re.compile(r"^我(?:什么|哪里|哪儿|谁)(?:都|也)")


def looks_like_question(text: str) -> bool:
    """识别常见有/无问号问句，供提取基线和 Fake 共用。

    混合陈述与提问时暂不提取整段，避免把疑问包装为事实。
    “我不知道猫叫什么”等属于嵌入疑问的陈述，不仅因含疑问词就过滤。
    这些例外只在当前分句内生效，不掩盖后面的独立提问。
    """

    if "?" in text or "？" in text:
        return True
    for clause in re.split(r"[，,。.!！;；\n]+", text):
        clause = clause.strip().rstrip("\"'”’ ")
        if not clause:
            continue
        if clause.endswith(("吗", "么", "呢")) and not clause.endswith("什么"):
            return True
        if _DECLARATIVE_PREFIX.match(clause) or _FREE_CHOICE.match(clause):
            continue
        if _QUESTION_WORDS.search(clause) or _YES_NO.search(clause):
            return True
    return False
