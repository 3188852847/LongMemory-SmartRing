# 方法边界与阶段 A 使用说明

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
└─ dialogue_chunks/             # 同会话两条消息分块的批处理对照
   └─ method.py                # 原始事件封存、角色/时间/来源与关键词召回
```

`core/` 保留现有实现；`application/memory_turn.py` 提供 observe/recall，prepare 保留旧日常流程。
bootstrap 通过方法工厂创建基线。旧聊天/管理仍使用 L1 DTO，属于仅基线可用的兼容路径，对话分块不能假装实现这些 DTO。实验的 session 元数据档案、冻结生命周期、状态哈希和逐题隔离由 evaluation/comparison 层负责，不修改日常方法能力声明。

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
- 每个实例连接由自己拥有，不能跨线程共享。close 可重复，不删除文件。
- session_id 暂不落库，有值即报不支持，不静默丢掉会话边界；目前只有 user/assistant 消息，无工具事件接口。
- 不接受测试答案、奖励或反馈，不声明冻结协议支持；能力不满足应在实验开始前拒绝。
- 阶段 B 为 longmemory_v1 的 observe 增加 SQLite BEGIN IMMEDIATE：同一事件的 L0、去重、L1、来源共同提交/回滚；模型调用不在事务内。方法级重复 event_id 仍由 L0 主键拒绝；网页另有会话内请求去重，不能当作持久幂等协议。
- recall 在一个只读事务快照内读取记忆和来源；合成前后状态测试证明调用不写 L0/L1，不证明整个实验被冻结。不同轮次仍可能看到别的进程已提交的新数据。
- 网页显式使用 existing_only=True，只打开已有当前版本库、不建库或迁移；CLI/方法工厂仍保留原建库行为。网页短期会话保存在应用层内存，不向方法传不支持的持久 session_id。
- 历史 occurred_at 保存为 L0 created_at；L1 recorded_at 是实际提取记录时间，valid_from 仍未知。

参见 `docs/requirements/research-platform.md` 的后续 B/C/D 验收，不能把基础接口当成已接通论文实验。
