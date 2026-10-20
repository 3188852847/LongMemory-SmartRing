"""圆屏下一轮封闭分支预测的影子观察器。

第一版只判断助手是否提出可以用“肯定/否定”回答的封闭问题，并观察用户下一句
是否真的落入其中。它不保存正文、不调用模型、不合成或播放音频，也不执行操作。
"""

import re
import threading


_CLOSED_QUESTION = re.compile(
    r"(?:要不要|是否|是不是|可不可以|可以.{0,12}吗|行.{0,12}吗|"
    r"好不好|好吗|愿意.{0,12}吗|需要.{0,12}吗|想.{0,12}吗|确定.{0,12}吗)"
    r"[^。！？!?]{0,24}[？?]\s*$"
)
_AFFIRMATIVE = frozenset({
    "好", "好的", "好啊", "可以", "行", "是", "是的", "嗯", "嗯嗯",
    "要", "愿意", "需要", "没问题", "确定",
})
_NEGATIVE = frozenset({
    "不", "不用", "不用了", "不要", "不了", "算了", "不行", "不是",
    "不需要", "不愿意", "取消",
})


def _normalized(text):
    if not isinstance(text, str):
        return ""
    return re.sub(r"[\s，。！？!?、,.]+", "", text).casefold()


def closed_question(text):
    """只接受回答末尾有明确封闭问式的助手文本。"""
    return isinstance(text, str) and _CLOSED_QUESTION.search(text.strip()) is not None


def reply_branch(text):
    """严格识别完整的肯定或否定短答；带新问题的长句不会命中。"""
    value = _normalized(text)
    if value in _AFFIRMATIVE:
        return "affirmative"
    if value in _NEGATIVE:
        return "negative"
    return None


class VoicePredictionShadow:
    """进程内聚合统计；只保留计数和有限枚举，不保留对话内容。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = False
        self._opportunities = 0
        self._evaluated = 0
        self._hits = 0
        self._misses = 0
        self._last_result = "none"

    def observe_user(self, text):
        with self._lock:
            if not self._pending:
                return None
            self._pending = False
            self._evaluated += 1
            branch = reply_branch(text)
            if branch is None:
                self._misses += 1
                self._last_result = "miss"
                return None
            self._hits += 1
            self._last_result = f"hit_{branch}"
            return branch

    def observe_assistant(self, text):
        if not closed_question(text):
            return False
        with self._lock:
            self._pending = True
            self._opportunities += 1
            self._last_result = "pending"
        return True

    def snapshot(self):
        with self._lock:
            return {
                "version": 1,
                "state": "candidate_waiting" if self._pending else "observing",
                "opportunities": self._opportunities,
                "evaluated": self._evaluated,
                "hits": self._hits,
                "misses": self._misses,
                "last_result": self._last_result,
            }


def install_voice_prediction_shadow(connection_class):
    """逐连接观察相邻话轮，不能把另一连接的封闭问题当成本连接候选。"""
    if getattr(connection_class, "_longmemory_voice_prediction_installed", False):
        return
    original = connection_class.chat

    def chat(connection, query, depth=0):
        # 必须只读实例字典；类上的旧值不能作为逐连接状态容器。
        state = vars(connection).get("_longmemory_voice_prediction_shadow")
        if state is None:
            state = VoicePredictionShadow()
            connection._longmemory_voice_prediction_shadow = state
        if depth == 0:
            state.observe_user(query)
        before = len(connection.dialogue.dialogue)
        result = original(connection, query, depth)
        if depth == 0:
            answers = [
                item.content for item in connection.dialogue.dialogue[before:]
                if getattr(item, "role", None) == "assistant"
                and isinstance(getattr(item, "content", None), str)
                and item.content.strip()
            ]
            if answers:
                state.observe_assistant("\n".join(answers))
        return result

    connection_class.chat = chat
    connection_class._longmemory_voice_prediction_installed = True

