"""中文目录恢复后，Git 输出不能依赖 Windows 的默认代码页。"""

import subprocess
import sys

from longmemory.evaluation import runner


def test_provenance_accepts_utf8_git_paths_with_gbk_default(monkeypatch):
    original = subprocess.check_output
    monkeypatch.setattr(subprocess, "_text_encoding", lambda: "gbk")

    def git_output(command, **kwargs):
        output = "a" * 40 + "\n" if command[1] == "rev-parse" else "?? 启动智慧圆屏.cmd\n"
        # 实际经过子进程字节流和 subprocess 解码，覆盖 UTF-8/GBK 不一致。
        script = f"import sys; sys.stdout.buffer.write({output.encode('utf-8')!r})"
        return original([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(runner.subprocess, "check_output", git_output)
    result = runner.provenance()
    assert result["commit"] == "a" * 40
    assert result["dirty"] is True
    assert len(result["source_sha256"]) == 64
