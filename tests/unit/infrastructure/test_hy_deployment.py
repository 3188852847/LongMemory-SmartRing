"""固定私有配置入口的合成验证；不运行解释器或读取任何私有配置。"""

from hashlib import sha256
import json
from dataclasses import asdict

import pytest

from longmemory.infrastructure.config.hy_deployment import load_hy_deployment, build_daily_hy_runtime
from longmemory.methods.hy_memory.settings import HySettings


def setup_config(root):
    python = root / "local/runtime/hy-memory/.venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"synthetic-interpreter-identity-only-not-executable")
    settings = HySettings(user_id="synthetic", model_mode="synthetic_transport")
    directory = root / "local/config/hy-memory"
    directory.mkdir(parents=True)
    (directory / "settings.json").write_text(json.dumps(asdict(settings)))
    data = {"version": 1, "python": python.relative_to(root).as_posix(), "python_version": "3.12.13",
        "python_sha256": sha256(python.read_bytes()).hexdigest(),
        "state_directory": "data/memory/hy-daily", "source_path": "data/databases/hy-sources.db",
        "settings_identity": settings.identity()}
    path = directory / "deployment.json"
    path.write_text(json.dumps(data))
    return data, path, settings


def test_fixed_files_explicit_paths_and_pinned_identity_without_implicit_creation(tmp_path):
    _, _, settings = setup_config(tmp_path)
    deployment = load_hy_deployment(tmp_path)
    assert deployment.settings.identity() == settings.identity()
    assert deployment.state_directory == tmp_path / "data/memory/hy-daily"
    assert not deployment.state_directory.exists() and not deployment.source_path.exists()


def test_failed_empty_database_reopen_preserves_current_selection(tmp_path, monkeypatch):
    from longmemory.infrastructure.config.hy_deployment import reset_daily_hy_memory
    from longmemory.methods.hy_memory.assembly import HyState
    from types import SimpleNamespace

    _, pointer, settings = setup_config(tmp_path)
    old = load_hy_deployment(tmp_path)
    state = HyState(old.state_directory, settings, create=True)
    (state.root / "sdk" / "synthetic").write_bytes(b"original")
    state.ready()
    original = pointer.read_bytes()
    calls = []

    def build(root, deployment, *, create=False, reuse_budget=False):
        assert deployment.state_directory != old.state_directory
        calls.append((create, reuse_budget))
        if not create:
            raise ValueError("synthetic_reopen_failure")
        return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr("longmemory.bootstrap_hy_daily.build_owned_daily_runtime", build)
    with pytest.raises(ValueError, match="synthetic_reopen_failure"):
        reset_daily_hy_memory(tmp_path, sha256(original).hexdigest())
    assert calls == [(True, True), (False, False)]
    assert pointer.read_bytes() == original
    assert (state.root / "sdk" / "synthetic").read_bytes() == b"original"


def test_daily_entry_rejects_offline_or_simulated_models_before_initializing_state(tmp_path):
    setup_config(tmp_path)
    with pytest.raises(ValueError, match="real_model_configuration_required"):
        build_daily_hy_runtime(tmp_path, create=True)
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("flag", ["management_writes_enabled", "management_exclusive_profile"])
def test_daily_settings_cannot_self_authorize_management_without_trusted_receipt(tmp_path, flag):
    setup_config(tmp_path)
    path = tmp_path / "local/config/hy-memory/settings.json"
    settings = json.loads(path.read_text()); settings[flag] = True
    path.write_text(json.dumps(settings))
    with pytest.raises(ValueError, match="management_flags_require_verification"):
        load_hy_deployment(tmp_path)
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("value", [True, 1, "background"])
def test_daily_background_priority_is_set_only_by_owned_bootstrap_not_saved_settings(tmp_path,value):
    setup_config(tmp_path)
    path = tmp_path / "local/config/hy-memory/settings.json"
    settings = json.loads(path.read_text()); settings["background_priority_enabled"] = value
    path.write_text(json.dumps(settings))
    with pytest.raises(ValueError,match="background_flag_requires_owned_bootstrap"):
        load_hy_deployment(tmp_path)
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("change", [
    {"version": 2}, {"url": "https://forbidden.invalid"},
    {"python_version": "3.10.20"},
    {"python": "../../python.exe"}, {"python": "C:/untrusted/python.exe"},
    {"source_path": "local/config/personal.db"},
    {"state_directory": "data/memory/../../local/model"},
    {"settings_identity": "0" * 64}, {"python_sha256": "0" * 64},
])
def test_deployment_rejects_arbitrary_targets_and_identity_changes(tmp_path, change):
    data, path, _ = setup_config(tmp_path)
    path.write_text(json.dumps(data | change))
    with pytest.raises(ValueError):
        load_hy_deployment(tmp_path)


@pytest.mark.parametrize("change", ["dimensions", "endpoint"])
def test_changed_model_dimension_or_endpoint_cannot_reopen_same_library(tmp_path, change):
    _, _, _ = setup_config(tmp_path)
    path = tmp_path / "local/config/hy-memory/settings.json"
    data = json.loads(path.read_text())
    if change == "dimensions":
        data["embedding_dimensions"] += 1
    else:
        data["embedding"]["base_url"] = "https://different.invalid/v1"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="model_identity_mismatch"):
        load_hy_deployment(tmp_path)
