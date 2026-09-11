"""pytest 公共环境入口；只修正测试进程，不改变应用或系统配置。"""

import os
import sys
from pathlib import Path


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
