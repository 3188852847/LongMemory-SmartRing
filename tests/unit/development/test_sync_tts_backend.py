"""使用合成 YAML 验证 TTS 切换，不读取真实小智私有配置。"""

import importlib.util
from pathlib import Path
import sys

import pytest

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = ROOT / "scripts/development/xiaozhi"
sys.path.insert(0, str(DIRECTORY))
spec = importlib.util.spec_from_file_location("sync_tts_backend_test", DIRECTORY / "sync_tts_backend.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
sys.path.pop(0)


def make_server(tmp_path):
    server = tmp_path / "server"; (server / "data").mkdir(parents=True)
    text = (
        "# retained\nselected_module:\n  TTS: EdgeTTS\n"
        "TTS:\n  EdgeTTS:\n    type: edge\n    voice: synthetic\n"
        "  CustomTTS:\n    type: custom\n    method: GET\n    url: http://old.invalid/speech\n"
        "    params:\n      input: old\n      response_format: mp3\n      stream: true\n"
        "      voice: retained\n    headers: {}\n    format: mp3\n    output_dir: tmp/\n"
        "LLM:\n  secret: SYNTHETIC_ONLY\n"
    )
    path = server / "data/.config.yaml"; path.write_text(text, encoding="utf-8")
    return server, path, text


def test_voxcpm_check_then_apply_changes_only_contract_fields(tmp_path):
    server, path, original = make_server(tmp_path)
    checked = module.sync(server, {"action": "check", "backend": "voxcpm2"})
    assert checked["config_matches"] is False and path.read_text(encoding="utf-8") == original
    result = module.sync(server, {"action": "apply", "backend": "voxcpm2",
                                  "expected_digest": checked["digest"]})
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    custom = config["TTS"]["CustomTTS"]
    assert config["selected_module"]["TTS"] == "CustomTTS"
    assert (custom["method"], custom["url"], custom["format"]) == ("POST", module.VOX_URL, "wav")
    assert custom["params"] | {"voice": "retained"} == custom["params"]
    assert custom["params"]["input"] == "{prompt_text}"
    assert custom["params"]["response_format"] == "wav" and custom["params"]["stream"] is False
    assert custom["tts_timeout"] == 90
    assert config["LLM"]["secret"] == "SYNTHETIC_ONLY" and "# retained" in path.read_text(encoding="utf-8")
    assert ".tts-" in result["backup"] and (path.parent / result["backup"]).read_text(encoding="utf-8") == original


def test_edge_restore_only_changes_selection_and_checks_digest(tmp_path):
    server, path, _ = make_server(tmp_path)
    text = path.read_text(encoding="utf-8").replace("TTS: EdgeTTS", "TTS: CustomTTS")
    path.write_text(text, encoding="utf-8")
    checked = module.sync(server, {"action": "check", "backend": "edge"})
    with pytest.raises(ValueError):
        module.sync(server, {"action": "apply", "backend": "edge", "expected_digest": "0" * 64})
    module.sync(server, {"action": "apply", "backend": "edge", "expected_digest": checked["digest"]})
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["selected_module"]["TTS"] == "EdgeTTS"


def test_minimal_private_override_can_add_custom_tts(tmp_path):
    server = tmp_path / "server"; (server / "data").mkdir(parents=True)
    path = server / "data/.config.yaml"
    original = ("selected_module:\n  TTS: EdgeTTS\nTTS:\n  EdgeTTS:\n"
                "    type: edge\n    voice: synthetic\nLLM:\n  secret: SYNTHETIC_ONLY\n")
    path.write_text(original, encoding="utf-8")
    edge = module.sync(server, {"action": "check", "backend": "edge"})
    assert edge["config_matches"] is True and path.read_text(encoding="utf-8") == original
    checked = module.sync(server, {"action": "check", "backend": "voxcpm2"})
    module.sync(server, {"action": "apply", "backend": "voxcpm2",
                         "expected_digest": checked["digest"]})
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert config["selected_module"]["TTS"] == "CustomTTS"
    assert config["TTS"]["CustomTTS"]["url"] == module.VOX_URL
    assert config["LLM"]["secret"] == "SYNTHETIC_ONLY"


def test_sanotts_uses_separate_fixed_loopback_endpoint(tmp_path):
    server, path, _ = make_server(tmp_path)
    checked = module.sync(server, {"action": "check", "backend": "sanotts"})
    result = module.sync(server, {"action": "apply", "backend": "sanotts",
                                  "expected_digest": checked["digest"]})
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert config["TTS"]["CustomTTS"]["url"] == module.SANO_URL
    assert result["service_url"] == module.SANO_URL
