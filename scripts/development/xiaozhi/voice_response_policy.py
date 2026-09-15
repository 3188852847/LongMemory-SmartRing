"""仅供圆屏回答请求使用的表达策略，不改角色、历史或 Memory Core。"""

import os


STYLE_ENV = "LONGMEMORY_VOICE_RESPONSE_STYLE"
REALTIME_INSTRUCTION = (
    "圆屏实时语音表达规则：先直接回答当前问题，首句通常用8–18个中文字表达一个完整意思，"
    "尽早用自然句号收束；不要先说无信息的寒暄、复述问题或‘让我想想’。"
    "普通问题默认用1–3个简短口语句，先给有用结论，再按需补充。"
    "这只是表达偏好：用户要求详细、复杂问题需要说明，或有固定格式、简短原文等明确要求时，"
    "保留必要内容并遵从要求；不要为凑字数添话。"
    "保留角色语气和个性化含义，不改变已有记忆证据、事实准确性、工具使用及安全规则；"
    "不要为了抢先开口编造结果或省略关键条件。"
)


def prepare_voice_dialogue(dialogue, *, style=None):
    """复制本次请求的消息，再追加口语表达偏好；原会话不会逐轮积累提示。

    规则放入已有 system 消息，避免在用户问题之后伪造一条用户消息。
    不调整 token 上限或截断模型输出，因此详细问题仍可完整回答。
    original 是回退开关，返回原来的请求，沿用之前的提供器行为。
    """
    selected = os.environ.get(STYLE_ENV, "realtime") if style is None else style
    if str(selected).strip().lower() == "original":
        return dialogue
    if not isinstance(dialogue, (list, tuple)):
        # 非标准提供器输入保留其原来的校验，不猜测其消息结构。
        return dialogue

    # 上游 normalize_dialogue 会补写顶层 content；复制每条字典也保护这一步，
    # 嵌套的工具参数与多模态内容保持原样，不重新解释或移动记忆证据。
    messages = [dict(item) if isinstance(item, dict) else item for item in dialogue]
    for message in messages:
        if (isinstance(message, dict) and message.get("role") == "system"
                and isinstance(message.get("content"), str)):
            content = message["content"]
            if not content.endswith(REALTIME_INSTRUCTION):
                message["content"] = content + "\n\n" + REALTIME_INSTRUCTION
            return messages
    messages.insert(0, {"role": "system", "content": REALTIME_INSTRUCTION})
    return messages
