# 开发环境

要求：Python 3.12、uv、Git。

```powershell
cd "D:\02-项目\LongMemory-SmartRing"
uv sync
uv run python --version
uv run pytest -p no:cacheprovider
uv run longmemory
```

`uv sync` 会根据 `pyproject.toml` 和 `uv.lock` 同步依赖，并将 `src/longmemory` 以可编辑方式安装到项目虚拟环境。也可以使用下面的等价模块入口启动 CLI：

```powershell
uv run python -m longmemory
```

默认 SQLite 文件位于 `data/databases/longmemory.db`。首次实验只使用合成信息，不输入真实隐私数据。

PyCharm 解释器选择项目内 `.venv\Scripts\python.exe`。不要提交 `.venv`、`.idea`、`.env`、数据库、`*.egg-info` 或真实运行日志。
