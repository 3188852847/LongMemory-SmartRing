# 开发环境

要求：Python 3.12、uv、Git。

```powershell
cd "D:\02-项目\LongMemory-SmartRing"
uv sync
uv run python --version
uv run pytest
```

PyCharm 解释器选择项目内 `.venv\Scripts\python.exe`。不要提交 `.venv`、`.idea`、`.env`、数据库或真实运行日志。
