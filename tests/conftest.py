"""pytest 公共环境入口；只修正测试进程，不改变应用或系统配置。"""

import os
import shutil
import sys
import uuid
from pathlib import Path


_owned_test_temp: Path | None = None


def pytest_configure(config):
    """给每个 pytest 进程分配自己的项目内临时目录。

    不能在 pyproject.toml 中固定 ``--basetemp=.pytest-tmp``：两个测试进程
    并行时，后启动的进程会清理前一个仍在使用的 SQLite 文件。这里既避开
    Windows 用户临时目录的 ACL 问题，也不会让不同测试进程互相破坏。
    显式传入 ``--basetemp`` 时尊重调用者选择，便于故障排查。
    """
    global _owned_test_temp
    if config.option.basetemp is not None:
        # pytest 创建 basetemp 自身时不会递归创建父目录。显式传入项目内
        # ``.test-tmp/run-name`` 在全新检出中会因此整套夹具初始化失败；这里
        # 只补父目录，不预建或清空 pytest 将接管的目标目录。
        Path(config.option.basetemp).resolve().parent.mkdir(parents=True, exist_ok=True)
        return
    run_name = f"run-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    _owned_test_temp = Path(config.rootpath) / ".pytest-tmp" / run_name
    _owned_test_temp.parent.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(_owned_test_temp)


def pytest_unconfigure(config):
    """正常结束时只清理本进程拥有的目录；异常残留仍被 Git 忽略。"""
    del config
    global _owned_test_temp
    if _owned_test_temp is None:
        return
    shutil.rmtree(_owned_test_temp, ignore_errors=True)
    try:
        _owned_test_temp.parent.rmdir()
    except OSError:
        pass
    _owned_test_temp = None


if sys.platform == "win32":
    # uv 管理的 Python 位于含中文目录时，Tk 有时不能自行定位 init.tcl。
    # 当前 Windows 嵌入式解释器的 sys.base_prefix 可能已经把中文变成乱码；
    # 虚拟环境自己的 pyvenv.cfg 仍是 UTF-8，因此优先从那里取真实 home。
    base = Path(sys.base_prefix)
    config = Path(sys.prefix) / "pyvenv.cfg"
    try:
        home = next(
            line.split("=", 1)[1].strip()
            for line in config.read_text(encoding="utf-8").splitlines()
            if line.lower().startswith("home =")
        )
        configured = Path(home)
        if configured.is_dir():
            base = configured
    except (OSError, StopIteration, UnicodeError):
        pass
    tcl_root = base / "tcl"
    for name, directory in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
        candidate = tcl_root / directory
        if candidate.is_dir():
            os.environ.setdefault(name, str(candidate))
