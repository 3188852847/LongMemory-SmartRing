"""不依赖圆屏/模型/个人配置的后端质量入口，并拒绝意外跳过测试。"""

import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
TEST_PATHS = ("tests",)
# 只允许这些需要另行下载专属资源的验收跳过；依赖安装失败不能伪装成绿色。
ALLOWED_SKIPS = {
    ("tests.integration.device_control.test_transport", "test_real_http_and_upstream_mcp_with_simulated_device"),
    ("tests.integration.memory_pipeline.test_xiaozhi_bridge", "test_real_upstream_dialogue_injects_context_if_available"),
    ("tests.integration.memory_pipeline.test_xiaozhi_bridge", "test_python310_provider_calls_python312_worker_if_available"),
    ("tests.unit.infrastructure.test_round_wallpaper_library", "test_library_real_ffmpeg_roundtrip_when_local_tools_exist"),
}
# 这些模块属于语音运行环境，PyYAML 没有在主项目 console/dev 中声明。
# 允许精确模块的 collection skip，其他任何模块缺依赖仍然失败。
ALLOWED_SKIPS.update(("", f"tests.unit.development.{name}") for name in (
    "test_sync_memory_config", "test_sync_model_config", "test_sync_role",
    "test_sync_tts_backend", "test_sync_vad_config", "test_voice_settings",
))
ALLOWED_SKIPS.update(("tests.unit.development.test_launcher", name) for name in (
    "test_network_sync_preserves_other_configuration_and_backups",
    "test_network_sync_rejects_ambiguous_format",
))
SKIP_REASON_SUBSTRINGS = {
    ("tests.unit.development.test_local_config_layout", "test_migration_rejects_escape_and_symlink"):
        "host does not grant synthetic symlink creation",
    ("tests.unit.development.test_local_config_layout", "test_ui_sync_changes_canonical_then_generation_updates_vendor"):
        "could not import 'yaml'",
}
ALLOWED_SKIPS.update(SKIP_REASON_SUBSTRINGS)


def audit_report(path: Path) -> tuple[int, int]:
    """检查实际执行报告，避免 importorskip 掩盖 console 依赖缺失。"""
    cases = list(ET.parse(path).iter("testcase"))
    if not cases:
        raise ValueError("质量报告没有测试用例")
    skipped = 0
    for case in cases:
        identity = (case.get("classname", ""), case.get("name", ""))
        if case.find("failure") is not None or case.find("error") is not None:
            raise ValueError(f"质量报告含失败：{identity}")
        skip = case.find("skipped")
        if skip is not None:
            skipped += 1
            if identity not in ALLOWED_SKIPS:
                raise ValueError(f"出现未经声明的跳过：{identity}")
            expected_reason = SKIP_REASON_SUBSTRINGS.get(identity)
            if expected_reason and expected_reason not in skip.get("message", ""):
                raise ValueError(f"跳过原因与声明不符：{identity}")
    if len(cases) == skipped:
        raise ValueError("质量报告没有执行通过的测试")
    return len(cases) - skipped, skipped


def main() -> int:
    # 代码来源必须是当前检出，不能被本机另一工作树的 editable 安装覆盖。
    sys.path.insert(0, str(ROOT / "src"))
    import longmemory
    import aiohttp  # noqa: F401
    import pydantic  # noqa: F401
    import pytest

    if not Path(longmemory.__file__).resolve().is_relative_to(ROOT / "src"):
        raise RuntimeError("longmemory 源码不属于当前检出")
    os.chdir(ROOT)
    report = ROOT / "data/test-tmp/ci/backend.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    result = pytest.main([
        *TEST_PATHS, "-q", f"--junitxml={report}",
        "--ignore=tests/unit/development/test_cosyvoice_streaming.py",
        "--deselect=tests/unit/development/test_cosyvoice_segments.py::test_actual_v6_installer_keeps_each_drained_segment_separate",
    ])
    if result != 0:
        return int(result)
    passed, skipped = audit_report(report)
    message = f"后端合成质量检查：{passed} 通过，{skipped} 个已声明的专属资源验收跳过。"
    print(message)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(message + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
