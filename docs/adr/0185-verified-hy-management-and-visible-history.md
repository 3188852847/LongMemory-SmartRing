# ADR-0185：经实证开启的 Hy 管理与可见历史隔离

日期：2026-10-19。状态：接受本轮组合实现及隔离软件验收；正式切换和设备体验随后登记。承接 [ADR-0181](0181-neutral-memory-backend-and-platform-sources.md) 的来源所有权与 [ADR-0184](0184-shared-campaign-budget-and-owned-model-gateway.md) 的原预算池，接受[管理契约](../development/hy-memory-management-contract.md)中 HY-UI-001 的受限串行方案，不改写旧阶段结果。

## 决定

通用 CAS（原子比较并交换）能力继续 false。专属管理只有真实 SDK 原语验收、后台语义写关闭、精确 RPC 摘要、引擎与来源两份独占锁、Runtime 写开关和 HTTP 启动权限共同满足才开放。可信回执在 SDK 创建前核验，才设置进程管理 flag；日用 settings 不能自行授权。画像额外要求在持锁的新空库创建持久 user/agent/source 范围证明，重开再核对；旧库不能开开关补发证明。

日用请求将画像注入回答时，实际画像能力证明也必须成立，否则拒绝启动并关闭自有资源；不能用界面隐藏代替回答注入边界。

平台和 worker 共用确定性输入/范围/当前版本资格规则。平台在写 running 审计之前拒绝非法 ID、NUL 正文、未证明来源/非 user、历史非 latest 条目；worker 实际写前再次复核。删除只接受明确无前驱/后继的当前孤立 L2/L3，任意演化链成员拒绝，避免 SDK 修链/恢复旧值扩大单条范围。

通过资格检查才记录 running，执行一次原生 SDK update/delete，独立 get 读回后记录 completed。异常、读回不符、重启遗留 running 保持 uncertain，不自动重试或猜回滚。来源先归档，重复请求复用原 source，异载荷拒绝。单条删除不擦除原话、历史或备份。

SDK 把可见旧版本正文合入链头。适配器保留经过结构校验的可见版本 ID，逐版本叠加 completed 纠正的真实平台来源；任一可见版本 running/uncertain 时整段链头不注入回答。列表用完整 get 构造修订，避免 SDK list 缺字段造成正常纠正误判冲突。

## 代价、替代与回退

管理账本、SDK、来源库不是同一事务，没有原生 CAS、全隐私擦除或自动解锁。逐项 get 增加本地只读 RPC，换取完整稳定修订；保守排除整段链头暂时减少证据，但避免未确认历史注入。直接开放链删除或只看头条目不能满足范围与隔离要求。

可撤回管理回执、关闭进程写权限后重开为只读，保留引擎、平台来源、管理账本、management-scope 与原预算池。回退不覆盖个人旧库、不自动清理 uncertain、不获得预算外调用权；恢复须覆盖全部持久资源。

## 验证边界

真实 Runtime→HTTP→RPC→SDK 闭环、SDK/Chroma 单条副作用/演化链/持久证明/重启、真实前后端 HTTP、原池流式开发探针与受影响旧链通过；精确提交、数量、产物及限制见 [Z 报告](../development/parallel/Z-hy-release-integration-20261019.md)。旧 V 17 题保留原条件结果，没有重新采样。软件验收不是实机声音、播放或打断验收，主动交流仍暂停。
