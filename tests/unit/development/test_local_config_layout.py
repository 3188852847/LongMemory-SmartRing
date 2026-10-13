"""配置搬迁只使用合成文件；不读真实凭据、数据库或日用服务。"""
from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/development/xiaozhi"))
import config_paths
import sync_vad_config
import setup
sys.path.pop(0)

spec = importlib.util.spec_from_file_location("migrate_local_config_test", ROOT / "scripts/development/migrate_local_config.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def write(root, relative, content=b"SYNTHETIC_SECRET\r\n# comment\r\n"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def server(root):
    return root / migration.SERVER


def test_migration_preserves_exact_bytes_and_repeats_without_root_sources(tmp_path):
    expected = {}
    for old, new, _ in migration.PAIRS:
        content = b"SYNTHETIC_ONLY" + old.encode("utf-8")
        write(tmp_path, old, content)
        expected[new] = content
    assert len(migration.plan(tmp_path)) == 11
    result = migration.apply(tmp_path, services_stopped=True)
    assert result["migrated"] == 11
    for relative, content in expected.items():
        assert (tmp_path / relative).read_bytes() == content
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "data/control/launcher.json").exists()
    assert (server(tmp_path) / "data/.config.yaml").exists()
    assert migration.plan(tmp_path) == []
    assert "SYNTHETIC_ONLY" not in (tmp_path / result["receipt"]).read_text(encoding="utf-8")


def test_plan_is_read_only_and_apply_requires_stopped_services(tmp_path):
    write(tmp_path, ".env")
    migration.plan(tmp_path)
    assert not (tmp_path / "local").exists()
    with pytest.raises(ValueError, match="services_must_be_stopped"):
        migration.apply(tmp_path)
    assert not (tmp_path / "local").exists()


def test_collision_refuses_entire_batch_before_first_move(tmp_path):
    first = write(tmp_path, ".env")
    write(tmp_path, ".env.deepseek.local")
    target = write(tmp_path, "local/config/.env.deepseek.local", b"NEWER_PRIVATE")
    with pytest.raises(ValueError, match="migration_destination_exists"):
        migration.apply(tmp_path, services_stopped=True)
    assert first.exists()
    assert target.read_bytes() == b"NEWER_PRIVATE"


def test_rollback_restores_originals_and_preserves_yaml_copy_in_archive(tmp_path):
    write(tmp_path, ".env")
    write(tmp_path, migration.SERVER + "/data/.config.yaml")
    result = migration.apply(tmp_path, services_stopped=True)
    receipt = tmp_path / result["receipt"]
    migration.rollback(tmp_path, receipt)
    assert (tmp_path / ".env").read_bytes() == b"SYNTHETIC_SECRET\r\n# comment\r\n"
    assert not (tmp_path / "local/config/.env").exists()
    assert not (tmp_path / "local/config/xiaozhi.yaml").exists()
    assert (receipt.parent / (receipt.stem + "-xiaozhi.yaml")).exists()
    assert json.loads(receipt.read_text(encoding="utf-8"))["state"] == "rolled_back"


def test_rollback_rejects_changed_canonical_before_any_move(tmp_path):
    write(tmp_path, ".env")
    write(tmp_path, ".env.deepseek.local")
    result = migration.apply(tmp_path, services_stopped=True)
    write(tmp_path, "local/config/.env.deepseek.local", b"LATER_USER_EDIT")
    with pytest.raises(ValueError, match="canonical_config_changed"):
        migration.rollback(tmp_path, tmp_path / result["receipt"])
    assert not (tmp_path / ".env").exists()
    assert (tmp_path / "local/config/.env.deepseek.local").read_bytes() == b"LATER_USER_EDIT"


def test_failed_move_rolls_back_only_this_transaction(tmp_path, monkeypatch):
    write(tmp_path, ".env")
    write(tmp_path, ".env.deepseek.local")
    real_rename = Path.rename
    def fail_second(path, destination):
        if path.name == ".env.deepseek.local":
            raise OSError("synthetic failure")
        return real_rename(path, destination)
    monkeypatch.setattr(Path, "rename", fail_second)
    with pytest.raises(OSError):
        migration.apply(tmp_path, services_stopped=True)
    assert (tmp_path / ".env").exists()
    assert (tmp_path / ".env.deepseek.local").exists()
    assert not (tmp_path / "local/config/.env").exists()


def test_copy_validation_failure_archives_partial_and_restores_env(tmp_path, monkeypatch):
    write(tmp_path, ".env")
    yaml_source = write(tmp_path, migration.SERVER + "/data/.config.yaml")
    original = yaml_source.read_bytes()
    real_read = Path.read_bytes
    reads = 0
    def truncated_copy(path):
        nonlocal reads
        if path == yaml_source:
            reads += 1
            if reads == 3:  # plan、写前摘要后，模拟读取/写入阶段截断。
                return original[:3]
        return real_read(path)
    monkeypatch.setattr(Path, "read_bytes", truncated_copy)
    with pytest.raises(ValueError, match="config_changed_before_migration"):
        migration.apply(tmp_path, services_stopped=True)
    assert (tmp_path / ".env").exists()
    assert not (tmp_path / "local/config/xiaozhi.yaml").exists()
    assert list((tmp_path / "local/archive/config-migrations").glob("*-partial-*"))
    assert yaml_source.read_bytes() == original


