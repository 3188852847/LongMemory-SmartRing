"""受控日用Hy模型装配；复用V网关/设置/预算，不运行实验或创建新费用池。"""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from time import time

from longmemory.adapters.llm.local_embedding import LocalBGEEncoder, REVISION
from longmemory.infrastructure.config.hy_campaign import ExistingCampaignBudget, CAMPAIGN_RELATIVE
from longmemory.methods.hy_memory.model_gateway import ModelGateway, selected_model
from longmemory.methods.hy_memory.settings import Endpoint


BUDGET_NOTICE = "本轮模型调用已暂停：共享预算暂不允许新请求，请核对额度、价格核验和账本状态。你的原话已经保留，尚未交给记忆模型处理。"


class OwnedHyModels:
    def __init__(self, gateway, budget):
        self.gateway, self.budget = gateway, budget
        self.closed = False

    def status(self):
        return self.budget.status() if not self.closed else {"state": "paused", "reason": "model_gateway_closed"}

    def pause_notice(self):
        return BUDGET_NOTICE if self.status()["state"] != "available" else None

    def model_settings(self, phase="answer"):
        if phase not in {"answer", "voice"} or self.closed:
            raise ValueError("owned_model_phase_unavailable")
        return self.gateway.local_settings(phase, max_tokens=min(8192, self.gateway.settings.max_tokens))

    def voice_configuration(self):
        model = self.model_settings("voice")
        return {"version": 1, "base_url": model.base_url, "api_key": model.api_key,
                "model_name": model.model, "max_tokens": model.max_tokens,
                "timeout": model.timeout_seconds, "max_retries": 0}

    def close(self):
        if not self.closed:
            self.closed = True
            self.gateway.close()


def load_daily_encoder(root):
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
    encoder = LocalBGEEncoder(Path(root) / "local/runtime/models/bge-small-zh-v1.5" / REVISION)
    encoder._torch.set_num_threads(2)
    vector = encoder.encode_documents(["合成向量维度检查"])[0]
    if len(vector) != 512 or abs(sum(value * value for value in vector) - 1) > .0001:
        raise ValueError("daily_bge_dimension_or_normalization_mismatch")
    return encoder


def build_owned_daily_runtime(root, deployment, *, create=False, encoder_loader=load_daily_encoder,
                              model_loader=selected_model, gateway_factory=ModelGateway):
    from longmemory.bootstrap import build_hy_memory_runtime
    root = Path(root).resolve()
    prototype = deployment.settings
    if not prototype.managed_gateway or not prototype.network_authorized or prototype.model_mode == "synthetic_transport":
        raise ValueError("hy_daily_managed_gateway_required")
    model, identity = model_loader(root)
    if model.model != prototype.llm.model or prototype.embedding_dimensions != 512:
        raise ValueError("daily_selected_model_or_dimension_changed")
    if identity.get("profile") == "campus":
        from longmemory.infrastructure.config.campus_calls import open_campus_calls
        budget = open_campus_calls(root, model, create=create)
    else:
        budget = ExistingCampaignBudget(root / CAMPAIGN_RELATIVE)
        if budget.policy.model != model.model:
            raise ValueError("daily_campaign_selected_model_changed")
        proof_file = root / "local/config/hy-memory/price-verification.json"
        if proof_file.is_symlink() or not proof_file.is_file() or proof_file.stat().st_size > 8192:
            raise ValueError("daily_price_currency_verification_required")
        proof = json.loads(proof_file.read_text(encoding="utf-8"))
        if (proof.get("currency") != "CNY" or proof.get("currency_verified") is not True or proof.get("model") != model.model
                or proof.get("credential_sha256") != hashlib.sha256(model.api_key.encode()).hexdigest()):
            raise ValueError("daily_price_currency_verification_required")
        if type(proof.get("valid_until_unix")) in (int, float) and proof["valid_until_unix"] > time():
            budget.renew_verified_price({key:value for key,value in proof.items() if key != "credential_sha256"})
    encoder = encoder_loader(root)
    provider_identity = hashlib.sha256(json.dumps({"model": identity, "embedding": encoder.identity}, sort_keys=True).encode()).hexdigest()
    if encoder.identity != prototype.embedding.model or provider_identity != prototype.provider_identity:
        raise ValueError("daily_model_resource_identity_changed")
    management_file = root / "local/config/hy-memory/management-verification.json"
    management_verification = None
    if management_file.exists():
        if management_file.is_symlink() or management_file.stat().st_size > 8192:
            raise ValueError("hy_management_verification_invalid")
        management_verification = json.loads(management_file.read_text(encoding="utf-8"))
    authority = ({"currency_verified": False, "free_policy_verified": True}
                 if identity.get("profile") == "campus" else {"currency_verified": True})
    gateway = gateway_factory(settings=model, budget=budget, encoder=encoder, **authority)
    owned = OwnedHyModels(gateway, budget)
    runtime = None
    try:
        gateway.__enter__()
        settings = replace(prototype,
            llm=Endpoint(gateway.base + "/hy/v1", model.model, gateway.token, True),
            embedding=Endpoint(gateway.base + "/hy/v1", encoder.identity, gateway.token, True),
            # 只由已经建立的受控网关装配后台类别；不把运行时路由写进持久身份。
            background_priority_enabled=prototype.semantic_layers_enabled)
        if settings.identity() != prototype.identity():
            raise ValueError("daily_ephemeral_gateway_changed_identity")
        runtime = build_hy_memory_runtime(settings=settings, python=deployment.python,
            state_directory=deployment.state_directory, source_path=deployment.source_path,
            create=create, expected_python_version=deployment.python_version,
            management_verification=management_verification)
        if settings.include_profile and not runtime.administer_extension("hy_memory", "workspace").get("profile"):
            # UI能力关闭还不够：回答注入也不能使用范围未证明的聚合画像。
            raise ValueError("daily_profile_injection_scope_unproven")
        runtime.attach_model_service(owned)
        return runtime
    except BaseException:
        try:
            if runtime is not None:
                runtime.close()
        finally:
            owned.close()
        raise
