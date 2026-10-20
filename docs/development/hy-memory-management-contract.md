# Hy 记忆管理接线契约

## 2026-10-21：语义后台组合追加（隔离候选）

下文保留原图关闭/后台关闭管理证明的依据；新 L6/L7 仅在 AB 协议 2 证明和真实派生失效验证成立后可装配，不把旧证明改签为新模式。公共 Runtime 现已实现初始化/写门变化时 `configure_background_writes(write_enabled=...)` 同步；失败保持前台暂停，不声称运行中任务已回滚。`semantic_enqueue` 受同一写门，取消 pending 在暂停时仍可请求。

新增 HTTP 固定入口：`GET /api/memory-engine/hy/semantic/status`、`GET /api/memory-engine/hy/semantic/tasks/{task_id}`；读响应为原 AB DTO 顶层，追加 `observed_at` UTC 读取时间，status 追加 `runtime:{write_enabled,use_enabled}`。只窥视现存实例、非阻塞，不调用普通 search 或 Runtime.status 的过期处理，不为查看懒创建引擎。schema disabled 仍由 AB 返回完整关闭结构；读成功不获得管理写、未来意图执行或主动联系权限。

显式管理请求为 `POST .../semantic/tasks`，JSON 精确字段 `task_id/kind/max_batches`，kind 仅 `evolve/intention_maintenance`、batches 整数 1–4；取消为 `POST .../semantic/tasks/{task_id}/cancel`，JSON `{}`。任务 ID 限有界字母数字/下划线/短横线，不接受路径、来源、用户或 SDK 方法。两项沿现有管理启动权限和会话/CSRF；enqueue 另查 Runtime 写门，pause 无 HTTP 入口。语义后台生成不是新增用户事实，不伪造 user 来源。任务结果以 AB 实际回执为准，取消已认领任务不回滚。

稳定错误为 400 请求错误、403 `hy_management_write_disabled/memory_write_paused`、404 `hy_semantic_task_not_found`、409 `hy_semantic_conflict/hy_semantic_operation_rejected`、501 `memory_backend_capability_unsupported`、503 `hy_semantic_busy/hy_semantic_unavailable/hy_semantic_outcome_uncertain`；会话与 CSRF 的 401/403 继续沿原中间件。公共决策见 [ADR-0201](../adr/0201-composed-runtime-write-gates-and-observation.md)，实际接力/验证见 [AI 任务书](parallel/AI-hy-advanced-low-latency-20261021.md)。这是隔离实现说明，不表示正式服务已提供新入口。

日期：2026-10-19。Y 已实现管理适配/API/前端，V/X 接线仍待主会话安排；未接线的动作不宣称可用。本文件只覆盖记忆管理，不修改通用 MemoryMethod 的层级含义。

## 确认的底层事实

已只读检查所有者安装的 `hy-memory==2.0.3` 的 `client.py`：`get/list_memories` 可读；`get_user_profile(user_id=...)` 只按 user 隔离；`history(memory_id)` 返回历史数组（关闭历史时也返回空数组）；`update(memory_id, content)` / `delete(memory_id)` 没有 expected_revision。list 只返回 ACTIVE、可接受 layers，不支持正文查询或 source 过滤。SDK update 不能同时提交平台纠正来源。不能把它包装成原生 CAS（比较并交换）或跨存储事务。真实 SDK 离线验证同时确认：get.source=`vdb` 是存储通道，来源隔离按透传 meta 核对；修订指纹排除每次读取的 request_id/elapsed_ms。

## V 接力：受限 RPC（远程过程调用）

沿用现有 JSONL envelope / 超时即关闭 / 稳定脱敏错误。不接受客户端路径、user/agent/source 的 HTTP 覆盖。

