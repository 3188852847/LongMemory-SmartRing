"""CosyVoice3 常见寒暄快速通道。

只处理无需记忆或模型判断的严格封闭意图。用户原话仍经过 Memory 查询入口，
以保留 L0 和正常的提取审计；回答本身来自同声线预生成音频。
"""

import asyncio
import json
import re
from uuid import uuid4
from functools import lru_cache
import importlib.util
from pathlib import Path


@lru_cache(maxsize=1)
def _voice_profile_helper():
    spec = importlib.util.spec_from_file_location('fast_cosyvoice_profiles', Path(__file__).with_name('cosyvoice_profiles.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def default_voice_active():
    return _voice_profile_helper().default_voice_active()


COSYVOICE_URL = "http://127.0.0.1:18770/v1/audio/speech"
FAST_RESPONSE_ASSETS = {
    "你好呀我在呢": "hello.wav",
    "我在听得到": "present.wav",
    "不用客气": "thanks.wav",
    "晚安做个好梦": "goodnight.wav",
}

_QUERY_RESPONSES = {
    "你好": "你好呀，我在呢。",
    "嗨": "你好呀，我在呢。",
    "哈喽": "你好呀，我在呢。",
    "hello": "你好呀，我在呢。",
    "在吗": "我在，听得到。",
    "你在吗": "我在，听得到。",
    "还在吗": "我在，听得到。",
    "你还在吗": "我在，听得到。",
    "听得到吗": "我在，听得到。",
    "能听见吗": "我在，听得到。",
    "谢谢": "不用客气。",
    "谢谢你": "不用客气。",
    "晚安": "晚安，做个好梦。",
}


def fast_response_for(query):
    """返回严格封闭意图的固定回复；不做包含匹配或语义猜测。"""

    if not isinstance(query, str) or len(query) > 16000:
        return None
    text = query.strip()
    if text.startswith("{"):
        # FunASR 的正文封装与归档入口相同；只用 content 匹配，元数据不作意图。
        # 原 query 继续交给 Memory/对话，不在快路改写来源或说话人信息。
        try:
            payload = json.loads(text)
        except (ValueError, RecursionError):
            return None
        if (not isinstance(payload, dict) or payload.get("role", "user") != "user"
                or not isinstance(payload.get("content"), str)):
            return None
        text = payload["content"].strip()
    if not text or len(text) > 4000:
        return None
    normalized = re.sub(r"[\s，。！？!?、,.]+", "", text).casefold()
    return _QUERY_RESPONSES.get(normalized)


def fast_asset_for_text(text):
    if not isinstance(text, str):
        return None
    normalized = re.sub(r"[\s，。！？!?、,.]+", "", text).casefold()
    return FAST_RESPONSE_ASSETS.get(normalized)


def _uses_cosyvoice3(connection):
    selected = connection.config.get("selected_module", {}).get("TTS")
    custom = connection.config.get("TTS", {}).get(selected, {})
    return selected == "CustomTTS" and custom.get("url") == COSYVOICE_URL


def install_fast_voice_responses(connection_class):
    """在模型前回答封闭寒暄，同时复用原有 TTS 生命周期和记忆归档。"""

    if getattr(connection_class, "_longmemory_fast_voice_installed", False):
        return
    original = connection_class.chat

    def chat(connection, query, depth=0):
        response = fast_response_for(query) if depth == 0 else None
        if response is None or not _uses_cosyvoice3(connection) or not default_voice_active():
            return original(connection, query, depth)

        from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO
        from core.utils.dialogue import Message

        sentence_id = uuid4().hex
        connection.sentence_id = sentence_id
        connection.client_abort = False
        tracker = getattr(connection, "_longmemory_voice_latency", None)
        if tracker is not None:
            tracker.set_response_path("preset")
        connection.dialogue.put(Message(role="user", content=query))

        # Memory 查询对简单寒暄会走 NOOP，但仍负责保存 L0 和提取审计。
        # 失败不能阻止已经确定安全的本地寒暄回答，也不能回退后重复写入。
        memory = getattr(connection, "memory", None)
        if memory is not None and callable(getattr(memory, "query_memory", None)):
            try:
                future = asyncio.run_coroutine_threadsafe(
                    memory.query_memory(query), connection.loop
                )
                future.result()
                fixed = getattr(memory, "fixed_reply_for_current_turn", None)
                if callable(fixed):
                    response = fixed() or response
            except Exception:
                connection.logger.bind(tag="fast-voice").warning(
                    "寒暄归档失败；本轮继续播放本地回答且不自动重试"
                )

        connection.dialogue.put(Message(role="assistant", content=response))
        connection.tts.tts_text_queue.put(TTSMessageDTO(
            sentence_id=sentence_id,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        ))
        connection.tts.tts_text_queue.put(TTSMessageDTO(
            sentence_id=sentence_id,
            sentence_type=SentenceType.MIDDLE,
            content_type=ContentType.TEXT,
            content_detail=response,
        ))
        connection.tts.tts_text_queue.put(TTSMessageDTO(
            sentence_id=sentence_id,
            sentence_type=SentenceType.LAST,
            content_type=ContentType.ACTION,
        ))
        connection.logger.bind(tag="fast-voice").info(
            "封闭寒暄已使用本地预置语音"
        )
        return True

    connection_class.chat = chat
    connection_class._longmemory_fast_voice_installed = True
