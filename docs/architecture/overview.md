# 架构总览

长程记忆是研究主体，SmartRing-Plus 圆屏终端和 Xiaozhi 已接通合成最小演示。
按 ADR-0008，研究平台、具体记忆方法、应用/任务执行端划分职责，仍在一个仓库中增量迁移。

```text
entrypoints → application → core ← adapters
                         ↑
                 infrastructure
```

- `core`：领域模型、存储契约、提取与检索规则。
- `methods`：中立方法契约与 `longmemory_v1` 包装；对其他方法不强制 L1/SQLite。当前只有基线，旧聊天/管理 DTO 仍是兼容路径。
- `application`：组织一次对话或记忆管理用例。
- `adapters`：SQLite 和不同 LLM 的可替换实现。
- `infrastructure`：配置、数据库连接、日志和装配。
- `entrypoints`：CLI、已有本机管理 API、Xiaozhi 入口；网页文字聊天尚未实现。

旧 V0.1 范围与验收保留；新的分阶段能力见 `method-boundary.md` 及 `docs/requirements/research-platform.md`。
