# 网页聊天归档与记忆写入回归

2026-11-21，分支 `codex/fix-memory-20261121`，基线 `40452b25`。

| 修复位置 | 已验证行为 |
|---|---|
| `MemoryRuntime.configure` | 首次暂停后台写入失败后，前台保持暂停，其他配置保留原值。再次暂停或改为恢复，都要等后台同步成功才返回成功。 |
| `GET /api/chat-config` | 工作线程读取角色和运行时状态。在配置读取等待期间，另一个已认证的 HTTP 请求能正常返回。 |
| 网页聊天终轮归档 | 首次终轮保存失败返回 HTTP 503，查询仅展示已提交轮次。同一请求号和正文重试、查询详情可共享一次补写。持有真实 SQLite 写锁时，会话列表仍能读取。保存成功后再公开终轮，模型只调用一次。 |
| 模型健康状态 | 真实模型返回有效回答后标记可用。应用命令和跟进回执保留原状态、错误码和检查时间。Fake 回答器保持 `not_applicable`。 |

正常停机会等待在途任务，再逐个给待保存的终轮一次提交机会。两份合成会话中，一份恢复可写后在重启时读到 `completed`，另一份持续保存失败，按原档案恢复为 `interrupted`。进程在补写成功前丢失内存结果时，保留原请求号，沿用写入状态未知的中断语义。

主仓 Python 3.12.13 解释器使用工作树的 `src` 和根目录作为进程级 `PYTHONPATH`，已断言三个改动模块均从本树导入。以下五个文件共 **95 项通过**。HTTP 测试使用随机回环端口、合成数据库和模型替身。

```text
python -m pytest -q tests/integration/test_hy_semantic_platform.py tests/unit/application/test_managed_memory_proposals.py tests/unit/entrypoints/test_chat_backend.py tests/unit/entrypoints/test_chat_console.py tests/unit/entrypoints/test_chat_persistence.py
```

## 同一条记忆的多条来源

整合提交 `88c7f236` 报告去重端到端测试中两条原文偶发倒序。该提交与本分支的相关读写实现及原用例一致。自 `67c7f7c2` 起，SQLite 按证据关联时间 `linked_at` 升序读取，同一时间按来源消息 ID 升序。日常消息使用随机 UUID，同一时刻可能先读到后说的那句话。

用合成时钟和逆序消息 ID 运行原顺序断言，间隔一秒的用例通过，同一时刻的用例稳定复现“叹号、句号”。修订后的用例按两种时间条件逐条比较证据和原始消息，关闭并重开数据库后再次核对整个列表，并验证第三条陈述复用原记忆且排在末尾。改动仅涉及测试和本记录，沿用既有档案的读取顺序。

`python -m pytest -q tests/e2e tests/integration/database/test_sqlite_stores.py tests/unit/methods/test_longmemory_v1.py tests/unit/application/test_chat_service.py` 共 **40 项通过**，包括旧版合成数据库的来源迁移和独立 CLI 进程重启。
