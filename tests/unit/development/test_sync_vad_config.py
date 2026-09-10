"""用合成配置验证 VAD 档位同步，不读取真实小智配置。"""

import importlib.util
from pathlib import Path
import sys

import pytest

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = ROOT / "scripts/development/xiaozhi"
sys.path.insert(0, str(DIRECTORY))
spec = importlib.util.spec_from_file_location("sync_vad_config_test", DIRECTORY / "sync_vad_config.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
sys.path.pop(0)


def make_server(tmp_path):
    server = tmp_path / "server"; (server / "data").mkdir(parents=True)
    text = (
        "# retained\nVAD:\n  SileroVAD:\n    type: silero\n"
        "    model_dir: models/synthetic\n    threshold: 0.5\n"
        "    threshold_low: 0.3\n    min_silence_duration_ms: 600\n"
        "LLM:\n  secret: SYNTHETIC_ONLY\n"
    )
    path = server / "data/.config.yaml"; path.write_text(text, encoding="utf-8")
    return server, path, text


def test_noisy_profile_checks_then_changes_only_vad_numbers(tmp_path):
    server, path, original = make_server(tmp_path)
    checked = module.sync(server, {"action": "check", "profile": "noisy"})
    assert checked["config_matches"] is False
    assert path.read_text(encoding="utf-8") == original
    changed = module.sync(server, {"action": "apply", "profile": "noisy",
                                   "expected_digest": checked["digest"]})
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key, value in module.PROFILES["noisy"].items():
        assert config["VAD"]["SileroVAD"][key] == value
    assert config["LLM"]["secret"] == "SYNTHETIC_ONLY"
    assert "# retained" in path.read_text(encoding="utf-8")
    assert ".vad-" in changed["backup"]


def test_rejects_unknown_profile_and_stale_digest(tmp_path):
    server, _, _ = make_server(tmp_path)
    with pytest.raises(ValueError):
        module.sync(server, {"action": "check", "profile": "maximum"})
    with pytest.raises(ValueError):
        module.sync(server, {"action": "apply", "profile": "close_talk",
                             "expected_digest": "0" * 64})
