# U：记忆层可替换边界补完整

日期：2026-10-19。状态：代码、隔离验收与本地提交已完成，待主会话独立审查/合入/推送。不是 Hy 真实运行或日用切换验收。

## 授权、分工与完成标准

用户决定 Hy-Memory 为长期主要目标后端，可从新库积累；旧实现保留作对照/回退，不为旧派生层完整迁移增加复杂成本。“一切重来”不授权删除/覆盖个人数据。

本轮只使用 U 树的合成临时库，无个人库正文/真实对话导出，无 local/config 写入，无日用 8767/8000/8003 服务访问、设备/串口操作、下载/安装或环境切换。主 Python 3.12.13 只读复用，已实际打印确认导入为 U/src。没有升级依赖或锁文件，也没有共享 node_modules。

| 会话 | 范围与工作树 | 分支/会话 ID |
|---|---|---|
| 主会话 | 协调、独立审查、整合和推送 | `01a1534f-3c56-78c1-9e13-4777422a67bb` |
| U | 通用协议、来源/运行时/管理装配、必要页面兼容、相关测试/现行文档；`local/worktrees/u-memory-boundary-20261019` | `codex/u-memory-boundary-20261019`；`01a15362-e6ae-72c2-bf03-bfb4f3844ba6` |
| V | 官方版本/依赖预检、`methods/hy_memory`、Hy 专属适配/对比入口/合成样本/V 报告；`local/worktrees/v-hy-memory-20261019` | `codex/v-hy-memory-20261019`；`01a15363-8120-7400-a9db-8f9142104b12` |

共同起点 `147cbc117d4f88f5775dd02076ab9970871238a8`。U 未编辑 V 模块，未向其他会话发工具消息，未 merge/push。由主会话通过提交交付 V。

实际依赖图：原 `server/bootstrap → MemoryRuntime → MemoryMethod` 已中立；管理、自然纠错、历史、情景/画像仍直读旧 SQLite。现补为 `BackendAssembly(method, resources, management) → Runtime`，旧适配器才接原 SQL 派生能力；新引擎的来源由平台归档、写入/召回/管理由方法自身实现。

完成标准：旧 LongMemory 和一种目录/图节点结构的替身经过同一运行时与中立管理；未知过程保持 None，角色/时间/来源可追溯；能力不足明确拒绝；写入暂停、失败/重试、重启/并发有实际合成证据；旧 API/DailyLLM 回归保留。新后端无需假装 AtomicMemory、单文件或 L0–L3。

## 代码交付与精确接口

| 阶段 | 提交 | 本地验收 | 合入/推送 |
|---|---|---|---|
| 最小稳定契约 | `83b5b6d` | 后续方法/架构/HTTP 回归覆盖 | 待主会话 |
| 实际装配、来源账本、运行时与中立管理 | `b52e0e3` | 受影响范围 489 passed / 2 skipped；后续精确回归 73 passed | 待主会话 |
| 纠正操作的用户来源权限 | `77c7342` | 后端边界 25 passed | 待主会话 |
| 中立列表不可用/空结果区分 | `4deee7b` | 后端边界 25 passed；React 尚未构建 | 待主会话 |
| ADR/现行说明/清单/本报告 | 本报告所在文档提交（Git 历史可查） | 窄范围 strict 检查见下 | 待主会话 |

`83b5b6d` 的 DTO（数据传输对象）签名未改变。后续把 `require_management` 的实现移至 `methods/contracts.py`，`backend_contracts.py` 仍可导入该名称；这是为遵守原有架构检查，没有放宽测试。新增 `idempotent_observation` 能力默认为 False，不修改旧方法声明的真实保证。

V 应依序接入四个代码提交；只取首个提交可开始类型适配，真实组装须取后续实现。

```python
from longmemory.bootstrap import assemble_backend, build_backend_runtime
from longmemory.methods.backend_contracts import StateResource

# engine/admin 由 V 实现；路径来自可信启动装配，不来自 HTTP。
assembly = assemble_backend(
    method=engine,
    resources=(StateResource("hy_state", engine_directory, "directory"),),
    source_path=platform_source_file,
    management=admin,          # 无忠实管理适配就传 None，能力明确拒绝
    create_sources=True,      # 仅全新隔离来源库；重开必须 False
)
runtime = build_backend_runtime(assembly)
```

`engine.observe(MemoryEvent)` 可以是完整组合 add；`recall` 返回 `MemorySupport`，未知 writes/retrieved 为 None，返回分数不作跨方法统一排序。source_event_ids 需要由 V 把其私有来源映射到平台 event_id；不能伪造旧 L1。助手消息只进平台来源，平台会拒绝以助手消息作为纠正权威。session_id 平台保存；引擎未声明支持时不静默传给它或丢掉，而是 source_only + 明确 warning。

`MemoryAdministration` 为 `list_items(query,state,limit,offset) → MemoryPage`、`get_item(id) → MemoryItem`、`correct_item(id,content,expected_revision,source) → MemoryItem`、`delete_item(id,expected_revision)`。适配器负责在自身状态内原子比较修订并实施；没有原生支持就声明 False/拒绝。记录时间和生效区间分开，未知为 None，条目 kind 为方法自身表示。

