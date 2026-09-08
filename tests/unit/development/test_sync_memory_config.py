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


def test_adds_local_summary_and_only_switches_provider(tmp_path):
    server = tmp_path / "server"
    (server / "data").mkdir(parents=True)
    path = server / "data/.config.yaml"
    original = config_text()
    path.write_text(original, encoding="utf-8")
    checked = module.action(server, "xiaozhi_local")
    assert checked["config_matches"] is False
    assert path.read_text(encoding="utf-8") == original
    result = module.action(server, "xiaozhi_local", apply=True,
                           expected_digest=checked["digest"])
    updated = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(updated)
    assert parsed["selected_module"]["Memory"] == "mem_local_short"
    assert parsed["Memory"]["mem_local_short"] == {
        "type": "mem_local_short", "llm": None,
    }
    assert parsed["Memory"]["LongMemory"]["database_path"].endswith("example.db")
    assert "# keep this comment" in updated and parsed["unrelated"] == {"keep": True}
    assert ".memory-" in result["backup"]
    assert (path.parent / result["backup"]).read_text(encoding="utf-8") == original


def test_switching_to_none_preserves_existing_local_and_longmemory_data_config(tmp_path):
    server = tmp_path / "server"
    (server / "data").mkdir(parents=True)
    path = server / "data/.config.yaml"
    path.write_text(config_text(), encoding="utf-8")
    first = module.action(server, "xiaozhi_local")
    module.action(server, "xiaozhi_local", apply=True, expected_digest=first["digest"])
    checked = module.action(server, "none")
    module.action(server, "none", apply=True, expected_digest=checked["digest"])
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert parsed["selected_module"]["Memory"] == "nomem"
    assert "LongMemory" in parsed["Memory"] and "mem_local_short" in parsed["Memory"]
