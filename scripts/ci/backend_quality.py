"""不依赖圆屏/模型/个人配置的后端质量入口，并拒绝意外跳过测试。"""

import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from backend_resources import declared_skips


ROOT = Path(__file__).resolve().parents[2]
TEST_PATHS = ("tests",)
# 精确用例与精确资源原因同时匹配；声明依赖缺失不能冒充资源不可用。
SKIP_REASON_SUBSTRINGS = declared_skips()
ALLOWED_SKIPS = set(SKIP_REASON_SUBSTRINGS)


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
    # 这些是锁定的合成测试依赖；缺失必须失败，不能落入专属模型/SDK例外。
    import requests  # noqa: F401
    import numpy  # noqa: F401
    import yaml  # noqa: F401
    import pytest

    if not Path(longmemory.__file__).resolve().is_relative_to(ROOT / "src"):
        raise RuntimeError("longmemory 源码不属于当前检出")
    os.chdir(ROOT)
    report = ROOT / "data/test-tmp/ci/backend.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    result = pytest.main([
        *TEST_PATHS, "-q", f"--junitxml={report}",
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
