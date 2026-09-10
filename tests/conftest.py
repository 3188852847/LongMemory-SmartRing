"""pytest 公共环境入口；只修正测试进程，不改变应用或系统配置。"""

import os
import sys
from pathlib import Path


if sys.platform == "win32":
    # uv 管理的 Python 位于含中文目录时，Tk 有时不能自行定位 init.tcl。
    # 只在当前解释器确实带有对应运行库时补全；保留调用者显式配置。
    tcl_root = Path(sys.base_prefix) / "tcl"
    for name, directory in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
        candidate = tcl_root / directory
        if candidate.is_dir():
            os.environ.setdefault(name, str(candidate))
