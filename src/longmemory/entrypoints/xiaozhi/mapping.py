"""将小智普通文字或 ASR JSON 封装转为用户陈述，不信任附带情绪/身份。"""

import json


def extract_user_text(query: str) -> str:
    if not isinstance(query, str) or not query.strip() or len(query) > 16000:
        raise ValueError("用户输入为空或超过演示长度限制")
    text = query.strip()
    if text.startswith("{"):
        # 这版小智会传递 {content, language, emotion}；不能直接对整个
        # JSON 做第一人称规则提取，也不能把情绪分类当成用户事实。
        payload = json.loads(text)
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
            raise ValueError("不支持的 ASR 消息结构")
        if payload.get("role", "user") != "user":
            raise ValueError("只接收用户来源")
        text = payload["content"].strip()
    if not text or len(text) > 4000:
        raise ValueError("用户正文为空或超过演示长度限制")
    return text
