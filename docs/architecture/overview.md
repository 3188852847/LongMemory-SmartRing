# 架构总览

LongMemory Core 是研究主体，SmartRing-Plus 圆屏终端和 Xiaozhi 是后续接入的实验载体。

```text
entrypoints → application → core ← adapters
                         ↑
                 infrastructure
```

- `core`：领域模型、存储契约、提取与检索规则。
- `application`：组织一次对话或记忆管理用例。
- `adapters`：SQLite 和不同 LLM 的可替换实现。
- `infrastructure`：配置、数据库连接、日志和装配。
- `entrypoints`：CLI，以及后续 API、Xiaozhi 入口。

V0.1 只要求 CLI 入口和本地 SQLite 闭环。
