# 方法与后端替换边界

2026-10-19 增补：以下“新后端装配”是 U 的实际实现；V 已交付 Hy-Memory 专用适配与真实 SDK/Chroma＋模拟模型验证，W 完成隔离后端审查和回归，并在串行移交的独立前端树完成 MemoryApp 11项组件测试、TypeScript 检查和生产构建。目录型替身与模拟模型都不证明真实模型效果。决定见 [ADR-0181](../adr/0181-neutral-memory-backend-and-platform-sources.md)，证据见 [U 记录](../development/parallel/U-memory-boundary-20261019.md)、[V 记录](../development/parallel/V-hy-memory-20261019.md)与 [W 审查](../development/parallel/W-hy-review-integration-20261019.md)。main 合入待主会话，日用选择和个人库没有切换。

## 新后端装配

实际依赖为：`server → bootstrap → BackendAssembly → MemoryRuntime → MemoryMethod`；管理通过 `MemoryAdministration`，平台原文通过 `ManagedMemoryMethod → SQLiteSourceJournal → SQLiteConversationStore`。旧引擎另由 `build_legacy_runtime` 接入原自然纠错、时间事实、临时方式、情景/画像与可选影子/整理；新装配不会自动获得这些 SQL 提供器。

`methods/backend_contracts.py` 定义中立条目、分页、管理能力和 `StateResource`。一个状态可由目录和多个文件组成；条目可以是摘要、图节点、块或事实。来源 ID、记录时间、有效区间各自保留，未知为 `None`；不强迫外部方法伪装成 `AtomicMemory` 或 L0–L3。分数和召回策略仍由方法命名，不强制同量纲。

新后端按下列方式显式接入，不接受 HTTP 模块名或路径：

1. 适配器构建实现 `MemoryMethod` 的引擎，`observe(event)` 可以是完整组合 pipeline；不要求拆开私有提取/索引/存储。
2. 调用 `bootstrap.assemble_backend(method=..., resources=(StateResource(...),), source_path=..., management=..., create_sources=...)`。新来源库仅 `create_sources=True` 排他创建；重开用 `False`，不迁移旧个人库。来源文件不能落在引擎资源目录内部。
3. `build_backend_runtime(assembly)` 装配应用运行时；`ChatBackend` 显式注入该 Runtime，`create_app(memory_runtime=runtime, chat_backend=...)` 使用同一个实例管理和聊天。`ChatBackend.database` 在新装配中使用平台来源路径，旁边的网页会话/角色旁库继续与引擎隔离。该兼容字段不是“所有后端都是数据库”的约束。
4. `management=None` 或能力为假就拒绝。`/api/memory-engine` 暴露能力和资源，`/items` 支持列表、详情、纠正和删除；`/sources/{event_id}` 读取原角色/时间/正文，`/retry` 仅接受显式预期尝试 ID。纠正/删除还受服务器启动权限约束，纠正和恢复受运行期写开关约束。旧 `/api/memories`、情景/画像/主动交流等端点在新后端返回 501，不打开旧库。当前 React 管理页只增加中立条目与能力展示，尚无新引擎编辑表单。

新装配的来源与投递语义：

- 先提交原文，再调用引擎。用户消息才进入事实引擎；助手原文只归档。普通查询不归档、不调用 observe；运行期 `use_enabled=False` 停止召回，`write_enabled=False` 保留原文但不派生。明确自然排除句也只归档。
- 延后投递以 `pending` 持久保存；收到完成回执才排队，不自动恢复/重放。重启后可显式恢复尚未投递的 pending。归档但被暂停/排除的 `archived` 不可当失败自动重跑。
- 组合调用采用保守串行锁，可能阻塞同 Runtime 的读取；不继承 DailyLLM 两阶段路径的延迟保证。引擎返回失败会保留原文和 `failed`。引擎提交与来源账本没有跨存储事务，崩溃窗口的 `running` 在下次取得独占来源拥有权后变为 `uncertain`。
- 已完成 event_id 重复请求返回持久结果；同 ID 异载荷拒绝。失败/不确定投递仅在引擎真实声明 `idempotent_observation=True` 时允许显式重试；该声明的真实保证由适配器实现并验证。否则明确拒绝，不能保证跨存储 exactly-once。单来源库有操作系统生命周期锁，避免第二拥有者错误接管进行中的投递。
- 纠正来源先归档再调用管理适配器；管理修订比较须由适配器原子执行。新后端跨存储管理失败不承诺回滚原文。删除只删除引擎条目，平台原文保留，不等于隐私擦除。
- 未适配的自然纠错、历史事实、来源解释、明确补记和陪伴控制返回 `unsupported` 回执；不是模型推测执行结果。一次“下一轮”的应用内临时方式保留。旧 L1 审计、圆屏完成关联/反馈、影子复核在新后端明确不支持，不静默读取旧表。低频整理与影子不自动启用。

