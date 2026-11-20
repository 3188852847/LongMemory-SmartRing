"""用合成 YAML 验证圆屏记忆后端切换，不接触个人记忆或真实配置。"""

import importlib.util
import sys
from pathlib import Path

import pytest


yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts/development/xiaozhi"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "sync_memory_config_test", SCRIPTS / "sync_memory_config.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sys.path.pop(0)


def config_text():
    return (
        "# keep this comment\n"
        "selected_module:\n  Memory: LongMemory\n"
        "Memory:\n"
        "  nomem:\n    type: nomem\n"
        "  LongMemory:\n    type: longmemory\n"
        "    allowed_device_id: aa:bb:cc:dd:ee:ff\n"
        "    python_executable: D:/project/.venv/Scripts/python.exe\n"
        "    project_root: D:/project\n"
        "    database_path: D:/project/data/databases/example.db\n"
        "    audit_log: D:/project/data/logs/example.jsonl\n"
        "unrelated:\n  keep: true\n"
    )


def test_startup_repairs_only_the_selected_provider(tmp_path):
    server = tmp_path / "server"
    (server / "data").mkdir(parents=True)
    path = server / "data/.config.yaml"
    original = config_text().replace("Memory: LongMemory", "Memory: nomem")
    path.write_text(original, encoding="utf-8")
    checked = module.action(server, "hy_memory")
    result = module.action(server, "hy_memory", apply=True, expected_digest=checked["digest"])
    expected = yaml.safe_load(original)
    expected["selected_module"]["Memory"] = "LongMemory"
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == expected
    assert (path.parent / result["backup"]).read_text(encoding="utf-8") == original


@pytest.mark.parametrize("retired", ["longmemory", "xiaozhi_local", "none"])
def test_old_profiles_are_rejected(tmp_path, retired):
    with pytest.raises(ValueError, match="unknown_profile"):
        module.action(tmp_path, retired)
