"""豆包配置只使用临时合成凭据，不读取 .env 或用户真实密钥。"""

import importlib
from pathlib import Path
import sys

import pytest


SCRIPT_ROOT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi"
sys.path.insert(0, str(SCRIPT_ROOT))
config = importlib.import_module("doubao_realtime.config")


def test_default_path_and_offline_status_are_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("DOUBAO_API_KEY", "process-secret-must-not-be-used")
    path = tmp_path / ".env.doubao.local"
    status = config.config_status(path)
    assert status["configured"] is False
    assert status["missing"] == ["DOUBAO_API_KEY"]
    assert config.DEFAULT_CONFIG_PATH == SCRIPT_ROOT.parents[2] / ".env.doubao.local"
    with pytest.raises(config.ConfigError, match="缺少豆包配置文件"):
        config.load_config(path)
    assert not path.exists()


def test_roundtrip_save_keeps_key_private_and_preserves_other_fields(tmp_path):
    path = tmp_path / ".env.doubao.local"
    config.save_config(path, api_key="synthetic-key-1", speaker="S_synthetic",
                       instructions="以中文简洁回答。")
    first = config.load_config(path)
    assert first.api_key == "synthetic-key-1"
    assert first.speaker == "S_synthetic"
    assert first.url == config.OFFICIAL_URL
    assert first.output_sample_rate == 24000
    assert first.input_sample_rate == 16000
    assert "synthetic-key" not in repr(first)
    config.save_credentials(path, api_key="synthetic-key-2")
    updated = config.load_config(path)
    assert updated.api_key == "synthetic-key-2"
    assert updated.instructions == first.instructions
    assert updated.speaker == first.speaker
    assert config.config_status(path) == {"configured": True, "missing": [], "error": ""}
    assert not list(tmp_path.glob(".doubao-*.tmp"))


@pytest.mark.parametrize("content", [
    "DOUBAO_API_KEY=synthetic-secret\nDOUBAO_API_KEY=other",
    "OTHER_SECRET=synthetic-secret",
    "DOUBAO_API_KEY=\"synthetic-secret\\nsecond-line\"",
    "DOUBAO_API_KEY=$(synthetic-secret)",
    "DOUBAO_API_KEY=${synthetic-secret}",
    "DOUBAO_API_KEY=`synthetic-secret`",
    "DOUBAO_API_KEY=\"synthetic-secret",
    "DOUBAO_API_KEY=[synthetic-secret] \nDOUBAO_WS_URL=wss://evil.invalid",
    "DOUBAO_API_KEY=synthetic-secret\nDOUBAO_MODEL=legacy-version",
])
def test_invalid_dotenv_never_discloses_value(tmp_path, content):
    path = tmp_path / ".env.doubao.local"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(config.ConfigError) as error:
        config.load_config(path)
    assert "synthetic-secret" not in str(error.value)
    assert "synthetic-secret" not in str(config.config_status(path))


@pytest.mark.parametrize("value", ["", "secret\r\nOTHER=x", "secret\x00", "secret space"])
def test_invalid_credential_save_preserves_existing_file(tmp_path, value):
    path = tmp_path / ".env.doubao.local"
    config.save_credentials(path, api_key="synthetic-original")
    original = path.read_bytes()
    with pytest.raises(config.ConfigError):
        config.save_credentials(path, api_key=value)
    assert path.read_bytes() == original


def test_failed_atomic_replace_preserves_existing_configuration(tmp_path, monkeypatch):
    path = tmp_path / ".env.doubao.local"
    config.save_credentials(path, api_key="synthetic-original")
    original = path.read_bytes()

    def fail(*args):
        raise OSError("synthetic-private-platform-message")

    monkeypatch.setattr(config.os, "replace", fail)
    with pytest.raises(config.ConfigError, match="无法保存豆包配置文件") as error:
        config.save_credentials(path, api_key="synthetic-new")
    assert "private-platform" not in str(error.value)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".doubao-*.tmp"))


def test_missing_key_can_be_saved_into_a_template(tmp_path):
    path = tmp_path / ".env.doubao.local"
    path.write_text("# 本地模板\nDOUBAO_API_KEY=\nDOUBAO_SPEAKER='S_synthetic'\n", encoding="utf-8")
    config.save_credentials(path, api_key="synthetic-key")
    assert config.load_config(path).speaker == "S_synthetic"