| Python client 方法 | 固定参数 | 返回 / 错误 |
|---|---|---|
| `management_capabilities()` | 无 | `{"protocol":1,"history":bool,"profile":bool,"update":bool,"delete":bool,"exclusive_user_profile":bool}`；只有核对 SDK API / 当前配置后为真，默认 false。profile 须独占 user、当前 agent/source 范围证明，否则 false。 |
| `history(memory_id=...)` | 非空字符串 ID；先在 Y 按 user/agent/source 核对当前条目 | SDK history 数组；未知字段不透传 HTTP，Y 白名单投影。空数组表示“未记录或无变化”，不等于没有历史变化。 |
| `update(memory_id=..., content=...)` | ID / 明确用户纠正正文；不接受任意 kwargs | SDK `success is True` 且 memory_id 一致，随后 Y 独立 get 验证正文。异常可能部分提交，绝不自动重试。不得调用 add/模型重新提取来冒充纠正。 |
| `delete(memory_id=...)` | 单条 ID；不提供 delete_all | SDK `success is True`，随后 Y 独立 get 确认不存在。仅引擎条目删除，平台来源/历史/备份保留。 |

现有 `get_user_profile(user_id=...)` 继续使用；Y method 的 sdk_call 增加白名单。若真实 SDK update/delete 的副作用不满足当前单条范围，capability 必须 false 并给出阻塞证据；不能仅为 UI 打开动作。

## X 接力：Runtime 扩展入口

请在 Runtime 增加 `administer_extension(namespace, operation, **arguments)`，namespace 仅 `hy_memory`，operation 白名单：`workspace`, `profile`, `history`, `operations`, `correct`, `delete`。在现有 Runtime 串行锁内检查 open / assembly / `management.extension_namespace`，调用 `management.extension(operation, **arguments)`；不向 HTTP 暴露对象或任意方法名。

`correct/delete` 均检查运行期 write_enabled；启动权限由 Y 路由继续检查。`correct` 的 `source` 必须是平台新建真实 user 事件，正文与 content 相同，归档后调用 extension；`delete` 也传入真实用户明确删除指令来源，先归档，不能伪造助手/模型为权威。来源归档后管理失败不撤销原文、不自动向 observe 投递。重放同 request_id 应使用同 source.event_id，避免重复来源；推荐 source ID 为 `hy-management:<request_id>`。Y 路由创建来源，HTTP 不接受用户指定 event_id/时间/角色。

`workspace` 返回管理能力与限制；`profile/history/operations` 为只读。Y 不绕过缺失扩展：未装配时 API 501、UI 显示具体限制。现有中立 listing/detail 继续可用。通用 correction/deletion 能力仍 false，因为它们要求原子修订比较。

Y 实现为 `HyAdministration.extension()`，`extension_namespace="hy_memory"`。构造参数 `serialized_writes=False` 默认拒绝受控写；由 X 的可信装配在核对唯一拥有者/后台语义写关闭/V primitives 实测后显式选择 True，不能由 HTTP 设置。接线不得仅加 Runtime 方法后遗漏这个默认关闭门。Runtime 在同 request_id 重放时复用已归档 source 的原时间和会话，核对角色/正文一致后再调用扩展；不能每次用新的 occurred_at 冲突覆盖旧来源。

## Y 的操作语义

Y 在 Hy method 的同一 RLock 内校验条目 user/agent/source、比较完整可见修订指纹、持久写 running 审计、调用一次 SDK、独立读回，再写 completed；全程沿既有 engine.owner 独占租约，SDK 后台语义写必须关闭。此保证叫“唯一拥有者串行修订检查”，不是 SDK 原生 CAS。不能允许第二 writer 绕过租约。若不能核对该前提，写能力 false。

审计位于可信 Hy state root 下 `management.sqlite3`，不接受 HTTP 路径。记录 request_id、动作、条目、预期修订、用户 source ID、内容摘要、时间、结果状态及稳定错误码；原文保留在平台来源账本，审计不复制完整正文。重复同请求不重发 SDK，异载荷同 ID 拒绝。异常/读回不符标 uncertain；取得新独占拥有权后原 running 变 uncertain。uncertain 不自动重试，UI 要求先重新核对；completed 纠正来源通过该审计补入详情，不能假称 SDK meta 已更改。

