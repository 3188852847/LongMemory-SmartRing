"""纯离线检查教学脚本，不运行第三方服务、不访问模型或读取真实密钥。"""

from contextlib import contextmanager
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/setup.py"
spec = importlib.util.spec_from_file_location("xiaozhi_setup", SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.fixture
def config():
    return {
        "server": {"ip": "127.0.0.1", "port": 8000, "http_port": 8003,
                   "websocket": "ws://127.0.0.1:8000/xiaozhi/v1/"},
        "selected_module": dict(VAD="SileroVAD", ASR="FunASR", LLM="CampusLLM",
                                TTS="EdgeTTS", Memory="nomem", Intent="nointent"),
        "LLM": {"CampusLLM": {"type": "openai", "base_url": "https://example.invalid/v1",
                              "api_key": "synthetic-key", "model_name": "synthetic-model"}},
    }


def test_local_config_is_accepted(config):
    assert setup.validate_config(config)["model_name"] == "synthetic-model"


def test_provider_instance_prefix_before_v1_is_accepted(config):
    config["LLM"]["CampusLLM"]["base_url"] = "http://example.invalid/instance-123/v1"
    assert setup.validate_config(config)["model_name"] == "synthetic-model"


@pytest.mark.parametrize("path", ["/v1/chat/completions", "/api", "/v10"])
def test_non_base_model_paths_are_rejected(config, path):
    config["LLM"]["CampusLLM"]["base_url"] = f"https://example.invalid{path}"
    with pytest.raises(setup.SetupError):
        setup.validate_config(config)


def test_voxcpm2_config_is_accepted_only_when_explicitly_selected(config):
    config["selected_module"]["TTS"] = "CustomTTS"
    config["TTS"] = {"CustomTTS": {
        "type": "custom", "method": "POST",
        "url": "http://127.0.0.1:18768/v1/audio/speech", "format": "wav",
        "params": {"input": "{prompt_text}", "response_format": "wav", "stream": False},
    }}
    assert setup.validate_config(config, tts_backend="voxcpm2")["model_name"] == "synthetic-model"
    with pytest.raises(setup.SetupError):
        setup.validate_config(config)


def test_voxcpm2_contract_rejects_wrong_local_endpoint(config):
    config["selected_module"]["TTS"] = "CustomTTS"
    config["TTS"] = {"CustomTTS": {
        "type": "custom", "method": "POST", "url": "http://example.invalid/speech",
        "format": "wav",
        "params": {"input": "{prompt_text}", "response_format": "wav", "stream": False},
    }}
    with pytest.raises(setup.SetupError):
        setup.validate_config(config, tts_backend="voxcpm2")


def test_sanotts_config_is_accepted_only_at_its_fixed_endpoint(config):
    config["selected_module"]["TTS"] = "CustomTTS"
    config["TTS"] = {"CustomTTS": {
        "type": "custom", "method": "POST",
        "url": setup.CUSTOM_TTS_URLS["sanotts"], "format": "wav",
        "params": {"input": "{prompt_text}", "response_format": "wav", "stream": False},
    }}
    setup.validate_config(config, tts_backend="sanotts")
    with pytest.raises(setup.SetupError):
        setup.validate_config(config, tts_backend="voxcpm2")


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.2"])
def test_non_local_listen_is_rejected(config, host):
    config["server"]["ip"] = host
    with pytest.raises(setup.SetupError):
        setup.validate_config(config)


@pytest.mark.parametrize("key,value", [("api_key", "FILL_LOCALLY"),
                                      ("base_url", "https://YOUR_MODEL_HOST/v1"),
                                      ("api_key", "${API_KEY}")])
def test_placeholders_are_rejected_without_echoing(config, key, value):
    config["LLM"]["CampusLLM"][key] = value
    with pytest.raises(setup.SetupError) as error:
        setup.validate_config(config)
    assert value not in str(error.value)


def test_http_needs_explicit_consent():
    model = {"base_url": "http://example.invalid/v1"}
    with pytest.raises(setup.SetupError):
        setup.require_transport_consent(model, False)
    setup.require_transport_consent(model, True)


def test_init_does_not_overwrite_private_config(tmp_path):
    (tmp_path / "app.py").touch()
    target = setup.init_config(tmp_path)
    assert "FILL_LOCALLY" in target.read_text(encoding="utf-8")
    target.write_text("keep-this", encoding="utf-8")
    with pytest.raises(FileExistsError):
        setup.init_config(tmp_path)
    assert target.read_text(encoding="utf-8") == "keep-this"


def fake_client(chunks, captured):
    @contextmanager
    def create(**kwargs):
        captured.update(kwargs)
        try:
            yield iter(chunks)
        finally:
            captured["closed"] = True
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_stream_counts_only_content_and_closes(config):
    captured = {}
    chunks = [SimpleNamespace(choices=[]),
              SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="连接成功"))])]
    assert setup.probe_stream(fake_client(chunks, captured), config["LLM"]["CampusLLM"]) == (1, 4)
    assert captured["stream"] is True
    assert captured["closed"] is True
    assert "api_key" not in captured


def test_empty_stream_is_not_success(config):
    captured = {}
    with pytest.raises(setup.SetupError):
        setup.probe_stream(fake_client([], captured), config["LLM"]["CampusLLM"])
    assert captured["closed"] is True


