"""用公开固定问题比较语音回答策略，只记录数值，不接触记忆或个人对话。

默认只说明边界。只有显式传入 --run-official 和项目内 .env.deepseek.local 才联网；
仅允许 DeepSeek 官方 HTTPS，直连、不跟随重定向、不重试、不采用代理环境变量。
首段时刻复用日用 CosyVoice 切段规则，但不调用 TTS，不能代表圆屏首声。

每次请求新建 HTTPS 连接；日用 OpenAI SDK 通常复用连接，两者不能直接等同。
connection_ms 包含 DNS/TCP/TLS；headers_ms 从连接就绪到发送 POST 并收到响应头，
两阶段不重叠。first_output_after_headers_ms 是收到头后到首个可见文本的等待。
这些是客户端墙钟，不能仅凭响应头等待将云端排队、模型计算和网络往返拆开。
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
import http.client
import json
import math
from pathlib import Path
import re
import socket
import sys
from time import perf_counter
from types import SimpleNamespace
from urllib.parse import urlsplit

from cosyvoice_segments import install_cosyvoice_punctuation_policy


PROJECT = Path(__file__).resolve().parents[3]
OFFICIAL_ENV = PROJECT / ".env.deepseek.local"
CASES = (
    ("sunset", "为什么傍晚的天空会变红？"),
    ("desk", "请给我一个整理书桌的简单办法。"),
    ("walk", "晚上散步时可以做些什么让自己放松？"),
)
BASELINE_SYSTEM = "你是一个友好、自然的中文助手。请简短回答用户的问题。"
MAX_LINE_BYTES = 65536
MAX_RESPONSE_BYTES = 512 * 1024
MAX_RESPONSE_CHARS = 4096
MODEL_OVERRIDES = ("deepseek-v4-flash", "deepseek-flash")
MODEL_NAME = re.compile(r"deepseek[-a-zA-Z0-9._]{1,80}\Z")


class BenchmarkError(Exception):
    """错误只携带固定原因码，不透传服务响应、URL、请求或密钥。"""


@dataclass(frozen=True)
class OfficialConfig:
    api_key: str = field(repr=False)
    model: str
    path: str = "/v1/chat/completions"


@dataclass
class ObservedLines:
    """仅附加数值观测，不把 HTTP 对象、响应头或 SSE 正文放入结果。"""
    source: object = field(repr=False)
    connection_ms: float
    headers_ms: float
    headers_ready_at: float

    def __iter__(self):
        return iter(self.source)


def load_official_config(path: Path) -> OfficialConfig:
    # 不接受通用 .env、任意用户文件或软链接；该入口不能变成私有文件读取器。
    if path.is_symlink() or path.resolve() != OFFICIAL_ENV.resolve() or OFFICIAL_ENV.is_symlink():
        raise BenchmarkError("official_config_path_required")
    try:
        if not path.is_file() or path.stat().st_size > 65536:
            raise BenchmarkError("official_config_unavailable")
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise BenchmarkError("official_config_unavailable") from None
    allowed = {"LONGMEMORY_LLM_BASE_URL", "LONGMEMORY_LLM_MODEL", "LONGMEMORY_LLM_API_KEY"}
    values = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in allowed:
            continue
        if key in values:
            raise BenchmarkError("official_config_ambiguous")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    try:
        parsed = urlsplit(values.get("LONGMEMORY_LLM_BASE_URL", ""))
        valid = (parsed.scheme == "https" and parsed.netloc == "api.deepseek.com"
                 and parsed.path in {"", "/", "/v1", "/v1/"}
                 and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise BenchmarkError("official_endpoint_required")
    model = values.get("LONGMEMORY_LLM_MODEL", "")
    key = values.get("LONGMEMORY_LLM_API_KEY", "")
    if not MODEL_NAME.fullmatch(model):
        raise BenchmarkError("official_model_invalid")
    if not key or len(key) > 2048 or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise BenchmarkError("official_key_invalid")
    return OfficialConfig(key, model)


def request_body(config, question, style, *, temperature=None, apply_policy=None):
    if style not in {"baseline", "realtime"}:
        raise BenchmarkError("style_invalid")
    messages = [{"role": "system", "content": BASELINE_SYSTEM},
                {"role": "user", "content": question}]
    if style == "realtime":
        if apply_policy is None:
            from voice_response_policy import prepare_voice_dialogue
            apply_policy = lambda items: prepare_voice_dialogue(items, style="realtime")
        messages = apply_policy(messages)
    body = {"model": config.model, "messages": messages, "stream": True,
            "max_tokens": 256, "thinking": {"type": "disabled"}}
    # 两组温度一致。未指定则两组均省略，沿用官方 API 默认；不读私有 YAML。
    if temperature is not None:
        if type(temperature) not in {int, float} or not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise BenchmarkError("temperature_invalid")
        body["temperature"] = temperature
    return body


@contextmanager
def official_lines(config, body, deadline, clock=perf_counter):
    """每次读写都受剩余总时间约束；不借助可能自动重试的 SDK。"""
    if config.path != "/v1/chat/completions":
        raise BenchmarkError("official_endpoint_required")
    def remaining():
        value = deadline - clock()
        if value <= 0:
            raise BenchmarkError("request_timeout")
        return min(10.0, value)

    connection = http.client.HTTPSConnection("api.deepseek.com", timeout=remaining())
    response = None
    try:
        connect_started = clock()
        connection.connect()
        connected_at = clock()
        transport_socket = connection.sock
        transport_socket.settimeout(remaining())
        connection.request("POST", config.path, body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                           headers={"Content-Type": "application/json", "Accept": "text/event-stream",
                                    "Authorization": "Bearer " + config.api_key})
        transport_socket.settimeout(remaining())
        response = connection.getresponse()
        headers_ready_at = clock()
        if response.status != 200:
            # 3xx 不跟随，4xx/5xx 不读正文或重试，也不记录请求 ID。
            raise BenchmarkError("official_http_rejected")
        if response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "text/event-stream":
            raise BenchmarkError("official_stream_type_invalid")

        def lines():
            total = 0
            while True:
                transport_socket.settimeout(remaining())
                value = response.readline(MAX_LINE_BYTES + 1)
                if not value:
                    return
                total += len(value)
                if len(value) > MAX_LINE_BYTES or total > MAX_RESPONSE_BYTES:
                    raise BenchmarkError("response_too_large")
                yield value

        yield ObservedLines(lines(), (connected_at - connect_started) * 1000,
                            (headers_ready_at - connected_at) * 1000, headers_ready_at)
    except BenchmarkError:
        raise
    except (TimeoutError, socket.timeout):
        raise BenchmarkError("request_timeout") from None
    except Exception:
        raise BenchmarkError("official_transport_failed") from None
    finally:
        if response is not None:
            response.close()
        connection.close()


def sse_events(lines):
    data = []
    event_bytes = 0
    for raw in lines:
        try:
            line = raw.decode("utf-8").rstrip("\r\n")
        except UnicodeError:
            raise BenchmarkError("stream_encoding_invalid") from None
        if not line:
            if data:
                yield "\n".join(data)
            data = []
            event_bytes = 0
        elif line.startswith("data:"):
            value = line[5:].removeprefix(" ")
            event_bytes += len(raw)
            if event_bytes > MAX_LINE_BYTES:
                raise BenchmarkError("response_too_large")
            data.append(value)
    if data:
        raise BenchmarkError("stream_incomplete")


def measure_reply(config, case, style, *, temperature=None, timeout_seconds=30,
                  open_lines=official_lines, clock=perf_counter, apply_policy=None, text_consumer=None):
    if not 1 <= timeout_seconds <= 60:
        raise BenchmarkError("timeout_invalid")
    case_id, question = case
    body = request_body(config, question, style, temperature=temperature, apply_policy=apply_policy)
    segmenter = SimpleNamespace(tts_text_buff=[], processed_chars=0, is_first_sentence=True,
                               tts_stop_request=False, current_sentence_id="synthetic-benchmark",
                               _get_segment_text=lambda: None)
    install_cosyvoice_punctuation_policy(segmenter)
    started = clock()
    first_output = first_segment_ms = None
    first_segment = ""
    actual_model = None
    finished = False
    done = False
    total_chars = 0
    with open_lines(config, body, started + timeout_seconds, clock) as lines:
        connection_ms = getattr(lines, "connection_ms", None)
        headers_ms = getattr(lines, "headers_ms", None)
        headers_ready_at = getattr(lines, "headers_ready_at", None)
        for event in sse_events(lines):
            elapsed = (clock() - started) * 1000
            if elapsed > timeout_seconds * 1000:
                raise BenchmarkError("request_timeout")
            if event == "[DONE]":
                done = True
                break
            try:
                payload = json.loads(event)
            except (ValueError, TypeError):
                raise BenchmarkError("stream_json_invalid") from None
            if not isinstance(payload, dict) or "error" in payload:
                raise BenchmarkError("official_stream_rejected")
            model = payload.get("model")
            if isinstance(model, str) and MODEL_NAME.fullmatch(model):
                actual_model = model
            choices = payload.get("choices", [])
            if not isinstance(choices, list) or len(choices) > 1:
                raise BenchmarkError("stream_choices_invalid")
            if not choices:
                continue
            choice = choices[0]
            if not isinstance(choice, dict) or not isinstance(choice.get("delta", {}), dict):
                raise BenchmarkError("stream_delta_invalid")
            delta = choice.get("delta", {})
            if delta.get("tool_calls") or delta.get("function_call"):
                raise BenchmarkError("unexpected_tool_call")
            content = delta.get("content")
            if content is not None and not isinstance(content, str):
                raise BenchmarkError("stream_content_invalid")
            if content:
                total_chars += len(content)
                if total_chars > MAX_RESPONSE_CHARS:
                    raise BenchmarkError("response_too_large")
                segmenter.tts_text_buff.append(content)
                if content.strip() and first_output is None:
                    first_output = elapsed
                if first_segment_ms is None:
                    first_segment = segmenter._get_segment_text() or ""
                    if first_segment:
                        first_segment_ms = elapsed
            reason = choice.get("finish_reason")
            if reason is not None:
                if reason != "stop":
                    raise BenchmarkError("response_not_completed")
                finished = True
        completed_ms = (clock() - started) * 1000
    if not done or not finished:
        raise BenchmarkError("stream_incomplete")
    answer = "".join(segmenter.tts_text_buff)
    if first_output is None or not answer.strip():
        raise BenchmarkError("response_empty")
    if first_segment_ms is None:
        # 日用 LAST 会交付不足阈值的完整短回复；只在响应真正结束时记为就绪。
        first_segment, first_segment_ms = answer.strip(), completed_ms
    result = {"case": case_id, "style": style, "requested_model": config.model,
              "actual_model": actual_model, "llm_first_output_ms": round(first_output, 3),
              "connection_ms": round(connection_ms, 3) if connection_ms is not None else None,
              "headers_ms": round(headers_ms, 3) if headers_ms is not None else None,
              "first_output_after_headers_ms": round(first_output - (headers_ready_at - started) * 1000, 3)
              if headers_ready_at is not None else None,
              "first_segment_ready_ms": round(first_segment_ms, 3),
              "response_completed_ms": round(completed_ms, 3),
              "first_segment_chars": len(first_segment), "response_chars": len(answer),
              "temperature": temperature, "max_tokens": 256, "thinking_disabled": True}
    if text_consumer is not None:
        # 可选后续合成只通过内存回调接收文本；默认 CLI 不暴露此入口或写入正文。
        text_consumer(first_segment, answer)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-official", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--style", choices=("both", "baseline", "realtime"), default="both")
    parser.add_argument("--repeat", type=int, choices=(1, 2), default=1)
    parser.add_argument("--case-count", type=int, choices=(2, 3), default=2)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--model", choices=MODEL_OVERRIDES)
    parser.add_argument("--timeout-seconds", type=float, default=30)
    args = parser.parse_args(argv)
    if not args.run_official:
        print(json.dumps({"state": "not_run", "requires": "--run-official --env-file .env.deepseek.local",
                          "scope": "synthetic_text_only_no_tts_no_memory"}))
        return 0
    try:
        if args.env_file is None:
            raise BenchmarkError("official_config_path_required")
        config = load_official_config(args.env_file)
        if args.model is not None:
            config = OfficialConfig(config.api_key, args.model)
        records = []
        for repeat in range(args.repeat):
            for index, case in enumerate(CASES[:args.case_count]):
                styles = [args.style] if args.style != "both" else ["baseline", "realtime"]
                if args.style == "both" and (repeat + index) % 2:
                    styles.reverse()
                for style in styles:
                    record = measure_reply(config, case, style, temperature=args.temperature,
                                           timeout_seconds=args.timeout_seconds)
                    record["repeat"] = repeat + 1
                    records.append(record)
        print(json.dumps({"scope": "llm_only_synthetic_no_audio_no_memory",
                          "transport": "fresh_https_connection_per_request",
                          "records": records}, ensure_ascii=False))
        return 0
    except BenchmarkError as error:
        print(json.dumps({"error": str(error)}))
    except Exception:
        print('{"error":"benchmark_failed"}')
    return 2


if __name__ == "__main__":
    sys.exit(main())