受控写仅接受 `l2_fact/l3_summary`；画像、原始记录、保留层不直接更改。审计中有 running/uncertain 的条目拒绝新的请求 ID 再次写入，尚无自动解锁/回滚/人工判定 API。Hy recall 同时叠加 completed 纠正的真实平台来源；有未确认管理操作的条目暂不注入回答，并返回 `hy_management_uncertain_items_excluded`。未到 SDK 的权限/能力/修订拒绝不会生成 completed 审计；UI 保留请求编号，平台来源归档及守卫由 X 证明。审计与 SDK/平台来源不是一个事务。

基本画像为聚合结果，不保证其 ID 可交给普通 get。Y 在独立 profile 详情投影中回看正文和可得来源，不对聚合 ID 调用 get/update/history。仅当 V 证明独占 user/agent/source 时开放；否则 profile capability 保持 false。画像响应如提供 user_id 必须匹配；原生 layer 须为 l0_basic_info，未知时间不补造。

## HTTP 与 UI

在现有 `/api/memory-engine/hy` 下：GET workspace、profile、operations；GET items/{id}/history；POST items/{id}/corrections、POST items/{id}/deletion。写 body 为 `{request_id,revision,content}` 或 `{request_id,revision,confirmation:"删除这条记忆"}`，请求共享会话/同源/CSRF 与启动权限。错误 403 权限/暂停，404 缺失，409 修订/请求冲突，501 能力/接线不支持，503 不确定/引擎失败。失败不显示成功、不自动重试。

前端分页使用真实 offset/limit/total。SDK 无正文检索，当前页筛选明确标范围，不借 search 触发可能写状态或外部费用。基本画像按 capability 启用，未知来源/时间、部分来源读取失败如实显示。L4/L5 保留层、Graph/Intention/System2 未启用；旧库独立保留，不提供旧库按钮的隐式回落。

V/X 接线与 Z 组合软件验收已完成，真实 SDK 副作用和前后端证据见 [Z 报告](parallel/Z-hy-release-integration-20261019.md)，不代表已切换日用或设备体验通过。

Z收尾：平台/worker共用确定性写资格检查，写running前拒绝非法ID/NUL、历史非latest、未证明来源/非user，worker写前重查；删除仅允许显式孤立当前L2/L3。列表以完整get构造稳定修订；暂停精确403/`memory_write_paused`。可见演化版本ID一并保留，completed来源逐版本叠加，任一可见版本running/uncertain则排除整段链头。

可信回执覆盖worker/process/management_rpc/sdk_bridge四文件摘要，在SDK创建前核验后才设置进程管理flag，日用settings不能自行授权。首次空库证明与重开核对、两份owner锁、实际RPC能力共同决定画像与受控写。见 [ADR-0185](../adr/0185-verified-hy-management-and-visible-history.md)。

## ADR（架构决策记录）HY-UI-001：专属受控管理

状态：方案由 ADR-0185 接受并经 Z 组合软件验收；保留 Y 初始问题与替代方案，不改变 ADR-0181，不提前填日用/实机结果。

问题：通用管理契约要求原子修订，SDK 未提供；直接启用通用写会误报并发保证，使用 SDK update 又无法带上新用户来源。

决定：通用写能力继续 false，专属管理经 Runtime 守卫、引擎唯一租约、方法串行锁和独立持久审计执行。SDK 与平台来源不宣称事务；崩溃/读回不符保守隔离未确认条目，完成纠正的来源通过审计叠加至 recall。旧个人库不迁移，管理库只随可信新 Hy state resource 备份/恢复。

替代：直接开放 SDK update/delete 无法说明并发与来源；修改 SDK 引入跨存储事务扩张范围且不可稳定复现；只保留 list/detail 无法满足用户纠正需求。当前方案可独立禁用 serialized_writes，保留新库与旧引擎回退，不自动清理持久审计。

代价与验收：增加一份有明确来源 ID 的操作账本；uncertain 无自动解锁，需后续明确的人工核对方案。模型派生可能保留历史内容，单条删除不等于隐私擦除。候选必须覆盖并发旧修订、重复/异载荷请求、部分提交、重启和真实来源；真实 SDK 写副作用、X 守卫与组合恢复未通过前不得开启日用管理写。