`ChatBackend` 注入同一 Runtime，database 兼容参数指定平台来源文件（路径不一致会拒绝），网页会话/助手角色旁库继续分开。`create_app(memory_runtime=runtime, chat_backend=chat, ...)` 保持聊天与管理同一实例；新源文件不能当旧 L1 库打开。CLI/启动器的日用选择未新增 Hy；V 接线后仍须单独定义日用切换。

中立 API 为 `/api/memory-engine`、`/items`、`/items/{id}`、`/items/{id}/corrections`、`/sources/{event_id}`、`/sources/{event_id}/retry`。纠正/删除受启动权限约束，恢复与纠正受运行期写开关约束；会话/同源/CSRF 原护栏保留。旧管理 API 返回结构未改，新引擎访问旧 L1/情景/画像/主动接口返回 501。React 只加中立条目和能力展示，不增加新引擎编辑表单或界面重设计。

## 来源与失败语义

- 来源库复用 SQLiteConversationStore，独立存原角色/时间、session_id 和投递状态；不创建旧派生层，不迁移个人库。持久身份绑定方法名、版本与精确资源路径；错误状态目录拒绝重开。
- 原文先提交。新引擎仅收到用户消息；暂停/排除只归档，关闭召回不查询引擎。组合调用保守串行，可能阻塞读取，不宣称旧两阶段路径的延迟保证。
- 延后状态 pending 保留到实际投递；无完成回执不自动执行，重启也不自动重放。pending 尚未调用引擎，可用预期尝试 ID 显式恢复；archive-only 不视为可重跑失败。
- 引擎失败保留 failed；它不保证引擎完全没写入。跨存储提交窗口没有事务保证，重启独占接管后 running 变 uncertain。只有真实持久幂等能力才允许显式重试 failed/uncertain。完成记录持久回放，同 ID 不同载荷拒绝。
- 来源文件有 OS 生命周期独占锁，第二拥有者拒绝，不把活跃投递误判为崩溃。此锁不是分布式协调服务。
- 纠正先归档新来源，管理失败不保证跨存储回滚；删除仅删除引擎条目，原文保留，不等于隐私擦除。没有通用批量清空/擦除协议。

## 实际验证

解释器为主项目 `.venv/Scripts/python.exe`，实测 Python 3.12.13；命令均显式 U workdir，pytest 导入 U/src，临时目录采用项目现有每进程隔离机制。HTTP 测试先绑定随机回环端口，未连接日用服务，使用假控制桥。

| 检查 | 实际结果与范围 |
|---|---|
| 首轮方法/管理/时间回归 | 88 passed，后续补了更多用例 |
| 后端边界替身最终回归 | 25 passed；旧/目录结构统一调用、来源角色/会话、空输入、未知过程、无结果、重复/冲突、失败前/后提交、显式重试、重启不确定、pending 恢复、并发修订、隔离、路径/拥有者拒绝、HTTP/权限/CSRF |
| 受影响范围 `tests/unit/methods tests/unit/entrypoints tests/unit/application tests/unit/architecture` | 489 passed / 2 skipped（符号链接能力、未绑定真实 Otto 资源）；后续最后的小改动另跑下一行 |
| 最后针对性回归（边界、ChatBackend、聊天 HTTP、架构） | 73 passed；之后新增用户纠正权威约束，由最终 25 项边界回归覆盖 |
| 首次全量 Python | 2132 passed / 7 skipped / 4 failed；不是最终全绿结果，详见下方 |
| 文档窄检查 | `check_docs.py --only` 六份改动 Markdown `--strict` 通过，结果统计为空；清单同批核对 |
| React | 新增一条不访问旧派生端点的兼容测试；U 树无独立 node_modules，未运行 TypeScript/Vitest/构建/浏览器视觉验收，未自动安装 |
| 差异检查 | `git diff --check` 通过；只含公开代码、合成测试和文档，无私有配置、真实正文、数据文件或锁升级 |

全量四处失败中，一处为本轮应用层导入新中立契约文件不符合已有“只导入 contracts”的规则；已把守卫移回 contracts，架构检查通过，没有改测试前提。另外三处源码/测试与起点 `147cbc1` 无差异：语音启动器测试观察到重复 bind（显式补齐原脚本导入路径后仍可复现）；Tk init.tcl 和诊断子进程日志数量在全量失败、单独重跑通过。没有为使全量变绿扩大修改范围。跳过项还包括本树未安装的小智环境/源码、符号链接权限和 FFmpeg，不能当真实依赖验收。

## 未验与主会话接力

Hy 包尚未安装；未运行真实 Hy、模型、语音/设备或个人库。25 项替身不证明 Hy 正确性、质量/性能或跨存储 exactly-once。新后端旧圆屏完成关联/反馈、旧 L1 提取审计/影子、自然补记/纠错/历史/画像/情景/主动跟进均未适配，已明确拒绝；低频整理和影子未开启。新后端的真实设备链路需后续适配，旧 LongMemory/DailyLLM 链路保持回归覆盖。

主会话下一步：审查并按提交交付 V → V 对其私有数据/来源/能力作忠实适配 → 独立合成接入与真实 Hy 验收 → 明确日用切换范围；不自动迁移或删除个人数据。合入提交、推送结果与最终用户验收由主会话追加，不由 U 代填。保留本分支与工作树。
