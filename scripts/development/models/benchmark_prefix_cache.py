"""只发合成请求的六次配对实验；默认仅显示计划，真实执行须主会话调度。"""

import argparse
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sys
from time import sleep

ROOT = Path(__file__).resolve().parents[3]
# 显式绑定本工作树源码，不依赖解释器editable安装指向。
sys.path.insert(0, str(ROOT / "src"))

from longmemory.infrastructure.config.campus_calls import FreeCampusCalls, open_campus_calls
from longmemory.methods.hy_memory.model_gateway import ModelGateway, selected_model


MAX_CALLS = 6
MAX_OUTPUT = 32
DENIED_PORTS = {8766, 8767, 8768, 18000, 18003, 18767, 18768, 18769, 18770, 8000, 8003}


def synthetic_body(model, nonce):
    # 随机标识放前端以隔离两个合成前缀；不能保证供应商已清缓存，故称cold_candidate。
    prefix = "实验标识：" + nonce + "。你是合成资料核对助手。以下只是虚构条目，用户提问时只回答完成。\n"
    prefix += "\n".join(f"合成记录{i:03d}：纸盒编号{i:03d}，颜色蓝色，数量三件，存放于虚构仓库甲。" for i in range(96))
    return {"model": model, "messages": [{"role": "system", "content": prefix},
            {"role": "user", "content": "资料核对实验，请只回答：完成。"}],
            "stream": True, "max_tokens": MAX_OUTPUT, "temperature": 0,
            "thinking": {"type": "disabled"}, "stream_options": {"include_usage": True}}


def public_usage(usage):
    """报告只含白名单计数；不复制供应商任意扩展字段。"""
    if not isinstance(usage, dict):
        return None
    keys = ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
    result = {key: usage[key] for key in keys if type(usage.get(key)) is int and usage[key] >= 0}
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict) and type(details.get("cached_tokens")) is int and details["cached_tokens"] >= 0:
        result["prompt_tokens_details"] = {"cached_tokens": details["cached_tokens"]}
    return result


class DiscardHandler:
    """所有响应正文即时丢弃，仅网关保留脱敏耗时；不打印或持久化正文。"""
    close_connection = False
    def __init__(self):
        self.wfile = self
        self.status = None
        self._text = ""
    def send_response(self, status): self.status = status
    def send_header(self, *args): pass
    def end_headers(self): pass
    def write(self, data):
        if data.startswith(b"data: {"):
            packet = json.loads(data[6:])
            for choice in packet.get("choices") or []:
                text = (choice.get("delta") or {}).get("content")
                if isinstance(text, str):
                    self._text = (self._text + text)[:256]
        return len(data)
    def flush(self): pass
    def respond(self, status, body): self.status = status
    def answer_matches(self): return self._text.strip().rstrip("。.!！") == "完成"


def validate_target(settings, identity):
    from urllib.parse import urlsplit
    url = urlsplit(settings.base_url)
    if (identity.get("profile") != "campus" or identity.get("billing_policy") != "owner_confirmed_free"
            or settings.model != "DeepSeek-V4-Flash" or not settings.api_key
            or url.hostname in {"api.deepseek.com", "localhost", "127.0.0.1", "::1"}
            or url.port in DENIED_PORTS):
        raise ValueError("experiment_requires_selected_free_campus_direct_target")


def run_pairs(settings, budget, *, gateway_factory=ModelGateway, pause=sleep, nonce_factory=lambda: secrets.token_hex(16)):
    """两组三次：新前缀/新连接→原样重复/同会话→原样重复/新会话。不重试。"""
    results = []
    for pair in range(2):
        body = synthetic_body(settings.model, nonce_factory())
        fingerprint = sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        gateway = None
        try:
            for index, condition in enumerate(("cold_candidate", "hot_same_session", "hot_fresh_session")):
                if index == 2:
                    gateway.close()
                    gateway = None
                if gateway is None:
                    gateway = gateway_factory(settings=settings, budget=budget, encoder=object(), free_policy_verified=True)
                if index:
                    pause(2)  # 官方说明落盘秒级；此等待不保证学校实现相同。
                if len(results) >= MAX_CALLS:
                    raise ValueError("experiment_call_limit")
                handler = DiscardHandler()
                gateway.stream(body, handler)
                row = gateway.responses[-1]
                results.append({"pair": pair, "condition": condition, "payload_sha256": fingerprint,
                    "attempt_id": row["attempt_id"], "http_status": row["http_status"],
                    "completed": row["completed"], "failure": row["failure"],
                    "finish_reason": row["finish_reason"], "model_ttft_ms": row["model_ttft_ms"],
                    "provider_elapsed_ms": row["provider_elapsed_ms"], "cache": row["cache"],
                    "synthetic_answer_matches": handler.answer_matches(),
                    "usage": public_usage(row.get("usage")), "has_effective_text": row["model_ttft_ms"] is not None})
                if not row["completed"] or row["failure"] is not None:
                    return results
        finally:
            if gateway is not None:
                gateway.close()
    return results


