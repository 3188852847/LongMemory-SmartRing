from hashlib import sha256
import json
import sqlite3

import pytest

from longmemory.infrastructure.config.campus_calls import open_campus_calls
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.hy_memory.model_gateway import selected_model


def arrange(root):
    model = ModelSettings(provider="openai_compatible", base_url="http://127.0.0.1:23456/synthetic/v1",
        model="DeepSeek-V4-Flash", api_key="synthetic-campus-key", allow_http=True, max_tokens=512)
    proof = {"version": 1, "profile": "campus", "billing_mode": "owner_confirmed_free",
        "personal_cost_micro_cny": 0, "source": "owner_confirmation", "confirmed_date": "2026-10-19",
        "endpoint_sha256": sha256(model.base_url.encode()).hexdigest(), "request_model": model.model,
        "credential_sha256": sha256(model.api_key.encode()).hexdigest(),
        "ledger_path": "data/databases/campus-calls.sqlite3"}
    folder = root / "local/config/hy-memory"; folder.mkdir(parents=True)
    (folder / "provider-policy.json").write_text(json.dumps(proof))
    return model, proof


def test_free_calls_preserve_unknown_and_do_not_require_or_modify_paid_pool(tmp_path):
    model, proof = arrange(tmp_path)
    calls = open_campus_calls(tmp_path, model, create=True)
    first = calls.reserve("answer"); calls.finish(first, None, successful=False)
    second = calls.reserve("hy"); calls.finish(second, {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}, successful=True)
    reopened = open_campus_calls(tmp_path, model)
    status = reopened.status()
    assert status["state"] == "available" and status["personal_cost_micro_cny"] == 0
    assert status["attempt_count"] == 2 and status["unknown_or_inflight"] == 1
    assert status["observed_prompt_tokens"] == 2 and status["observed_completion_tokens"] == 3
    assert not (tmp_path / "local/worktrees").exists()
    with sqlite3.connect(tmp_path / proof["ledger_path"]) as connection:
        assert connection.execute("SELECT state,prompt_tokens FROM calls WHERE id=?", (first,)).fetchone() == ("unknown", None)


@pytest.mark.parametrize("change", [{"personal_cost_micro_cny": 1}, {"source": "assumed_free"},
    {"request_model": "deepseek-v4-flash"}, {"endpoint_sha256": "0"*64},
    {"ledger_path": "../../outside.sqlite3"}, {"credential_sha256": "0"*64}])
def test_policy_cannot_silently_change_provider_cost_or_ledger_owner(tmp_path, change):
    model, proof = arrange(tmp_path)
    (tmp_path / "local/config/hy-memory/provider-policy.json").write_text(json.dumps(proof | change))
    with pytest.raises(ValueError): open_campus_calls(tmp_path, model, create=True)
    assert not (tmp_path / proof["ledger_path"]).exists()


def test_campus_selection_preserves_case_http_consent_port_and_prefix(tmp_path):
    model, _ = arrange(tmp_path)
    folder = tmp_path / "local/config"; (folder / ".env").write_text(
        'LONGMEMORY_LLM_BASE_URL='+model.base_url+'\nLONGMEMORY_LLM_API_KEY=synthetic-campus-key\n'
        'LONGMEMORY_LLM_MODEL=DeepSeek-V4-Flash\nLONGMEMORY_LLM_ALLOW_HTTP=true\n')
    preferences=folder/'preferences';preferences.mkdir()
    (preferences/'model-profile.json').write_text(json.dumps({"web_profile":"campus","voice_profile":"campus"}))
    settings, identity = selected_model(tmp_path)
    assert settings.model == "DeepSeek-V4-Flash" and settings.base_url == model.base_url
    assert identity["billing_policy"] == "owner_confirmed_free"
