from types import SimpleNamespace

import pytest

from longmemory.methods.hy_memory import model_gateway as module


@pytest.mark.parametrize("base_url,model", [
    ("http://synthetic-campus.invalid:51080/prefix/v1", "DeepSeek-V4-Flash"),
    ("http://api.deepseek.com", "deepseek-v4-flash"),
    ("https://synthetic-other.invalid/v1", "deepseek-v4-flash"),
    ("https://api.deepseek.com:444/v1", "deepseek-v4-flash"),
    ("https://api.deepseek.com/other", "deepseek-v4-flash"),
    ("https://api.deepseek.com/v1?key=synthetic", "deepseek-v4-flash"),
    ("https://synthetic:secret@api.deepseek.com/v1", "deepseek-v4-flash"),
    ("https://api.deepseek.com/v1", "DeepSeek-V4-Flash"),
])
def test_nonofficial_currency_check_rejected_before_any_connection(monkeypatch, base_url, model):
    connections = []
    def forbidden(*args, **kwargs):
        connections.append((args, kwargs))
        raise AssertionError("no connection is authorized")
    monkeypatch.setattr(module.http.client, "HTTPSConnection", forbidden)
    monkeypatch.setattr(module.http.client, "HTTPConnection", forbidden)
    settings = SimpleNamespace(base_url=base_url, model=model, api_key="synthetic-campus-key", timeout_seconds=30)
    with pytest.raises(ValueError, match="selected_(endpoint|model)_price_unverified") as error:
        module.verify_cny_account(settings)
    assert not connections and settings.api_key not in str(error.value)
