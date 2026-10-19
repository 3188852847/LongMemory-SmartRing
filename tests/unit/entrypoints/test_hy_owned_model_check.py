import asyncio
from longmemory.entrypoints.api import xiaozhi_model_profiles as module


def test_voice_connection_check_uses_owned_budget_gateway(monkeypatch, tmp_path):
    owned_settings = object()
    calls = []

    class Profiles:
        def selected(self, target):
            assert target == "voice"
            return "selected-profile"

        def settings(self, profile):
            raise AssertionError("the direct supplier configuration must not be consumed")

    class Generator:
        def __init__(self, settings):
            assert settings is owned_settings

        def generate(self, **arguments):
            calls.append(arguments)
            return "连接正常"

    monkeypatch.setattr(module, "OpenAICompatibleAnswerGenerator", Generator)
    profiles = module.XiaozhiModelProfiles(
        tmp_path, tmp_path, Profiles(), model_settings_factory=lambda: owned_settings,
    )
    result = asyncio.run(profiles.check())
    assert result["state"] == "available"
    assert calls == [{"query": "请只回复：连接正常", "memory_context": ""}]
