"""为提前生成消费学校网关SSE（服务器发送事件），只在内存保留最终文本。

网络/凭据/免费证明/unknown费用账本仍归装配层和现有网关。open_response 是
异步上下文管理器工厂；其 __aexit__ 必须关闭响应，即使请求被取消。
本模块无 URL 默认值、自动重试、工具执行或正式输出回调。
"""

from contextlib import asynccontextmanager
import json

from longmemory.methods.hy_memory.answer_content import FinalContent


class GatewayPreparationModel:
    automatic_retries = False

    def __init__(self, open_response, *, model, campus_free_verified=False):
        if model not in {"deepseek-v4-flash", "deepseek-flash"}:
            raise ValueError("preemptive_model_not_allowed")
        self._open_response = open_response
        self._model = model
        self.billing_class = ("campus_free_verified" if campus_free_verified is True else "unverified")

    @asynccontextmanager
    async def open(self, request):
        if self.billing_class != "campus_free_verified":
            raise ValueError("preemptive_free_policy_required")
        # 首 system 消息不重排，不追加第二个 system，不允许模型发起工具执行。
        payload = {"model": self._model,
                   "messages": [{"role": role, "content": text} for role, text in request.messages],
                   "max_tokens": request.max_output_tokens, "stream": True,
                   "stream_options": {"include_usage": True}, "n": 1,
                   "tool_choice": "none", "thinking": {"type": "disabled"}}
        async with self._open_response(payload) as response:
            if response.status != 200:
                raise ValueError("preemptive_provider_failed")
            yield _SSEText(response)


class _SSEText:
    def __init__(self, response):
        self.response, self.usage = response, None
        self._consumed = False

    async def __aiter__(self):
        if self._consumed:
            raise ValueError("preemptive_stream_already_consumed")
        self._consumed = True
        parser, rows, event_size, total = FinalContent(), [], 0, 0
        finished = False
        # response.content 必须按行迭代（例如 aiohttp StreamReader）。不是任意字节块。
        async for line in self.response.content:
            if not isinstance(line, bytes) or len(line) > 65536:
                raise ValueError("preemptive_stream_line_invalid")
            total += len(line)
            event_size += len(line)
            if total > 524288 or event_size > 65536:
                raise ValueError("preemptive_stream_too_large")
            if line.strip():
                rows.append(line)
                continue
            data = b"\n".join(row[5:].strip() for row in rows if row.startswith(b"data:"))
            rows, event_size = [], 0
            if not data:
                continue
            if data == b"[DONE]":
                parser.finish()
                if not finished:
                    raise ValueError("preemptive_finish_missing")
                return
            packet = json.loads(data)
            if not isinstance(packet, dict) or packet.get("error") is not None:
                raise ValueError("preemptive_packet_invalid")
            if packet.get("usage") is not None:
                self.usage = packet["usage"]
            choices = packet.get("choices", [])
            if not isinstance(choices, list) or len(choices) > 1:
                raise ValueError("preemptive_choice_invalid")
            for choice in choices:
                if (not isinstance(choice, dict) or type(choice.get("index", 0)) is not int
                        or choice.get("index", 0) != 0 or finished):
                    raise ValueError("preemptive_choice_invalid")
                delta = choice.get("delta", {})
                if (not isinstance(delta, dict) or delta.get("tool_calls")
                        or delta.get("function_call")
                        or delta.get("role", "assistant") != "assistant"):
                    raise ValueError("preemptive_tool_or_delta_invalid")
                content = delta.get("content")
                if content is not None:
                    text = parser.feed(content)
                    if text:
                        yield text
                # reasoning_content 不读、不保存、不计有效回答；显式 think 复用已审查边界。
                reason = choice.get("finish_reason")
                if reason is not None:
                    if reason != "stop":
                        raise ValueError("preemptive_finish_invalid")
                    parser.finish()
                    finished = True
        raise ValueError("preemptive_done_missing")