def test_environment_does_not_modify_parent(tmp_path, monkeypatch):
    ffmpeg = tmp_path / "ffmpeg"
    paths = [ffmpeg / "ffmpeg.exe", ffmpeg / "ffprobe.exe",
             tmp_path / "native/libopus-1.6.1/Library/bin/opus.dll",
             tmp_path / "models/SenseVoiceSmall/model.pt",
             tmp_path / "models/snakers4_silero-vad/src/silero_vad/data/silero_vad.onnx"]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.setenv("PATH", "original")
    env = setup.prepare_environment(tmp_path, ffmpeg)
    assert env["PATH"].endswith("original")
    assert setup.os.environ["PATH"] == "original"
    assert env["HF_HUB_OFFLINE"] == "1"


@pytest.fixture
def lan_config(config):
    config['server'].update(ip='192.168.124.45',
                            websocket='ws://192.168.124.45:8000/xiaozhi/v1/',
                            vision_explain='http://192.168.124.45:8003/mcp/vision/explain',
                            auth={'enabled': True, 'allowed_devices': []})
    return config


def test_lan_requires_explicit_matching_address(lan_config):
    setup.validate_config(lan_config, '192.168.124.45')
    with pytest.raises(setup.SetupError):
        setup.validate_config(lan_config)
    with pytest.raises(setup.SetupError):
        setup.validate_config(lan_config, '192.168.124.46')


@pytest.mark.parametrize('address', ['0.0.0.0', '127.0.0.1', '::', '8.8.8.8',
                                    '100.64.1.1', '169.254.1.2', '192.168.1.2/24'])
def test_lan_rejects_unspecified_public_and_non_host_addresses(address):
    with pytest.raises(setup.SetupError):
        setup.validate_lan_ip(address)


@pytest.mark.parametrize('auth', [{'enabled': False, 'allowed_devices': []},
                                 {'enabled': True, 'allowed_devices': ['test-device']},
                                 {'enabled': 'true', 'allowed_devices': []}])
def test_lan_rejects_disabled_auth_or_bypass_list(lan_config, auth):
    lan_config['server']['auth'] = auth
    with pytest.raises(setup.SetupError):
        setup.validate_config(lan_config, '192.168.124.45')


def test_lan_rejects_stale_advertised_url(lan_config):
    lan_config['server']['websocket'] = 'ws://127.0.0.1:8000/xiaozhi/v1/'
    with pytest.raises(setup.SetupError):
        setup.validate_config(lan_config, '192.168.124.45')


def test_ota_firmware_blocks_demo_without_deleting(tmp_path):
    setup.reject_ota_binaries(tmp_path)
    target = tmp_path / 'data/bin/demo_9.9.9.bin'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'keep')
    with pytest.raises(setup.SetupError):
        setup.reject_ota_binaries(tmp_path)
    assert target.read_bytes() == b'keep'


def test_install_memory_is_idempotent_and_preserves_other_content(tmp_path):
    base = tmp_path / 'core/providers/memory/base.py'
    base.parent.mkdir(parents=True)
    base.write_text('unchanged', encoding='utf-8')
    installed = setup.install_memory_provider(tmp_path)
    assert setup.install_memory_provider(tmp_path) == installed
    installed.write_text('user changes', encoding='utf-8')
    with pytest.raises(setup.SetupError):
        setup.install_memory_provider(tmp_path)
    assert installed.read_text(encoding='utf-8') == 'user changes'
    assert base.read_text(encoding='utf-8') == 'unchanged'


def test_update_memory_only_replaces_known_legacy_provider(tmp_path, monkeypatch):
    base = tmp_path / 'core/providers/memory/base.py'
    base.parent.mkdir(parents=True)
    base.write_text('unchanged', encoding='utf-8')
    target = tmp_path / 'core/providers/memory/longmemory/longmemory.py'
    target.parent.mkdir(parents=True)
    target.write_text('known legacy', encoding='utf-8')
    digest = __import__('hashlib').sha256(target.read_bytes()).hexdigest()
    monkeypatch.setattr(setup, 'LEGACY_MEMORY_PROVIDER_SHA256', {digest})
    setup.install_memory_provider(tmp_path, allow_known_update=True)
    assert target.read_bytes() == (SCRIPT.parent / 'longmemory_provider.py').read_bytes()
    assert base.read_text(encoding='utf-8') == 'unchanged'


def test_published_shared_runtime_provider_is_a_known_upgrade_source():
    """固定实机曾安装的发布版身份，避免以后误删受控升级路径。"""
    assert (
        '005104cc605aa05ad834774d649a0d088bf450bcc7040e44d0e40a2964d9be52'
        in setup.LEGACY_MEMORY_PROVIDER_SHA256
    )
    assert (
        '28969e5bee2c97cbe5c3798ebb80fe5075f6b218e0b1f2fec03e60a2d8ad1357'
        in setup.LEGACY_MEMORY_PROVIDER_SHA256
    )


def test_longmemory_config_requires_prompt_slot_and_explicit_device(config, tmp_path):
    config['selected_module']['Memory'] = 'LongMemory'
    config['Memory'] = {'LongMemory': dict(
        type='longmemory', allowed_device_id='aa:bb:cc:dd:ee:ff',
        python_executable=str(tmp_path / 'python.exe'), project_root=str(tmp_path),
        database_path=str(tmp_path / 'demo.db'), audit_log=str(tmp_path / 'audit.jsonl'),
    )}
    with pytest.raises(setup.SetupError):
        setup.validate_config(config)
    config['prompt'] = '只依据记忆证据回答。<memory></memory>'
    setup.validate_config(config)
    config['Memory']['LongMemory']['allowed_device_id'] = ''
    with pytest.raises(setup.SetupError):
        setup.validate_config(config)
