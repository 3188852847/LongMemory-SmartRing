# 开发环境

要求：Python 3.12、uv、Git。

```powershell
cd "D:\02-项目\LongMemory-SmartRing"
uv sync
uv run python --version
uv run --no-sync python -m pytest
uv run longmemory
```

项目已在 `pyproject.toml` 中把 uv 缓存固定到 `.uv-cache/`，并把 pytest
夹具临时目录固定到 `.pytest-tmp/`；两者均被 Git 忽略。正常运行测试时不需要再传
`-p no:cacheprovider` 或 `--basetemp`。`.pytest-tmp/` 会在每次测试开始时清理，
不得在其中保存手工数据或需要保留的实验结果。

依赖已经同步后，测试命令使用 `--no-sync`，这样不会因为检查包索引而意外联网。
需要新增或更新依赖时仍由用户明确执行 `uv sync`，两种操作的边界保持清楚。

`uv sync` 会根据 `pyproject.toml` 和 `uv.lock` 同步依赖，并将 `src/longmemory` 以可编辑方式安装到项目虚拟环境。也可以使用下面的等价模块入口启动 CLI：

```powershell
uv run python -m longmemory
```

默认 SQLite 文件位于 `data/databases/longmemory.db`。首次实验只使用合成信息，不输入真实隐私数据。

PyCharm 解释器选择项目内 `.venv\Scripts\python.exe`。不要提交 `.venv`、`.idea`、`.env`、数据库、`*.egg-info` 或真实运行日志。
