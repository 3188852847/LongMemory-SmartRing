"""X真实SDK常驻生命周期，外部模型仅受控替身，费用写合成账本。"""

from dataclasses import replace
from types import SimpleNamespace
from hashlib import sha256
import json
import os
from pathlib import Path
from time import time
from time import perf_counter
import socket

import pytest

from longmemory.bootstrap_hy_daily import build_owned_daily_runtime
from longmemory.infrastructure.config.hy_campaign import CAMPAIGN_RELATIVE, PRICE_SOURCE
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.hy_memory.budget import SharedBudget, PricePolicy
from longmemory.methods.hy_memory.model_gateway import ModelGateway
from longmemory.methods.hy_memory.settings import HySettings, Endpoint
from longmemory.application.round_screen_turns import memory_receipt
from longmemory.methods.hy_memory.assembly import management_primitives_identity


SDK = Path(os.environ.get("LONGMEMORY_TEST_HY_PYTHON", "missing-sdk"))
pytestmark = pytest.mark.skipif(not SDK.is_file(), reason="explicit owner-installed SDK required")


class Encoder:
    identity = "f" * 64
    def encode_documents(self, texts): return [[1.] + [0.] * 511 for _ in texts]
    def encode_query(self, text): return [1.] + [0.] * 511


def arrange(root, *, encoder=None):
    encoder = encoder or Encoder()
    model = ModelSettings(provider="openai_compatible", base_url="https://api.deepseek.com",
        api_key="synthetic-supplier-key-not-forwarded", model="deepseek-v4-flash", timeout_seconds=10)
    identity = {"profile":"official", "request_model":model.model,
        "endpoint_sha256":sha256(model.base_url.encode()).hexdigest(), "credential_present":True}
    provider = sha256(json.dumps({"model":identity,"embedding":encoder.identity},sort_keys=True).encode()).hexdigest()
    settings = HySettings(user_id="x-synthetic-daily", agent_id="x-synthetic-agent",
        llm=Endpoint("http://127.0.0.1:9/hy/v1",model.model,"ephemeral-replaced-at-start",True),
        embedding=Endpoint("http://127.0.0.1:9/hy/v1",encoder.identity,"ephemeral-replaced-at-start",True),
        embedding_dimensions=512, managed_gateway=True,provider_identity=provider,network_authorized=True,
        max_external_requests=10000,timeout_seconds=30)
    budget=SharedBudget(root/CAMPAIGN_RELATIVE,policy=PricePolicy(expires_at_unix=time()+1),create=True)
    aid=budget.reserve("probe")
    budget.finish(aid,{"prompt_tokens":245511,"completion_tokens":0,"total_tokens":245511},successful=True)
    directory=root/"local/config/hy-memory";directory.mkdir(parents=True)
    (directory/"price-verification.json").write_text(json.dumps({"source":PRICE_SOURCE,
        "verified_at_unix":time()-1,"valid_until_unix":time()+3600,"model":model.model,"currency":"CNY",
        "credential_sha256":sha256(model.api_key.encode()).hexdigest(),
        "input_micro_cny_per_token":2,"output_micro_cny_per_token":8,"currency_verified":True}))
    deployment=SimpleNamespace(settings=settings,python=SDK,python_version="3.12.13",
        state_directory=root/"data/memory/hy",source_path=root/"data/databases/hy-source.db")
    owned=[]
    def remote(payload):
        assert "synthetic-supplier-key-not-forwarded" not in payload.decode()
        return 200,json.dumps({"id":"synthetic","model":model.model,"choices":[{"finish_reason":"stop",
            "message":{"role":"assistant","content":json.dumps({"memory":[{"content":"合成用户喜欢茶","tags":[],"owner":"user"}],"intentions":[],"basic_info":{}})}}],
            "usage":{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120}}).encode()
    def factory(**kwargs):
        result=ModelGateway(**kwargs,remote=remote)
        owned.append(result)
        return result
    def open_runtime(create):
        return build_owned_daily_runtime(root,deployment,create=create,encoder_loader=lambda root:encoder,
            model_loader=lambda root:(model,identity),gateway_factory=factory)
    return open_runtime,owned,deployment,budget


def assert_closed(gateway):
    assert not gateway.thread.is_alive()
    with socket.socket() as connection:
        assert connection.connect_ex(("127.0.0.1",gateway.server.server_port))!=0


def test_constant_identity_restart_shared_spend_and_owned_gateway_cleanup(tmp_path):
    open_runtime, gateways, deployment, budget=arrange(tmp_path)
    runtime=open_runtime(True)
    first_settings=runtime._method.engine.settings
    first_port=gateways[-1].server.server_port
    try:
        assert first_settings.llm.api_key!=gateways[-1].settings.api_key
        assert first_settings.managed_gateway and first_settings.embedding_dimensions==512
        turn,_=runtime.prepare_round_screen("合成用户喜欢茶",client_round_id="a"*32,session_id="b"*32)
        runtime.complete_round_screen(turn_id=turn.event.event_id,answer="合成回答",receipt=memory_receipt(turn))
        runtime.wait_for_deferred_observations()
        assert runtime.source_status(turn.event.event_id)["state"]=="completed"
        assert runtime._method.engine.sdk_call("diagnostics")["external_http_attempts"]==0
        spent=runtime.status()["external_models"]["held_or_settled_upper_micro_cny"]
        assert spent>=491022
    finally:runtime.close()
    assert_closed(gateways[-1])
    runtime=open_runtime(False)
    try:
        second_settings=runtime._method.engine.settings
        assert second_settings.identity()==first_settings.identity()==deployment.settings.identity()
        assert second_settings.llm.api_key!=first_settings.llm.api_key
        assert runtime.status()["external_models"]["held_or_settled_upper_micro_cny"]==spent
        assert runtime._method.recall("茶").retrieved
    finally:runtime.close()
    assert_closed(gateways[-1])


