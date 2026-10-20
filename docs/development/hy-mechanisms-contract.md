# Hy 固定版机制展示契约

日期：2026-10-21。范围为 `hy-memory==2.0.3`、源提交 `2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed`。本契约追加只读展示，不开启机制、不更换日用配置。固定版事实来自已安装 SDK 源码与平台适配器；不把官方主分支 2.0.4 的说明混入。

官方固定来源：[枚举与数据模型](https://raw.githubusercontent.com/Tencent-Hunyuan/Hy-Memory/2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed/hy_memory/models/memory.py)、[写入与兼容处理](https://raw.githubusercontent.com/Tencent-Hunyuan/Hy-Memory/2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed/hy_memory/pipelines/writer.py)、[模式与场景 API](https://raw.githubusercontent.com/Tencent-Hunyuan/Hy-Memory/2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed/hy_memory/client.py)。本次只读核对这些固定页面和本机安装源码，没有下载/安装/替换资源，也未声明整个 wheel 与 Git 树逐字节一致。

## 前端接线

全站身份使用独立中立 `GET /api/memory-engine/identity`，无参数/body，共享会话鉴权；不会调用旧 `/api/memory-config`，该旧接口契约保持不变。

| 字段 | 精确含义 |
|---|---|
| `schema_version` | `1` |
| `configured` | 已装配为 true；仅显式旧库选择但尚未建 Runtime 也为 true；无选择为 false。不是文件存在性或健康检查 |
| `method` | 已装配 Runtime 的公开方法名；未初始化或未配置为 null，不提前猜测旧方法名 |
| `representation` | 旧 SQLite 为 `atomic_fact`；新后端为 `method_defined`；未配置为 null |
| `legacy_sqlite` | 已装配为布尔值；仅旧库选择为 true；未配置为 null |
| `state` | `available` 表示取得已有 Runtime 的身份；`not_initialized` 表示仅配置旧库；`unconfigured` 表示无配置；这些都不是引擎健康结论 |

锁忙返回 503 `memory_identity_busy`，关闭中/已关闭/异常返回 503 `memory_identity_unavailable`；无配置返回200而非503/501。Runtime.identity 非阻塞尝试 Runtime 锁，不拿 Hy/管理锁；只读公开方法名与装配类别。server 的 provider 只读取现有 `runtime` / `chat_backend._runtime` 引用，绝不调用懒创建 `chat_backend.memory_runtime()`，因此不触发 SDK、建库、status 或账本过期处理。Hy 机制端点同样使用该窥视 provider；无已装配 Runtime 返回503，不会为辨认旧引擎而初始化它。前端错误/忙必须保留未知或旧身份，不回退伪装成旧 L1。

新增 `GET /api/memory-engine/hy/mechanisms`，无查询参数、无 body，沿用会话鉴权。响应字段：

前端机制入口为 `/memories?view=mechanisms`，复用已有 React `/memories` 精确入口，支持直接打开与刷新；构建清单与 nonce 校验不变，未构建为 503。没有新增 `/memory-mechanisms` 路由或任意路径 SPA 回退。标签与选择坐标由 Y 实现。

| 字段 | 类型 / 含义 |
|---|---|
| `schema_version` | `1`，本展示协议版本 |
| `sdk` | `{version, source_commit}`，适配器锁定版本；不是现场探测 SDK 版本 |
| `observed_at` | UTC ISO 字符串，本进程内存读取时间；不是最后成功检索时间 |
| `scope` | `adapter_declaration_and_runtime_gates`；装配声明和内存开关，不是数据库检查或 worker 健康探针 |
| `assembly` | `standard_worker` / `custom_or_unknown`，自定义 factory 不套用标准 worker 的配置结论 |
| `mode` / `scene` | 标准装配为 `pro` / `chat`，未知装配为 `null` |
| `runtime` | `{write_enabled,use_enabled,engine_initialized,worker_health}`；前两项当前 Runtime 内存开关，初始化标记不能解释为健康，`worker_health="unknown"` |
| `modes` | `[{id,title,description,selected}]`，lite/pro/ultra 固定版差异，未知装配 selected 为 null |
| `layers` | `[{id,number,title,sdk_support,integration,description,evidence,count}]`；L0 基本信息加 L1–L7 七层；`count=null`，不伪装成 0 |
| `mechanisms` | `[{id,group,title,sdk_support,integration,description,evidence,endpoints}]`，双系统、写入、存储、召回、演化、管理、运行等 |
| `evidence_gaps` | 字符串数组，明确缺失逐项写轨迹、历史完整性、已发生召回/最终注入证据等 |

`sdk_support` 为 `implemented` / `reserved` / `platform`；`integration` 为 `configured` / `disabled` / `not_integrated` / `reserved` / `unknown`。configured 只表示代码接入，不等于本次运行已成功执行、有数据或质量通过。`evidence` 是公开的仓库/SDK 相对路径数组，不含本机路径、用户身份、模型名称、凭据、提示正文。现有可信配置由 worker 显式关闭的项目标 disabled；受环境变量影响且未探测的可选细节必须 unknown。

失败：未装配 Runtime 为 503 `memory_runtime_unavailable`；旧引擎/无 Hy 扩展为 501 `memory_backend_capability_unsupported`；关闭中/已关闭为 503 `hy_mechanisms_unavailable`；Runtime 或 Hy 锁繁忙为 503 `hy_mechanisms_busy`；任何查询参数为 400。标准读取不调用 `runtime.status()`（它会过期处理圆屏账本）、不启动 SDK、不调用 workspace/profile/search/list/diagnostics、不扫描库或触发模型，write/use 关闭仍可查看。

锁边界：依次尝试 Runtime 与 Hy 的 RLock，均 `blocking=False`；拿不到立即 busy，不排队等模型/管理。成功后只在锁内构造固定小目录和读取布尔开关，finally 释放；不持锁调用其他服务或持久层。开关与 closing/closed 在同一个 Runtime 临界区读取，Hy 初始化标记在同一个方法临界区读取。HTTP 用既有线程卸载；这不是实时延迟保证，事件循环/线程池饱和仍可能延迟调度。前端遇 busy 保留上次结果并标为旧快照，不自动密集重试。

## 编号与边界

Hy 的 L0 是基本信息聚合；平台原话归档是独立来源账本，不能贴成 Hy L0。L1 RAW、L2 FACT、L3 SUMMARY 为实际类型；L4 IDENTITY 只保留历史兼容，新提取不再写；L5 KNOWLEDGE 为保留层；L6 SCHEMA、L7 INTENTION 有实现，但本装配图关闭、pro 模式、意图提取与队列关闭，不表示已启用。

SDK 检索真实通道为 `schema/normal/proactive`，不是 README 中“画像、普通、主动”三路的字面协议。平台额外可选读取基本画像；实际注入仅该画像加 normal，并排除管理不确定条目与其可见版本链。schema/intention limit 均为 0。此次端点不能证明某一回答实际注入了什么。

已有证据入口保持原契约：`/api/memory-engine/items` 有界活动条目；`/items/{item_id}` 详情和可得来源；`/sources/{event_id}` 平台原文/投递状态；`/hy/profile` 聚合画像（须现有 scope capability）；`/hy/items/{item_id}/history` SDK 历史（当前关闭，不可把空数组解释为无变化）；`/hy/operations` 平台管理审计；`/hy/workspace` 实际管理能力与 HTTP 权限。新端点只列入口模板，不调用它们，也不生成虚假 trace。未接入列表按层过滤、图浏览、完整写入决策、已存召回/注入轨迹和 unknown 管理人工解锁均须明确呈现缺口。

## 决定与验证范围

这是现有 Hy Runtime 白名单扩展的追加操作 `mechanisms`，不新增中立 Memory Core 概念，不改变数据库/持久身份/worker RPC。标准装配在主进程保留非敏感配置来源标记；自定义 factory 默认为 unknown。worker/process/management primitives 指纹覆盖文件均不修改，既有管理证明不被静默重签或失效。

清单登记由主会话整合：本文件及 [AA 本轮记录](parallel/AA-hy-mechanisms-20261021.md)，关联 `methods/hy_memory/mechanisms.py`、`administration.py`、`assembly.py`、`application/memory_runtime.py`、`entrypoints/api/routes/memory_engine.py` 与对应测试；本会话不修改 manifest。新增只读展示沿用现有专属边界，不新增框架绑定或数据模型决定。

## 固定版一级机制覆盖矩阵

盘点范围是固定 SDK 的 Chat/Working/Coding 一层机制与平台接入边界；不是每一个环境变量、内部评分常数、MemHub 外部产品、论文实验或官方专训模型部署的功能验收。共46个机制目录项；L0–L7和lite/pro/ultra另有独立数组。标准 worker 的声明如下，实际使用仍受运行门和预算限制；unknown 项不通过现场执行来“补齐”。新增功能不沿用本表推断，须按其固定源码复核。

| 一级机制 | 目录 ID | 固定版支持／当前集成／观测边界 |
|---|---|---|
| 双系统 | `system1`, `system2` | 均有实现；S1接入，S2关闭；没有本次执行证明 |
| 原文、提取与冲突协调 | `extraction`, `reconcile_candidates` | 有实现；提取接入，协调候选具体融合未知；无逐项决策轨迹 |
| 版本演化与独立历史 | `version_chain`, `sdk_history` | 演化可见版本接入，history关闭；不可混作同一记录 |
| 向量与关系图 | `vector_store`, `graph_store`, `storage_backends` | Chroma接入，图关闭，其他后端未接入；不探测文件／计数 |
| 普通、画像与SDK三通道 | `normal_recall`, `profile_recall`, `schema_recall`, `proactive_recall` | normal接入；画像按include_profile；schema/proactive limit=0；不现场召回 |
| 最终注入 | `answer_injection` | normal＋可选画像，管理不确定链隔离；无持久逐答证据接口 |
| 改写与自动场景／时间解析 | `query_rewrite`, `automatic_routing` | SDK支持；改写关闭，平台固定chat/default，未接agentic |
| 读取器选择 | `reader_dispatch` | SDK有legacy/hybrid（向量＋BM25）；子进程固定legacy，不能与写协调融合混淆 |
| 强度排序与访问回写 | `recall_strength` | SDK支持；标准装配显式关闭 |
| 情景家族与摘要 | `episode_memory` | session/dynamic/series episode、摘要、capsule与成员展开有实现；有效配置未知；平台无finalize入口 |
| 实体与标签候选 | `entity_tag_recall` | entity store/NER/tag index/动态标签向量有实现；有效配置与命中未知 |
| 层次、多种子与系列组合 | `hierarchy_bundles` | 有实现；开关与实际组合未知 |
| 局部cross-encoder | `local_rerank` | 有实现；有效开关／加载未知，不把BGE当重排模型 |
| 时间过滤／日期视图 | `temporal_recall` | 有实现；平台不传created_after、未接agentic解析；内部加权不在观测范围 |
| 融合、去重、护栏、配额与格式 | `result_shaping` | 有实现；具体分支和分数未知，非统一量纲 |
| 检索子句与补充命题 | `retrieval_clauses`, `supplemental_propositions` | 有实现；子句显式关闭，补充命题未知 |
| 可选增强总览 | `optional_recall_enhancements` | 可探索的上述家族总览；不是“全部已开启” |
| 图式归纳与演进 | `schema_evolution` | 有实现；pro/图关闭，平台无图浏览 |
| 跨域归纳 | `cross_domain_sweep` | basic→core图式归纳有实现；当前未接evolve/sweep |
| ultra画像目录与具体事实补充 | `ultra_persona_catalog` | balanced catalog/specific supplement有实现；pro不启用，不冒充当前L0 |
| 意图形成与过期处理 | `intention_extraction`, `intention_lifecycle` | SDK有VDB L7提取、过期惰性转L2、复本删除；当前提取关闭、limit=0，不执行检索写副作用 |
| 生命周期与滚动配置 | `memory_lifecycle` | active/superseded/negated/conflicted/shadow/archived类型存在；当前数量未知。仅见rolling-delete配置声明，未证执行入口，不承诺自动删除 |
| Working 双层 | `working_route` | 会话事实＋可复用经验、分别协调并互链；平台未接工具trace/工作场景 |
| Coding 双层＋diff版本链 | `coding_route` | 在双层外附原话/代码版本差异链，可workspace/branch隔离；平台coding关闭、未接入 |
| 来源及范围隔离 | `scope_isolation` | user/agent/source固定过滤、保留session；平台长期跨会话，未接workspace/branch选择 |
| 受控管理 | `administration` | 平台接入；真实权限见workspace，不声称SDK原生CAS |
| 原文追溯与处理状态 | `source_trace` | 平台来源账本；只用可证明ID，缺来源保持未知 |
| 管理审计和不确定隔离 | `management_audit` | 平台接入；与SDK history独立，无自动解锁／重试 |
| 持久化与重开 | `persistence` | 平台隔离来源／引擎、租约和身份接入；此接口不重开或检查磁盘 |
| 缓存和后台队列 | `cache_and_tasks` | SQLite缓存接入，画像缓存/S2队列/意图缓存关闭；其他写记录细节未知 |
| 可观测性 | `observability` | SDK metrics/debug/trace关闭；平台安全计时和管理审计接入，未有完整持久trace |
| 多客户端共享Runtime | `shared_runtime` | SDK实现存在；平台独立子进程，无共享多client入口 |
| 模型与向量提供方 | `provider_endpoints`, `embedding_override` | 可信端点／网关装配接入；SDK逐调用端点覆盖未暴露给平台 |
| 平台主动联系 | `platform_proactive` | 当前Hy后端暂停旧调度；与SDK proactive返回通道分开 |