def summary(rows):
    completed = [row for row in rows if row["completed"] and row["failure"] is None]
    hits = [row for row in completed if row["cache"]["state"] == "reported_hit"]
    reported = [row for row in completed if row["cache"]["state"] in {"reported_hit", "reported_miss"}]
    comparisons = []
    for pair in range(2):
        group = [row for row in rows if row["pair"] == pair]
        if len(group) == 3 and all(row["has_effective_text"] and row["synthetic_answer_matches"] and row["completed"] and row["failure"] is None for row in group):
            comparisons.append({"pair": pair, "cold_minus_hot_same_ms": round(group[0]["model_ttft_ms"]-group[1]["model_ttft_ms"], 3),
                "fresh_minus_same_hot_ms": round(group[2]["model_ttft_ms"]-group[1]["model_ttft_ms"], 3)})
    return {"actual_requests": len(rows), "support_evidence": "provider_reported_hit" if hits else "counters_present_no_hit" if reported else "unconfirmed",
        "observed_hit_requests": len(hits), "counter_present_requests": len(reported), "paired_deltas": comparisons,
        "personal_cost_micro_cny": 0, "cost_authority": "owner_confirmed_free",
        "p95_reported": False, "cache_causality_proven": False, "device_first_audio_measured": False}


def code_identity():
    paths = ("scripts/development/models/benchmark_prefix_cache.py",
             "src/longmemory/methods/hy_memory/model_gateway.py",
             "src/longmemory/methods/hy_memory/prefix_cache.py",
             "src/longmemory/methods/hy_memory/answer_content.py",
             "src/longmemory/methods/hy_memory/provider_transport.py")
    return {path: sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-campus", action="store_true")
    parser.add_argument("--owner-root", type=Path)
    parser.add_argument("--dispatch-id")
    parser.add_argument("--output", type=Path, help="本工作树experiments/内新的专属目录")
    args = parser.parse_args(argv)
    if not args.execute_campus:
        body = synthetic_body("DeepSeek-V4-Flash", "plan-only")
        print(json.dumps({"mode": "plan_only", "maximum_calls": MAX_CALLS, "max_output_tokens_each": MAX_OUTPUT,
            "synthetic_prompt_characters": sum(len(m["content"]) for m in body["messages"]),
            "conditions": ["cold_candidate", "hot_same_session", "hot_fresh_session"], "pairs": 2,
            "network_requests": 0, "retries": 0}, ensure_ascii=False))
        return 0
    if not args.owner_root or not args.dispatch_id or not args.output:
        parser.error("真实执行须指定owner-root、dispatch-id和新的output目录")
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "experiments").resolve()) or output == (ROOT / "experiments").resolve():
        parser.error("output必须在本工作树experiments/内")
    settings, identity = selected_model(args.owner_root.resolve())
    validate_target(settings, identity)
    # 原账本只校验策略身份，绝不reserve/finish，不处理历史unknown。
    source = open_campus_calls(args.owner_root.resolve(), settings)
    output.mkdir(parents=True, exist_ok=False)
    ledger = output / "campus-calls.sqlite3"
    budget = FreeCampusCalls(ledger, proof=source.proof, create=True)
    settings = replace(settings, max_tokens=MAX_OUTPUT, timeout_seconds=min(settings.timeout_seconds, 30))
    started = datetime.now(UTC).isoformat()
    source_identity = code_identity()
    rows = run_pairs(settings, budget)
    report = {"protocol": "af-prefix-cache-six-v1", "started_at": started, "finished_at": datetime.now(UTC).isoformat(),
        "dispatch_id": args.dispatch_id, "provider_identity": identity, "rows": rows, "summary": summary(rows),
        "source_sha256": source_identity,
        "ledger_path": str(ledger), "ledger_sha256": sha256(ledger.read_bytes()).hexdigest(),
        "billing_audit": budget.status(), "raw_prompt_or_response_saved": False}
    path = output / "summary.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"report": str(path), **report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