def test_initialization_failure_releases_gateway_and_preserves_budget(tmp_path):
    open_runtime, gateways, deployment, budget=arrange(tmp_path)
    deployment.python_version="9.9.9"
    with pytest.raises(ValueError,match="runtime_version_identity_mismatch"):
        open_runtime(True)
    assert_closed(gateways[-1])
    assert budget.report()["attempt_count"]==1


def test_currency_proof_for_another_credential_cannot_start_or_charge(tmp_path):
    open_runtime, gateways, deployment, budget=arrange(tmp_path)
    path=tmp_path/"local/config/hy-memory/price-verification.json"
    proof=json.loads(path.read_text());proof["credential_sha256"]="0"*64
    path.write_text(json.dumps(proof))
    with pytest.raises(ValueError,match="price_currency_verification"):
        open_runtime(True)
    assert not gateways and budget.report()["attempt_count"]==1


def management_receipt(root):
    path = root / "local/config/hy-memory/management-verification.json"
    path.write_text(json.dumps({"sdk_version":"2.0.3", "rpc_source_sha256":management_primitives_identity(),
        "real_sdk_rpc_verified":True, "semantic_background_writes_disabled":True}))
    return path


def test_verified_daily_management_create_reopen_profile_scope_and_bad_receipt_cleanup(tmp_path):
    open_runtime, gateways, deployment, budget = arrange(tmp_path)
    path = management_receipt(tmp_path)
    assert not deployment.settings.management_writes_enabled
    for create in (True, False):
        runtime = open_runtime(create)
        try:
            workspace = runtime.administer_extension("hy_memory", "workspace")
            assert workspace["correction"] and workspace["deletion"] and workspace["profile"]
            assert runtime.administer_extension("hy_memory", "profile") == {"item": None}
            assert runtime._method.engine._client.state._lease is not None
            assert runtime._method.journal._lease is not None
            assert (deployment.state_directory / "management-scope.json").is_file()
        finally:
            runtime.close()
        assert_closed(gateways[-1])
    proof = json.loads(path.read_text()); proof["rpc_source_sha256"] = "0" * 64
    path.write_text(json.dumps(proof))
    with pytest.raises(ValueError, match="verification_identity"):
        open_runtime(False)
    assert_closed(gateways[-1])
    assert budget.report()["attempt_count"] == 1


def test_preexisting_daily_space_does_not_gain_profile_proof_from_new_receipt(tmp_path):
    open_runtime, gateways, deployment, budget = arrange(tmp_path)
    runtime = open_runtime(True)
    try:
        workspace = runtime.administer_extension("hy_memory", "workspace")
        assert not workspace["correction"] and not workspace["profile"]
    finally:
        runtime.close()
    management_receipt(tmp_path)
    runtime = open_runtime(False)
    try:
        workspace = runtime.administer_extension("hy_memory", "workspace")
        assert workspace["correction"] and not workspace["profile"]
        assert not (deployment.state_directory / "management-scope.json").exists()
    finally:
        runtime.close()


@pytest.mark.skipif(not os.environ.get("LONGMEMORY_TEST_BGE_ROOT"), reason="explicit existing CPU BGE root required")
def test_existing_cpu_bge_and_constant_sdk_process_warm_recall(tmp_path):
    from longmemory.bootstrap_hy_daily import load_daily_encoder
    encoder=load_daily_encoder(Path(os.environ["LONGMEMORY_TEST_BGE_ROOT"]))
    assert encoder.metadata["device"]=="cpu" and len(encoder.encode_query("合成测试"))==512
    open_runtime, gateways, deployment, budget=arrange(tmp_path, encoder=encoder)
    runtime=open_runtime(True)
    try:
        turn,_=runtime.prepare_round_screen("合成用户喜欢茶",client_round_id="c"*32,session_id="d"*32)
        runtime.complete_round_screen(turn_id=turn.event.event_id,answer="合成回答",receipt=memory_receipt(turn))
        runtime.wait_for_deferred_observations()
        assert runtime.source_status(turn.event.event_id)["state"]=="completed"
        process=runtime._method.engine._client.client._process.pid
        measured=[]
        for _ in range(2):
            start=perf_counter();support=runtime._method.recall("合成用户喜欢茶")
            measured.append(round((perf_counter()-start)*1000, 2))
            assert support.retrieved
            assert runtime._method.engine._client.client._process.pid==process
        print("synthetic_existing_bge_warm_recall_ms="+json.dumps(measured))
        assert runtime._method.engine.sdk_call("diagnostics")["external_http_attempts"]==0
    finally:runtime.close()
    assert_closed(gateways[-1])
