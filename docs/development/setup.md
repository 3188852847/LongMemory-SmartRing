# 开发环境

要求：项目固定的 Python 3.12.13、uv、Git；依赖使用既有 `uv.lock`。

```powershell
cd "<项目根目录>"
uv sync
uv run python --version
uv run --no-sync python -m pytest
uv run longmemory
```

`pyproject.toml` 保留 `.uv-cache/` 作为缓存默认值；本机 `UV_CACHE_DIR` 按机器规则指向
`D:\08-包与构建缓存\Python\uv`，实际位置用 `uv cache dir` 核对，不移动工具内部缓存。
`tests/conftest.py` 为每个 pytest 进程分配 `data/test-tmp/pytest/run-<PID>-<随机标识>/`，
产物被 Git 忽略。正常运行测试时不需要再传 `-p no:cacheprovider` 或 `--basetemp`。正常结束
只尝试清理本进程分配的 run 目录，共享父目录保留；不会扫描、清理其他进程或历史
目录。异常中断或文件被占用时可能残留，不能据此自动删除。

显式 `--basetemp` 会保留调用者路径，只补建不存在的父目录，本项目的退出钩子不
清理该目录。pytest 首次使用它时会清空目标已有内容，因此只能指定专用临时目录。
脚本、实验结果与历史目录的边界见 [测试产物管理](test-artifacts.md)。

依赖已经同步后，测试命令使用 `--no-sync`，这样不会因为检查包索引而意外联网。
需要新增或更新依赖时仍由用户明确执行 `uv sync`，两种操作的边界保持清楚。

`uv sync` 会根据 `pyproject.toml` 和 `uv.lock` 同步依赖，并将 `src/longmemory` 以可编辑方式安装到项目虚拟环境。也可以使用下面的等价模块入口启动 CLI：

```powershell
uv run python -m longmemory
```

默认 SQLite 文件位于 `data/databases/longmemory.db`。首次实验只使用合成信息，不输入真实隐私数据。

PyCharm 解释器选择项目内 `.venv\Scripts\python.exe`。不要提交 `.venv`、`.idea`、`.env`、数据库、`*.egg-info` 或真实运行日志。
