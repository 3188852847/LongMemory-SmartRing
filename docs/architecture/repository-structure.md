# 仓库结构约定

README 中的目录树是当前唯一的仓库蓝图。本文件记录容易混淆的边界：

- 使用单数 `core/conversation` 和 `core/memory`，与当前领域聚合命名一致。
- `methods/` 放完整方法契约与包装，公共类型不能依赖现有 L1 模型；当前 `longmemory_v1` 复用 core，不搬走或复制算法。阶段 A 边界见 `method-boundary.md`。
- L0/L1 模型归属于相应核心模块，不再创建第二套 `infrastructure/errors`。
- 领域异常放在 `core/common/exceptions.py`。
- SQLite 实现放在 `adapters/storage/`；连接和建表基础设施放在 `infrastructure/database/`。
- `tests/` 是测试代码，`datasets/` 是固定输入，`experiments/` 是运行产物和分析。
- 未来模块可以预留目录，但不得在 README 中写成已实现能力。
