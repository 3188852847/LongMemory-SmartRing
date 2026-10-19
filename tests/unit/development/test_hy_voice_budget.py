import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


SCRIPTS = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi"


def load(name):
    spec = importlib.util.spec_from_file_location("x_test_" + name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def configuration(port=23456, token="a" * 43):
    return {"version":1,"base_url":f"http://127.0.0.1:{port}/voice/v1","api_key":token,
        "model_name":"deepseek-v4-flash","max_tokens":512,"timeout":60,"max_retries":0}


def test_consumption_projection_preserves_canonical_bytes_and_rejects_unknown_target_edits(tmp_path):
    module = load("config_paths")
    server = tmp_path.joinpath(*module.SERVER_PARTS)
    source = tmp_path / "local/config/xiaozhi.yaml"; source.parent.mkdir(parents=True)
    original = {"selected_module":{"LLM":"CampusLLM"},"LLM":{"CampusLLM":{"type":"openai",
        "api_key":"synthetic-supplier-key","base_url":"https://api.deepseek.com","model_name":"deepseek-v4-flash","temperature":.7}},
        "prompt":"合成角色保持","binding":"synthetic-binding","TTS":{"synthetic":"untouched"}}
    source.write_bytes(yaml.safe_dump(original, allow_unicode=True).encode())
    before = source.read_bytes()
    module.render_runtime_config(server)
    module.render_runtime_config(server, model_override=configuration())
    target = server / "data/.config.yaml"
    projected = yaml.safe_load(target.read_bytes())
    assert source.read_bytes() == before
    assert projected["LLM"]["CampusLLM"]["api_key"] == "a" * 43
    assert "synthetic-supplier-key" not in target.read_text()
    assert projected["prompt"] == original["prompt"] and projected["TTS"] == original["TTS"]
    module.render_runtime_config(server, model_override=configuration(23457, "b" * 43))
    assert source.read_bytes() == before
    target.write_bytes(target.read_bytes() + b"# unknown edit\n")
    with pytest.raises(ValueError, match="runtime_config_changed"):
        module.render_runtime_config(server, model_override=configuration())


def test_unmanaged_projection_and_external_gateway_targets_are_rejected(tmp_path):
    module = load("config_paths")
    with pytest.raises(ValueError, match="managed_project"):
        module.render_runtime_config(tmp_path, model_override=configuration())
    budget = load("voice_budget")
    for change in ({"base_url":"https://api.deepseek.com/voice/v1"},{"max_retries":2}, {"max_tokens":None}):
        with pytest.raises(ValueError): budget.validate_configuration(configuration() | change)


def test_notice_is_local_and_stream_clients_disable_retry_without_changing_supplier(tmp_path):
    module = load("voice_budget")
    calls = []
    original = SimpleNamespace(response=lambda *args, **kwargs: calls.append("paid") or iter(["原流片"]),
        response_with_functions=lambda *args, **kwargs: iter([("原流片", None)]))
    memory = SimpleNamespace(fixed_reply_for_current_turn=lambda:"预算暂停固定回执")
    proxy = module.BudgetNoticeLLM(original, memory)
    assert list(proxy.response("session", [])) == ["预算暂停固定回执"] and not calls
    assert list(proxy.response_with_functions("session", [])) == [("预算暂停固定回执", None)]
    memory.fixed_reply_for_current_turn = lambda:None
    assert list(proxy.response("session", [])) == ["原流片"]
    provider = SimpleNamespace(openai=SimpleNamespace(OpenAI=lambda **kwargs:kwargs))
    module.install_no_retry_gateway_client(provider)
    result = provider.openai.OpenAI(base_url=configuration()["base_url"], api_key="random-local", max_retries=3)
    assert result["max_retries"] == 0
    with pytest.raises(ValueError): provider.openai.OpenAI(base_url="https://api.deepseek.com",api_key="synthetic")