Hy 是用户指定的长期主要目标；可从独立新库积累，旧引擎保留作对照/回退。不迁移旧派生层、不删除任何个人数据。V 已通过 `assemble_backend` 接入；SDK 由所有者安装，助手只读复用独立解释器，未获取外部资源。运行与预算边界见 [Hy 指南](../guides/Hy-Memory隔离接入与验证-20261019.md)。

平台契约位于 `src/longmemory/methods/contracts.py`。`MemoryEvent` 是允许输入的消息，
`ObservationResult` 描述记忆操作，`MemorySupport` 提供上下文与可选过程；它们不引用 AtomicMemory。
`None` 表示不提供内部过程，空元组表示提供过程但没有条目；分数不是统一量纲，本版不增加伪成本或伪分数。

## 实际目录

```text
src/longmemory/methods/         # 方法级入口，与应用/实验入口解耦
├─ contracts.py                # 中立消息、结果、能力声明和协议
├─ factory.py                  # 显式白名单；原子事实和对话分块两种方法
├─ longmemory_v1/               # 现有基线包装，不复制核心规则
│  └─ method.py                # 状态生命周期与旧组件适配
├─ dialogue_chunks/             # 同会话两条消息分块的批处理对照
│  └─ method.py                # 原始事件封存、角色/时间/来源与关键词召回
├─ llm_extract/                # D1 实验专用模型提取条件，未加入日常工厂
│  └─ method.py                # 事务外候选生成、原子落库、候选审计及冻结读取
└─ hy_memory/                  # 显式可选接入，独立SDK进程、只读管理与私有资源身份
```

`core/` 保留现有实现；`application/memory_turn.py` 提供 observe/recall，prepare 保留旧日常流程。
bootstrap 保留基线方法工厂，并提供上述独立后端装配。旧聊天/管理的 L1 DTO 继续由旧适配器兼容，对话分块不能假装实现这些 DTO。实验的 session 元数据档案、冻结生命周期、状态哈希和逐题隔离由 evaluation/comparison 层负责，不修改日常方法能力声明。

D1 的 `longmemory_llm_extract_v2` 由 `evaluation/comparison/methods.py` 显式装配，不自动暴露为日常入口。它复用 v1 存储/检索组件但不调用旧规则提取器：候选先在事务外形成，固定候选随后与 L0/L1/证据一起写入全新实验库，审计表写失败也整批回滚。冻结重开验证该方法自己的身份表；没有个人库升级或自动切换。真实提取模型效果待校园网验收，见 ADR-0010。

## 安全的合成示例

以下为新方法的 Python API 示例，不是网页功能；只创建并使用临时合成库，不需要网络或新依赖。
临时目录退出时由标准库清理，不指向日常数据目录。

```python
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from longmemory.methods.contracts import MemoryEvent
from longmemory.methods.factory import create_method

with TemporaryDirectory(prefix="longmemory-method-example-") as directory:
    method = create_method(name="longmemory_v1", state_path=Path(directory) / "synthetic.db")
    try:
        method.observe(MemoryEvent(
            event_id="synthetic-1", role="user",
            content="我养了一只叫豆包的猫", occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        ))
        method.wait_until_ready()
        result = method.recall("我的猫叫什么")
        print(result.context)
    finally:
        method.close()
```

## 明确限制

- state_path 由调用方明确提供；工厂沿用原建库/建表行为，不是控制台已有库只读后端，不能用于自动选取个人库。
- 普通方法实例的连接由自己拥有，不能跨线程共享。日常 `MemoryRuntime` 是唯一例外：显式关闭 SQLite 线程检查，并用自己的互斥锁保证连接不会并发操作。close 可重复，不删除文件。
- 旧基线 session_id 暂不落库，有值即报不支持；新平台来源账本保存 session_id，具体引擎是否消费由能力声明和适配器负责。消息仍限 user/assistant，无工具事件接口。
- 不接受测试答案、奖励或反馈，不声明冻结协议支持；能力不满足应在实验开始前拒绝。
- 阶段 B 为 longmemory_v1 的 observe 增加 SQLite BEGIN IMMEDIATE：同一事件的 L0、去重、L1、来源共同提交/回滚；模型调用不在事务内。方法级重复 event_id 仍由 L0 主键拒绝；网页另有会话内请求去重，不能当作持久幂等协议。
- recall 在一个只读事务快照内读取记忆和来源；合成前后状态测试证明调用不写 L0/L1，不证明整个实验被冻结。不同轮次仍可能看到别的进程已提交的新数据。
- 网页显式使用 existing_only=True，只打开已有当前版本库、不建库或迁移；CLI/方法工厂仍保留原建库行为。网页短期会话保存在应用层内存，不向方法传不支持的持久 session_id。
- 历史 occurred_at 保存为 L0 created_at；L1 recorded_at 是实际提取记录时间，valid_from 仍未知。

参见 `docs/requirements/research-platform.md` 的后续 B/C/D 验收，不能把基础接口当成已接通论文实验。
