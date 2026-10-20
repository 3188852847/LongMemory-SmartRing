"""真实请求门的禁网替身验证；不读取任何所有者配置/凭据。"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"fixtures"))
from ab_hy_campus_gate import HardGate,GateStopped,clamp,gateway_type
from hy_campus_probe_support import limited_campus_calls
from longmemory.methods.hy_memory.model_gateway import ModelGateway
from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
from longmemory.infrastructure.config.settings import ModelSettings


def test_seventh_llm_attempt_is_denied_before_sender_and_survives_reopen(tmp_path):
    gate = HardGate(tmp_path/"gate.db",create=True)
    sent = []
    for i in range(6):
        identifier = gate.claim("school_llm",request_sha256=hashlib.sha256(str(i).encode()).hexdigest(),output_limit=512)
        sent.append(identifier)
        gate.finish(identifier,status=200)
    with pytest.raises(GateStopped):
        gate.claim("school_llm",request_sha256="a"*64,output_limit=512)
    assert len(sent)==6
    state = HardGate(gate.path).snapshot()
    assert state["actual_llm_attempts"]==6 and state["halted"] and state["reason_code"]=="llm_limit"


def test_http_counts_sdk_local_and_school_hops_and_denies_39th(tmp_path):
    gate = HardGate(tmp_path/"gate.db",create=True)
    for _ in range(37):
        gate.sdk_claim("http://127.0.0.1:52111/hy/v1/embeddings")
    gate.claim("school_llm",request_sha256="a"*64,output_limit=512)
    with pytest.raises(GateStopped):
        gate.sdk_claim("http://127.0.0.1:52111/hy/v1/chat/completions")
    assert gate.snapshot()["http_attempts"]==38
    assert gate.snapshot()["reason_code"]=="http_limit"


def test_parallel_claims_cannot_overshoot(tmp_path):
    path = tmp_path/"gate.db"
    HardGate(path,create=True)
    def claim(i):
        try:
            return HardGate(path).claim("school_llm",request_sha256=hashlib.sha256(str(i).encode()).hexdigest(),output_limit=512)
        except GateStopped:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(claim,range(16)))
    assert len([identifier for identifier in ids if identifier])==6
    assert HardGate(path).snapshot()["http_attempts"]==6


def test_deadline_denies_before_any_network_and_invalid_endpoint_denied(tmp_path,monkeypatch):
    import ab_hy_campus_gate as module
    gate = HardGate(tmp_path/"gate.db",create=True,started=100)
    monkeypatch.setattr(module,"time",lambda:341)
    with pytest.raises(GateStopped,match="wall_deadline"):
        gate.sdk_claim("http://127.0.0.1:52111/hy/v1/embeddings")
    assert gate.snapshot()["http_attempts"]==0
    with pytest.raises(GateStopped,match="endpoint_denied"):
        gate.sdk_claim("https://unapproved.invalid/chat/completions")


def test_gateway_actual_sender_gets_clamped_payload_and_duplicate_never_sent(tmp_path):
    gate = HardGate(tmp_path/"gate.db",create=True)
    model = ModelSettings(provider="openai_compatible",base_url="https://blocked.invalid",api_key="synthetic",
        model="synthetic-campus",timeout_seconds=2)
    budget = limited_campus_calls(FreeCampusCalls,tmp_path/"free.db",{"request_model":model.model},create=True,arm="candidate",limit=6)
    encoder = SimpleNamespace(identity="encoder",encode_documents=lambda texts:[[1.0]*8 for _ in texts])
    sent = []
    def remote(payload):
        sent.append(json.loads(payload))
        return 200,json.dumps({"model":model.model,"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"{}"}}],
            "usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}).encode()
    gateway = gateway_type(ModelGateway)(gate=gate,raw_directory=tmp_path,settings=model,budget=budget,encoder=encoder,
        free_policy_verified=True,remote=remote)
    body = {"model":model.model,"messages":[{"role":"system","content":"synthetic"},{"role":"user","content":"synthetic"}],
        "max_tokens":9999,"max_completion_tokens":9999,"max_output_tokens":9999,"n":4,"stream":False}
    try:
        gate.sdk_claim("http://127.0.0.1:52111/hy/v1/chat/completions")
        assert gateway.complete("hy",body)[0]==200
        assert sent[0]["max_tokens"]==512 and sent[0]["n"]==1 and "max_completion_tokens" not in sent[0]
        gate.sdk_claim("http://127.0.0.1:52111/hy/v1/chat/completions")
        assert gateway.complete("hy",body)[0]==502
        assert len(sent)==1
        assert gate.snapshot()["reason_code"]=="duplicate_model_request"
    finally:
        gateway.close()


@pytest.mark.parametrize("body",[{"max_tokens":False},{"max_tokens":0},{"max_tokens":1,"stream":True}])
def test_invalid_payload_cannot_bypass_clamp(body):
    with pytest.raises(ValueError):
        clamp(body)
