"""用真实 pytest 子进程验证临时目录生命周期；只使用合成 SQLite 数据。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[3]

# 子工程只复制被测 conftest，不加载本机配置、不启动服务。用文件屏障控制
# 两个进程的时序，避免仅凭执行耗时猜测它们是否真正重叠。
PROBE = '''
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time

import longmemory


def wait_for(path):
    deadline = time.monotonic() + 30
    while not path.exists():
        assert time.monotonic() < deadline, f"barrier timed out: {path}"
        time.sleep(0.01)


def test_probe(request):
    project = Path(request.config.rootpath)
    name = __NAME__
    base = Path(request.config.option.basetemp).resolve()
    (project / f"{name}-configured.json").write_text(
        json.dumps({"base": str(base)}), encoding="utf-8"
    )
    if __GATED__:
        wait_for(project / f"{name}-start")
    temporary = request.getfixturevalue("tmp_path")
    database = temporary / "memory.db"
    # SQLite connection 的 with 只管理事务，不关闭文件；正常清理前须显式关闭。
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE synthetic (owner INTEGER)")
        connection.execute("INSERT INTO synthetic VALUES (?)", (os.getpid(),))
        connection.commit()
        (project / f"{name}-running.json").write_text(
            json.dumps({"base": str(base), "database": str(database),
                        "pid": os.getpid(), "source": longmemory.__file__}),
            encoding="utf-8",
        )
        if __HOLD__:
            wait_for(project / f"{name}-release")
        assert database.is_file()
        assert connection.execute("SELECT owner FROM synthetic").fetchone() == (os.getpid(),)
    assert not __FAIL__, "synthetic test failure"
'''


@pytest.fixture
def isolated_project(tmp_path):
    # 中文与空格路径同时覆盖项目原有的 Unicode 路径兼容要求。
    project = tmp_path / "隔离 pytest 工程"
    tests = project / "tests"
    tests.mkdir(parents=True)
    shutil.copyfile(ROOT / "tests/conftest.py", tests / "conftest.py")
    (project / "pytest.ini").write_text(
        "[pytest]\naddopts = -p no:cacheprovider\n"
        f'pythonpath = "{(ROOT / "src").as_posix()}"\n',
        encoding="utf-8",
    )
    processes = []
    yield project, processes
    # 断言失败也回收由本测试启动的子进程，避免让它们继续占用合成数据库。
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def start_probe(isolated_project, name, *, basetemp=None, gated=False, hold=False, fail=False):
    project, processes = isolated_project
    code = (PROBE.replace("__NAME__", repr(name))
            .replace("__GATED__", repr(gated))
            .replace("__HOLD__", repr(hold))
            .replace("__FAIL__", repr(fail)))
    target = project / "tests" / f"test_{name}.py"
    target.write_text(code, encoding="utf-8")
    command = [sys.executable, "-m", "pytest", "-q", str(target)]
    if basetemp is not None:
        command.extend(["--basetemp", str(basetemp)])
    environment = os.environ.copy()
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_CURRENT_TEST", "PYTHONPATH"):
        environment.pop(key, None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        command, cwd=project, env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )
    processes.append(process)
    return process


def wait_for_report(project, name, phase, process):
    path = project / f"{name}-{phase}.json"
    deadline = time.monotonic() + 30
    while not path.is_file():
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(f"probe exited before {phase}: {stdout}\n{stderr}")
        assert time.monotonic() < deadline, f"report timed out: {path}"
        time.sleep(0.01)
    # 写报告后再读取可能恰逢写入尚未完成，等待完整 JSON，避免并发测试偶发失败。
    while True:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            break
        except json.JSONDecodeError:
            assert time.monotonic() < deadline, f"incomplete report: {path}"
            time.sleep(0.01)
    if phase == "running":
        assert Path(report["source"]).resolve().is_relative_to(ROOT / "src")
    return report


def finish(process, expected=0):
    stdout, stderr = process.communicate(timeout=30)
    assert process.returncode == expected, f"{stdout}\n{stderr}"


@pytest.mark.parametrize("fail", [False, True])
def test_automatic_directory_is_cleaned_on_normal_exit(isolated_project, fail):
    project, _ = isolated_project
    root = project / "data/test-tmp/pytest"
    sibling = root / "run-historical"
    sibling.mkdir(parents=True)
    evidence = sibling / "keep.txt"
    evidence.write_text("synthetic historical evidence", encoding="utf-8")
    process = start_probe(isolated_project, "normal", fail=fail)
    finish(process, expected=1 if fail else 0)
    report = wait_for_report(project, "normal", "running", process)
    base = Path(report["base"])
    assert base.parent == root
    assert base.name.startswith(f'run-{report["pid"]}-')
    assert not base.exists()
    assert evidence.read_text(encoding="utf-8") == "synthetic historical evidence"


@pytest.mark.parametrize("relative", [False, True])
def test_explicit_basetemp_creates_parents_and_remains_after_exit(isolated_project, relative):
    project, _ = isolated_project
    requested = Path("manual/nested/explicit")
    expected = project / requested
    assert not expected.parent.exists()
    process = start_probe(
        isolated_project, "explicit", basetemp=requested if relative else expected,
    )
    finish(process)
    report = wait_for_report(project, "explicit", "running", process)
    assert Path(report["base"]) == expected
    assert Path(report["database"]).is_file()
    assert not (project / "data/test-tmp/pytest").exists()


def test_parallel_processes_keep_separate_sqlite_and_cleanup_ownership(isolated_project):
    project, _ = isolated_project
    first = start_probe(isolated_project, "first", hold=True)
    second = start_probe(isolated_project, "second", hold=True)
    first_report = wait_for_report(project, "first", "running", first)
    second_report = wait_for_report(project, "second", "running", second)
    assert first.poll() is None and second.poll() is None
    assert first_report["pid"] != second_report["pid"]
    assert first_report["base"] != second_report["base"]
    assert first_report["database"] != second_report["database"]
    (project / "second-release").touch()
    finish(second)
    assert not Path(second_report["base"]).exists()
    assert Path(first_report["database"]).is_file()
    assert first.poll() is None
    (project / "first-release").touch()
    finish(first)
    assert not Path(first_report["base"]).exists()


def test_shared_parent_survives_before_another_process_requests_tmp_path(isolated_project):
    project, _ = isolated_project
    pending = start_probe(isolated_project, "pending", gated=True)
    pending_report = wait_for_report(project, "pending", "configured", pending)
    assert not Path(pending_report["base"]).exists()
    active = start_probe(isolated_project, "active")
    finish(active)
    # pending 已配置但还没创建自身 basetemp：active 此时不能删共享父目录。
    assert Path(pending_report["base"]).parent.is_dir()
    (project / "pending-start").touch()
    finish(pending)
    report = wait_for_report(project, "pending", "running", pending)
    assert not Path(report["base"]).exists()
