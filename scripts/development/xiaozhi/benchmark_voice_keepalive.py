"""用小智已安装的 OpenAI/httpx SDK，比较空闲七秒后的连接复用。

只有 --run-official 才读取项目 local/config/.env.deepseek.local 并发出固定公开问题。
每组新建一个 SDK 客户端，先请求、空闲 7 秒、再请求；仅比较 keepalive_expiry
5/120 秒，保留 SDK 默认 trust_env/代理/连接池容量。请求禁止重试和重定向。
trace 回调完全忽略信息字典，只累计建连/TLS/响应头事件的计数和耗时，不打印
URL、头、密钥、响应 ID 或正文。请求完成后按 SDK 原本的流 close 路径回收。
--http2 仅申请 HTTP/2 协商，实际协议以每次 response_http_version 为准；默认关闭。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from time import perf_counter, sleep

from benchmark_voice_reply import BenchmarkError, MODEL_NAME, load_official_config


QUESTION = "请用一句话说明，为什么傍晚的天空会变红？"
SYSTEM = "你是一个友好、自然的中文助手。请简短回答用户的问题。"
PHASES = ("connect_tcp", "start_tls", "receive_response_headers")


class ConnectionTrace:
    """仅保留事件名白名单；不访问可能包含代理、证书、URL 的 info。"""
    def __init__(self, clock=perf_counter):
        self.clock = clock
        self.reset()

    def reset(self):
        self.started = {}
        self.counts = {name: 0 for name in PHASES}
        self.completed = {name: 0 for name in PHASES}
        self.elapsed = {name: 0.0 for name in PHASES}
        self.failed = 0

    def trace(self, event_name, _info):
        parts = event_name.rsplit(".", 2)
        if len(parts) != 3 or parts[1] not in PHASES:
            return
        prefix, phase, state = parts
        key = (prefix, phase)
        if state == "started":
            self.started[key] = self.clock()
            self.counts[phase] += 1
        elif state in {"complete", "failed"} and key in self.started:
            self.elapsed[phase] += (self.clock() - self.started.pop(key)) * 1000
            if state == "complete":
                self.completed[phase] += 1
            else:
                self.failed += 1

    def request_hook(self, request):
        url = request.url
        if (url.scheme != "https" or url.host != "api.deepseek.com"
                or url.port not in {None, 443} or url.path != "/v1/chat/completions"
                or url.query or url.username or url.password):
            raise BenchmarkError("official_endpoint_required")
        request.extensions["trace"] = self.trace

    def snapshot(self):
        result = {"trace_failed_count": self.failed}
        for phase in PHASES:
            result[phase + "_count"] = self.counts[phase]
            result[phase + "_completed_count"] = self.completed[phase]
            result[phase + "_ms"] = round(self.elapsed[phase], 3)
        return result


def create_sdk_client(config, expiry, trace, *, http2=False):
    # 独立实验进程关闭外部库日志，防止 OPENAI_LOG 等环境选项打印私有请求。
    # 不改环境变量，不改变 SDK 的代理/TLS/trust_env 默认行为。
    logging.disable(logging.CRITICAL)
    import httpx
    import openai
    defaults = openai.DEFAULT_CONNECTION_LIMITS
    if defaults.keepalive_expiry != 5.0:
        raise BenchmarkError("sdk_keepalive_default_changed")
    http_client = openai.DefaultHttpxClient(
        limits=httpx.Limits(max_connections=defaults.max_connections,
                           max_keepalive_connections=defaults.max_keepalive_connections,
                           keepalive_expiry=expiry),
        event_hooks={"request": [trace.request_hook]}, follow_redirects=False,
        http2=http2,
    )
    try:
        client = openai.OpenAI(
            api_key=config.api_key, base_url="https://api.deepseek.com/v1",
            max_retries=0, timeout=httpx.Timeout(30.0, connect=10.0, read=10.0, write=10.0, pool=5.0),
            http_client=http_client,
        )
    except Exception:
        http_client.close()
        raise BenchmarkError("sdk_initialization_failed") from None
    versions = {"openai": openai.__version__, "httpx": httpx.__version__}
    return client, versions


def response_metadata(stream):
    """只读实际协议与 Connection: close 标志，不保存完整响应头。"""
    response = getattr(stream, "response", None)
    if response is None:
        return {"response_http_version": None, "response_connection_close": None}
    version = getattr(response, "http_version", None)
    connection = response.headers.get("connection", "")
    return {"response_http_version": version if version in {"HTTP/1.0", "HTTP/1.1", "HTTP/2"} else None,
            "response_connection_close": "close" in {part.strip().lower() for part in connection.split(",")}}


def measure_request(client, config, trace, *, clock=perf_counter):
    trace.reset()
    started = clock()
    first_output = None
    count = 0
    finished = False
    actual_model = None
    stream = None
    try:
        stream = client.chat.completions.create(
            model=config.model, messages=[{"role": "system", "content": SYSTEM},
                                          {"role": "user", "content": QUESTION}],
            stream=True, max_tokens=128, extra_body={"thinking": {"type": "disabled"}},
        )
        metadata = response_metadata(stream)
        for chunk in stream:
            elapsed = (clock() - started) * 1000
            if elapsed > 30000:
                raise BenchmarkError("request_timeout")
            model = getattr(chunk, "model", None)
            if isinstance(model, str) and MODEL_NAME.fullmatch(model):
                actual_model = model
            choices = getattr(chunk, "choices", ())
            if not choices:
                continue
            if len(choices) != 1:
                raise BenchmarkError("stream_choices_invalid")
            choice = choices[0]
            delta = choice.delta
            if getattr(delta, "tool_calls", None) or getattr(delta, "function_call", None):
                raise BenchmarkError("unexpected_tool_call")
            content = getattr(delta, "content", None)
            if content is not None and not isinstance(content, str):
                raise BenchmarkError("stream_content_invalid")
            if content:
                count += len(content)
                if count > 4096:
                    raise BenchmarkError("response_too_large")
                if content.strip() and first_output is None:
                    first_output = elapsed
            reason = getattr(choice, "finish_reason", None)
            if reason is not None:
                if reason != "stop":
                    raise BenchmarkError("response_not_completed")
                finished = True
        completed_ms = (clock() - started) * 1000
        if not finished or first_output is None:
            raise BenchmarkError("stream_incomplete")
    except BenchmarkError:
        raise
    except Exception:
        raise BenchmarkError("sdk_request_failed") from None
    finally:
        if stream is not None:
            stream.close()
    return {"llm_first_output_ms": round(first_output, 3),
            "response_completed_ms": round(completed_ms, 3),
            "response_chars": count, "actual_model": actual_model, **metadata, **trace.snapshot()}


def run_comparison(config, *, repeat=1, client_factory=create_sdk_client,
                   measure=measure_request, clock=perf_counter, sleeper=sleep, http2=False):
    if repeat not in {1, 2}:
        raise BenchmarkError("repeat_invalid")
    records = []
    versions = None
    for cycle in range(repeat):
        # 第二轮反转顺序，不能靠挑选快的样本制造优化结论。
        for expiry in ((5.0, 120.0) if cycle % 2 == 0 else (120.0, 5.0)):
            trace = ConnectionTrace(clock)
            client, versions = client_factory(config, expiry, trace, **({"http2": True} if http2 else {}))
            try:
                initial = measure(client, config, trace, clock=clock)
                initial.update({"keepalive_expiry_seconds": expiry, "request_in_pair": 1,
                                "idle_seconds": 0.0, "repeat": cycle + 1})
                records.append(initial)
                idle_started = clock()
                sleeper(7.0)
                actual_idle = clock() - idle_started
                second = measure(client, config, trace, clock=clock)
                second.update({"keepalive_expiry_seconds": expiry, "request_in_pair": 2,
                               "idle_seconds": round(actual_idle, 3), "repeat": cycle + 1})
                records.append(second)
            finally:
                client.close()
    return {"scope": "synthetic_sdk_keepalive_only_no_tts_no_memory",
            "sdk_versions": versions, "trust_env": "sdk_default",
            "http2_requested": http2,
            "max_tokens": 128, "max_retries": 0, "records": records}


def main(argv=None):
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-official", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--repeat", type=int, choices=(1, 2), default=1)
    parser.add_argument("--http2", action="store_true")
    args = parser.parse_args(argv)
    if not args.run_official:
        print('{"state":"not_run","scope":"synthetic_sdk_keepalive_only"}')
        return 0
    try:
        if args.env_file is None:
            raise BenchmarkError("official_config_path_required")
        config = load_official_config(args.env_file)
        print(json.dumps(run_comparison(config, repeat=args.repeat, http2=args.http2), ensure_ascii=False))
        return 0
    except BenchmarkError as error:
        print(json.dumps({"error": str(error)}))
    except Exception:
        print('{"error":"keepalive_benchmark_failed"}')
    return 2


if __name__ == "__main__":
    sys.exit(main())
