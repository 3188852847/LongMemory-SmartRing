import json

import pytest

from longmemory.infrastructure.config.model_profiles import ModelProfileStore


def payload(**changes):
    return {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "synthetic-secret",
        "timeout_seconds": 30,
        "max_tokens": 512,
        "allow_http": False,
        "activate": True,
    } | changes


def test_profile_write_never_returns_key_and_selection_is_separate(tmp_path):
    store = ModelProfileStore(tmp_path, current_profile="campus")
    result = store.save("official", payload())

    assert result["next_start_profile"] == "official"
    assert result["restart_required"] is True
    assert result["profiles"][1]["api_key_configured"] is True
    assert "synthetic-secret" not in json.dumps(result)
    assert "synthetic-secret" in (tmp_path / ".env.deepseek.local").read_text(encoding="utf-8")

    store.save("official", payload(api_key="", model="deepseek-reasoner"))
    text = (tmp_path / ".env.deepseek.local").read_text(encoding="utf-8")
    assert "synthetic-secret" in text and "deepseek-reasoner" in text


def test_profile_validation_rejects_http_without_consent_and_unknown_fields(tmp_path):
    store = ModelProfileStore(tmp_path)
    with pytest.raises(ValueError):
        store.save("official", payload(base_url="http://model.invalid/v1"))
    with pytest.raises(ValueError):
        store.save("official", payload(extra=True))
