"""主动交流频率的高精度自然语言解析；不调用模型猜测。"""

import re


_NUMBER = r"(?:[0-9]{1,4}|[零〇一二两三四五六七八九十百千两]{1,6})"
_PATTERN = re.compile(
    rf"^(?:请)?(?:把)?(?:主动交流|主动联系|定时问候)(?:的)?(?:频率)?"
    rf"(?:改成|改为|设成|设为|调整为)?每(?P<number>{_NUMBER})"
    rf"(?P<unit>分钟|小时)一次$"
)


def _number(value: str) -> int:
    if value.isdigit():
        return int(value)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
              "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000}
    total = current = 0
    for character in value:
        if character in digits:
            current = digits[character]
        elif character in units:
            total += (current or 1) * units[character]
            current = 0
        else:
            raise ValueError("proactive_frequency_number_invalid")
    return total + current


def parse_proactive_frequency(text: str) -> int | None:
    """返回 60～86400 秒；越界或含糊表达不识别为控制命令。"""

    normalized = text.strip().rstrip("。！？!? ").replace(" ", "")
    match = _PATTERN.fullmatch(normalized)
    if match is None:
        return None
    value = _number(match.group("number"))
    seconds = value * (60 if match.group("unit") == "分钟" else 3600)
    return seconds if 60 <= seconds <= 24 * 60 * 60 else None


def frequency_text(seconds: int) -> str:
    return (
        f"{seconds // 3600}小时"
        if seconds % 3600 == 0
        else f"{seconds // 60}分钟"
    )
