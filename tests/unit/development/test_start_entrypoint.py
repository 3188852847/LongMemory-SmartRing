"""在合成项目中验证 CMD 入口；不打开真实启动器或访问日用服务。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[3]
USER_ENTRY = Path("启动智慧圆屏.cmd")
INTERNAL_ENTRY = Path("scripts/development/launcher/Start.cmd")
WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="需要 Windows CMD")


def test_root_has_one_daily_entrypoint():
    assert (ROOT / USER_ENTRY).is_file()
    assert (ROOT / INTERNAL_ENTRY).is_file()
    assert not (ROOT / "Start.cmd").exists()


def _synthetic_project(tmp_path, name):
    """只复制两个入口，启动目标完全替换为写入合成证据的短程序。"""
    project = tmp_path / name
    (project / INTERNAL_ENTRY).parent.mkdir(parents=True)
    for entry in (USER_ENTRY, INTERNAL_ENTRY):
        shutil.copyfile(ROOT / entry, project / entry)
    target = project / "scripts/development/launcher/app.py"
    target.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "root = Path(__file__).resolve().parents[3]\n"
        "(root / 'started.json').write_text(json.dumps({\n"
        "    'python': sys.executable, 'argv': sys.argv, 'cwd': str(Path.cwd())\n"
        "}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    return project


def _run_entry(project, entry, cwd):
    # 禁用 CMD AutoRun；从项目外调用，排除依赖当前工作目录的错误实现。
    # CMD 不使用 C 程序的反斜杠引号规则，传原始命令行以保留路径引号。
    command = os.environ.get("COMSPEC", "cmd.exe")
    return subprocess.run(
        f'"{command}" /d /c call "{project / entry}"',
        cwd=cwd,
        input="\n",
        capture_output=True,
        text=True,
        errors="replace",
        timeout=15,
    )


@WINDOWS_ONLY
@pytest.mark.parametrize("entry", [USER_ENTRY, INTERNAL_ENTRY])
@pytest.mark.parametrize("name", ["中文 project path", "中文 & (project path)"])
def test_entry_starts_only_synthetic_target(tmp_path, entry, name):
    project = _synthetic_project(tmp_path, name)
    scripts = project / ".venv/Scripts"
    scripts.mkdir(parents=True)
    # 复用现有解释器的无窗口启动壳与版本定位配置，不复制依赖或产品代码。
    # 合成环境唯一可执行目标是上面写入的短程序，不会打开 Tk 窗口。
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    config = Path(sys.prefix) / "pyvenv.cfg"
    if not pythonw.is_file() or not config.is_file():
        pytest.skip("运行此验证需要现有 Windows 项目虚拟环境")
    shutil.copyfile(pythonw, scripts / "pythonw.exe")
    shutil.copyfile(config, project / ".venv/pyvenv.cfg")
    caller = tmp_path / "其他 caller path"
    caller.mkdir()

    result = _run_entry(project, entry, caller)
    assert result.returncode == 0, result.stdout + result.stderr
    marker = project / "started.json"
    # START 为异步启动，等待合成程序留下证据；期限防止错误路径无限挂起。
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            observed = json.loads(marker.read_text(encoding="utf-8"))
            break
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.05)
    else:
        pytest.fail(f"合成启动目标未执行：{result.stdout}{result.stderr}")
    assert Path(observed["python"]).resolve() == (scripts / "pythonw.exe").resolve()
    assert observed["argv"] == [str(project / "scripts/development/launcher/app.py")]
    assert Path(observed["cwd"]).resolve() == caller.resolve()


@WINDOWS_ONLY
@pytest.mark.parametrize("entry", [USER_ENTRY, INTERNAL_ENTRY])
def test_missing_environment_keeps_hint_and_failure_status(tmp_path, entry):
    project = _synthetic_project(tmp_path, "缺少环境 project path")
    result = _run_entry(project, entry, tmp_path)
    assert result.returncode == 1
    assert "Project Python environment not found. See docs/guides." in result.stdout
    assert not (project / "started.json").exists()
