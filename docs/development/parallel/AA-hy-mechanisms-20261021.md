# AA：Hy 固定版机制目录与只读观察

日期：2026-10-21，Asia/Shanghai。起点 main `eaa65b5b2979add8fd513bba07e19e64d5afa36b`；分支 `codex/aa-hy-mechanisms-20261021`，隔离树 `local/worktrees/aa-hy-mechanisms-20261021`。本轮后端交付，前端由 Y 接入，组合审查由 Z 执行；本会话不 merge/push、不修改日用服务/配置/数据/设备。

## 范围与事实

已读 AGENTS、本机公共 README/索引/通用/机器/Python 规则、project-doc-maintenance 技能、文档入口与清单、方法边界、架构/流程/仓库边界、Hy 管理契约及 Z 发布/低延迟审查。固定版为 `hy-memory==2.0.3`、提交 `2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed`；只读核对 V 树已安装 SDK 的 enum/config/client/writer/reader 和官方固定提交页面，没有以主分支 2.0.4 的 README 替代协议。未运行 SDK client、加载模型或读取个人数据；未下载/安装/移动 V 环境。

Hy L0 是基本信息聚合，平台原话是独立来源账本。L1–L7 为 RAW/FACT/SUMMARY/IDENTITY/KNOWLEDGE/SCHEMA/INTENTION；L4 新 writer 不再生成、保留历史兼容，L5 未实现保留，L6/L7 有固定版实现但标准 worker 的 pro/图关闭/意图关闭使其不接入。三种模式、双系统、存储、写入与冲突、演化版本、三路返回与实际注入、管理与持久化均有结构化目录。SDK 原生通道为 schema/normal/proactive，平台实际只选 normal 与可选基本画像；不把 SDK proactive 通道称为设备主动联系。

## 改动与契约

- [契约](../hy-mechanisms-contract.md)：字段、来源、错误、锁边界、证据入口和缺口的单一事实入口。
- `methods/hy_memory/mechanisms.py`：固定小目录，8 层、3 模式、46 类机制；SDK 支持与平台接入状态分开，未知计数为 null。补充固定版一级机制覆盖矩阵，Working 双层事实/经验、Coding diff链、reader选择/重排/情景/实体/层次/时间/生命周期、跨域归纳/ultra画像补充均可探索。没有把尚未盘点的全部内部参数或 MemHub 产品宣称已覆盖。
- `assembly.py`：主进程记录标准 worker 来源标记；自定义 factory 默认为 unknown。未加入持久身份或管理证明。
- `administration.py` / `application/memory_runtime.py`：白名单追加 mechanisms。两级 RLock 都尝试非阻塞获取，繁忙立即 503；成功时只构造内存目录和门状态。关闭中或已关闭拒绝；不调用会过期处理圆屏账本的 status，不等待模型执行锁。
- `routes/memory_engine.py`：新增 GET `/api/memory-engine/hy/mechanisms`，沿用会话鉴权，拒绝参数/body，稳定脱敏错误；不受 write/use 关闭影响。
- `routes/memory_identity.py` / `server.py` / Runtime.identity：新增全站中立 GET `/api/memory-engine/identity`，分已装配、仅旧库配置未初始化、未配置。只窥现有Runtime引用、非阻塞Runtime锁；不调用懒创建入口/status/SDK/SQLite。Hy机制端点也用同一窥视provider，避免普通selector触发旧引擎懒初始化。旧memory-config契约不改。
- 前端最终采用 `/memories?view=mechanisms`，复用现有精确 `/memories` 静态入口；不新增后端页面路由。此前本树临时加入的 `/memory-mechanisms` 及断言均已撤回，正式差异不含静态托管修改。

configured 只是代码接入，不表示健康、已经执行、有记忆或质量通过。engine_initialized 只表示已初始化对象，worker_health 保持 unknown。可选环境召回增强没有有效快照，保持 unknown；本轮不探测来补数，不制造新 search/trace。管理能力仍由已有 workspace 实际 RPC 与权限返回，机制页不替它授权。

## 验证

主项目既有 Python 解释器只读复用，显式将本树 src 放首位并核对 import 文件来自本树。所有测试仅合成目录与 OS 分配的随机端口，排除日用端口；SDK/模型/实际外部请求为 0。

| 检查 | 实际结果 |
|---|---|
| 首轮新增用例 | 7 通过、2 失败：测试在 configure 前注入禁止 status 的替身，而 configure 本来返回 status；调整准备顺序，不改生产 configure 或其测试前提 |
| 第二轮组合 | 96 通过、1 失败：Windows owner 租约被 OS 锁定，测试读摘要报 PermissionError。保留文件集合检查，不绕过租约，只对可读数据库文件作前后摘要 |
| 八份后端定向组合 | 96 passed，1.57 秒；包括新端点、管理/HTTP/Runtime扩展、后端、守卫、版本演化和批来源叠加 |
| React 静态托管前期核对 | 临时精确新路径方案 6 passed，0.83 秒；最终采用 Y 的现有路径加查询参数，该临时实现已撤回，不能作为最终新页面路由验收 |
| 管理证明覆盖源码 | worker/process_client/management_rpc/sdk_bridge/short_embedding_input/sdk_observation/observation 七份内容相对起点完全不变；原/新摘要均 `e358debcfa870e09c6072645758d70ac4fa6792bcfb1dd5d589f3c1490657e04`，没有重签证明 |
| 中立身份首次接线测试 | 14通过、3失败：极简测试backend缺少正式Chat路由构造所需database，未进入身份请求；改为真实ChatBackend＋合成旁库，不改生产契约 |
| 身份与机制修正后 | 17 passed，0.76秒；身份有/无装配、旧引擎、鉴权、无参数/body、关闭、锁忙、动态窥视均覆盖 |
| 最终11份组合 | **191 passed，6.96秒**，0失败/0跳过；含正式server接线、身份、机制、管理、Runtime扩展、守卫、演化、来源叠加、静态托管与原console用例。身份测试在应用构造完成后禁止SQLite连接、status与懒初始化，证明请求自身不读写库；应用初始合成旁库创建不混作请求副作用 |
| 窄文档检查 | 仅内存补登记两篇后调用正式audit，2篇检查、findings为空；未写manifest，不冒充主会话正式登记。46个目录ID全部出现在覆盖矩阵，无重复ID |

正常、未知装配、无管理/旧引擎、权限/无Runtime、关闭/关闭中、暂停、两级锁繁忙、异常脱敏、零RPC/初始化、合成数据库字节不变均覆盖。不能把单元客户端替身当作真实 SDK/日用/设备验收。正式前端、远程 CI、真实模型和生产重启未执行。

文档清单由主会话统一维护：须登记本记录与契约，关联上述后端文件与 `tests/unit/methods/test_hy_mechanisms.py`、`tests/unit/entrypoints/test_memory_identity.py`，并与 Y 新页面建立相关引用。本会话不改 manifest，检查时内存补登记只用于窄验证，不冒充正式登记通过。

## 交接限制

Y 按契约接 `/memories?view=mechanisms` 与新 API；遇 busy 保留旧快照并标旧，不密集自动重试。已有条目、原文来源、聚合画像、history 和 operations 使用各自现有受控入口；无完整逐写决策/已存逐答注入轨迹/图浏览/服务端按层过滤/unknown人工解锁就明确显示缺口。

Z 审查组合后由主会话合入、登记清单、验证正式构建和后续运行安排。本分支无剩余必要实现；生产配置、个人库、预算、服务和硬件均未操作，当前运行版本并未切到本提交。