def test_receipt_failure_after_move_still_restores_original(tmp_path, monkeypatch):
    write(tmp_path, ".env")
    real_write = migration._write_receipt
    failed = False
    def fail_after_move(path, body):
        nonlocal failed
        if body["completed"] and body["state"] == "prepared" and not failed:
            failed = True
            raise OSError("synthetic receipt failure")
        return real_write(path, body)
    monkeypatch.setattr(migration, "_write_receipt", fail_after_move)
    with pytest.raises(OSError):
        migration.apply(tmp_path, services_stopped=True)
    assert (tmp_path / ".env").exists()
    assert not (tmp_path / "local/config/.env").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction validation")
def test_windows_junction_is_rejected_without_touching_its_target(tmp_path):
    outside = tmp_path / "private-outside"
    write(outside, ".env", b"SYNTHETIC_JUNCTION_SECRET")
    project = tmp_path / "project"
    project.mkdir()
    link = project / "local"
    command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "mklink", "/J", str(link), str(outside)]
    result = subprocess.run(command, capture_output=True, timeout=10)
    assert result.returncode == 0
    try:
        with pytest.raises(ValueError, match="unsafe_migration_path"):
            migration.plan(project)
        with pytest.raises(ValueError, match="unsafe_config_path"):
            config_paths.config_path(server(project))
        assert (outside / ".env").read_bytes() == b"SYNTHETIC_JUNCTION_SECRET"
    finally:
        # 仅移除本测试创建的空联接入口；目标仍在本进程合成临时目录内。
        link.rmdir()


def test_migration_rejects_escape_and_symlink(tmp_path):
    with pytest.raises(ValueError):
        migration.safe_path(tmp_path, "../outside/config")
    outside = write(tmp_path.parent, tmp_path.name + "-outside.env")
    try:
        (tmp_path / ".env").symlink_to(outside)
    except OSError:
        pytest.skip("host does not grant synthetic symlink creation")
    with pytest.raises(ValueError, match="unsafe_migration_path"):
        migration.plan(tmp_path)
    assert outside.read_bytes() == b"SYNTHETIC_SECRET\r\n# comment\r\n"


def test_managed_and_explicit_external_instances_stay_separate(tmp_path):
    managed = server(tmp_path)
    external = tmp_path / "explicit-instance"
    assert config_paths.config_path(managed) == tmp_path / "local/config/xiaozhi.yaml"
    assert config_paths.config_path(external) == external / "data/.config.yaml"
    assert config_paths.render_runtime_config(external) == {"managed": False}


def test_generation_repeats_and_archives_old_output_after_canonical_edit(tmp_path):
    canonical = write(tmp_path, "local/config/xiaozhi.yaml")
    target = write(tmp_path, migration.SERVER + "/data/.config.yaml")
    first = config_paths.render_runtime_config(server(tmp_path))
    assert config_paths.render_runtime_config(server(tmp_path)) == first
    original = canonical.read_bytes()
    canonical.write_bytes(b"SYNTHETIC_UPDATED\n")
    result = config_paths.render_runtime_config(server(tmp_path))
    assert result["sha256"] != first["sha256"]
    assert target.read_bytes() == canonical.read_bytes()
    archives = list((tmp_path / "local/archive/config-generated").glob("*.yaml"))
    assert len(archives) == 1 and archives[0].read_bytes() == original
    assert "SYNTHETIC" not in target.with_name(".config.source.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("marked", [False, True])
def test_generation_refuses_manual_runtime_edit(tmp_path, marked):
    write(tmp_path, "local/config/xiaozhi.yaml")
    target = write(tmp_path, migration.SERVER + "/data/.config.yaml")
    if marked:
        config_paths.render_runtime_config(server(tmp_path))
    target.write_bytes(b"MANUAL_RUNTIME_EDIT")
    with pytest.raises(ValueError, match="runtime_config_changed|unmanaged_runtime_config"):
        config_paths.render_runtime_config(server(tmp_path))
    assert target.read_bytes() == b"MANUAL_RUNTIME_EDIT"


def test_ui_sync_changes_canonical_then_generation_updates_vendor(tmp_path):
    yaml = pytest.importorskip("yaml")
    old = (b"# keep text\nVAD:\n  SileroVAD:\n    type: silero\n"
           b"    threshold: 0.5\n    threshold_low: 0.3\n    min_silence_duration_ms: 600\n"
           b"private_note: SYNTHETIC_ONLY\n")
    canonical = write(tmp_path, "local/config/xiaozhi.yaml", old)
    target = write(tmp_path, migration.SERVER + "/data/.config.yaml", old)
    config_paths.render_runtime_config(server(tmp_path))
    checked = sync_vad_config.sync(server(tmp_path), {"action": "check", "profile": "noisy"})
    changed = sync_vad_config.sync(server(tmp_path), {"action": "apply", "profile": "noisy", "expected_digest": checked["digest"]})
    assert target.read_bytes() == old
    assert yaml.safe_load(canonical.read_bytes())["VAD"]["SileroVAD"]["threshold"] == 0.7
    assert yaml.safe_load(canonical.read_bytes())["private_note"] == "SYNTHETIC_ONLY"
    assert (tmp_path / "local/archive/config-backups" / changed["backup"]).read_bytes() == old
    config_paths.render_runtime_config(server(tmp_path))
    assert target.read_bytes() == canonical.read_bytes()


def test_new_managed_init_uses_public_template_without_vendor_write(tmp_path):
    write(tmp_path, migration.SERVER + "/app.py", b"# synthetic upstream")
    target = setup.init_config(server(tmp_path))
    assert target == tmp_path / "local/config/xiaozhi.yaml"
    assert target.read_bytes() == (ROOT / "config/examples/xiaozhi.example.yaml").read_bytes()
    assert not (server(tmp_path) / "data/.config.yaml").exists()
