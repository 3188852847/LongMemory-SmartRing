# X：Hy 逐层真实内容发布准备

日期：2026-10-21。状态：**准备完成，最终候选、真实 SDK 证据和生命周期批准待交接；未部署**。

## 任务、归属与本次完成标准

用户要求 L0–L7 每层浏览真实内容，并修复运行路径点击跳页顶。AA 负责后端契约和实现，Y 负责前端，Z 独立审查；X 唯一负责后续正式生命周期及经审查的新管理证明（management proof）部署。本轮先查准入、保全当前状态和准备候选绑定流程，不停止服务、不重签或替换正式 proof，不调用真实模型。

工作树为原 X 隔离树，分支 `codex/x-hy-layer-data-release-20261021` 从 `34b2111d646cb1672bdad62603174e0da7c57f6b` 创建。此前 `codex/x-fast-asr-envelope-20261020` 的 `d8aed974a352dcba12a9e5bda3b78041e3002d26` 及旧 ignored 工具/证据保留，没有 reset、清理、合入 main 或推送。路径匹配检查未发现引用 X 工作树的 Python/Node/CMD 遗留进程；这不是机器上没有其他会话进程的声明。

仅新增本报告。文档 manifest 和根文档由主会话/Z 维护，本轮不改。任务会话 ID：`01a153df-8682-7e33-80b5-1102ee2b54c8`。

## 只读核查事实

2026-10-21 01:38:47（北京时间）的准备快照只包含状态、计数、路径和摘要；未读取个人对话正文。该时刻结果不代替未来停服前的新核对。

| 对象 | 观察结果 |
|---|---|
| 主线 | `34b2111d646cb1672bdad62603174e0da7c57f6b`；tracked 干净，原 6 个 unknown/untracked 条目保留 |
| 正式服务 | 启动器 PID 29464，ready；没有 shutdown/start 操作 |
| 正式前端 | 仍为上一轮 `09d1ba1` 的产物；manifest SHA-256 为 `d66cb33a09190bafc5458cdaae40d7304f8650bc49b0f8b648a71a5f2a1da59b` |
| 校园免费账本 | 38 completed、1 unknown、0 reserved；API attempt_count=39、unknown_or_inflight=1；该 1 条是已冻结历史 unknown，未视作正在调用、未结算 |
| 历史 unknown | 只读 `mode=ro`、`query_only`、状态分组和固定终结诊断/时间；不可逆摘要仍为 `487e2320d66317f1c25965c951ebd6943bf7874fe6619dfb35b505d2d5b81529`；不输出原始 ID |
| 忙碌状态 | 缓存设备连接/用户会话、API processing、延后 awaiting/running、TTS active/unfinished 均为 0 |
| 声音 | 当前声线 warm，ready，model_streaming=false，guard applied；档案 digest 仍为 `3bcf2fa4dbd8e72b642ac64d097d798d0c81f29a95c84373d36d722c77ac0d9f`；未合成试听 |
| 后台 | proactive=`paused_backend_unsupported`，consolidation 关闭 |
| 旧 paid 账本 | 文件摘要与上一轮发布记录相同，unknown=1、held=8388608 微元保留；未清账、释放或转入校园授权 |
| SDK 环境 | 正式 deployment 仍引用 V 树 `local/runtime/hy-memory/.venv/Scripts/python.exe`，声明 Python 3.12.13；解释器字节摘要匹配 deployment。本轮没有执行、修改或安装 V 环境 |

现场读取只用了既有账本的只读连接及本地缓存状态 GET，没有 `open_campus_calls`、业务构造、初始化、恢复 API、模型调用或设备指令。旧部署 helper 未作为本轮生命周期工具执行。

## proof 准入：代码事实与缺口

[可信装配](../../../src/longmemory/methods/hy_memory/assembly.py)要求四字段精确匹配：`sdk_version`、`rpc_source_sha256`、`real_sdk_rpc_verified=true`、`semantic_background_writes_disabled=true`。摘要不匹配时，在 `HyState` 和来源装配之前拒绝，错误为 `hy_management_verification_identity_mismatch`。通过证明之后仍核对外部拥有者租约、SDK/Python 版本和真实 RPC 能力，不因 UI 要显示按钮而放宽写入。

当前原语摘要为 `e358debcfa870e09c6072645758d70ac4fa6792bcfb1dd5d589f3c1490657e04`；正式 proof 文件摘要为 `525e50f3e87cecd1491e15cda4d8ee30bc90c1267b3f2b2418d25d4388c54479`，与当前代码一致。现有指纹以 SDK 版本和七个文件名及规范化换行内容计算：worker、process_client、management_rpc、sdk_bridge、short_embedding_input、sdk_observation、observation。AA 的新逐层模块及其语义依赖必须纳入候选指纹，不能仅改 worker 导入语句后假称新模块已经绑定；以最终清洁候选的实际函数为准。

[既有离线回执工具](../../../tests/fixtures/hy_management_receipt.py)不是密码学签名。它要求调用者已经审查背景语义写关闭、精确完整 HEAD、清洁源码、既有 SDK 解释器、全新 ignored 输出目录；使用隔离 HOME/TEMP、合成目录、Windows Job 管理后代和有界超时。JUnit 必须有用例、零失败、零错误、零跳过，执行前后源码/管理指纹/解释器摘要相同，才输出新 proof；不修改正式配置。

**既有工具的 `TESTS` 固定为两份旧测试**：`test_hy_memory_management_rpc.py` 与 `test_hy_release_management.py`。它们证明既有管理兼容，不能单独覆盖新逐层接口。仅让该工具在新 HEAD 上输出新摘要，仍不足以批准本轮。`management_identity` 调用候选自身的指纹函数，并非外部硬编码七文件列表；须同时审查候选函数纳入了全部新语义模块。

## Z 需要交根审查的离线证据

在最终候选清洁提交上完成下列证据，全部为合成库和真实已安装 SDK 2.0.3，不接个人库、不联网调用模型、不安装下载。X 当前不执行该验收，也不因准备工作而使用 V 解释器启动新 worker。

| 证据 | 本轮需要证明的内容 |
|---|---|
| 精确源码与环境 | 最终 HEAD/tree、源码摘要、指纹函数及文件清单、原语摘要、SDK 解释器摘要与 Python/SDK 元数据；测试前后不变，导入及子进程源码来自候选 |
| 基础管理兼容 | 既有两份真实 SDK 集成测试的回执、JUnit、工具摘要与独立审查标志；proof 四字段不手填、不复制旧回执 |
| 新逐层真实 SDK 测试 | 单独列出实际测试路径和用例清单，绑定相同 HEAD/源码/原语；真实 JSONL/Chroma、合成 transport、零跳过 JUnit。可扩展经审查的签发 runner，或另给同候选补充回执；只交旧工具成功不足以放行 |
| 八层与真实范围 | 精确 user/agent/source/layer/state/ID 下推与回包复核；空输入、空页、分页、末页 total 证明条件、跨范围同 404、真实关闭/保留层不伪装 empty，write/use 暂停仍可读 |
| L0 与 L6/L7 | L0 完整 SDK 合并算法、版本链、范围 stamp、超限/异常 namespace 拒绝；L6/L7 仅既有 VDB，未开图的 coverage 与 total 保留未知，不打开/创建 Kuzu、不走 SDK list/get 图回退 |
| 并发与只读 | Runtime/Hy/RPC 非阻塞锁，忙立即 503，5 秒边界与关闭语义，无重试/暗中排队；同一 owner worker、既有 SDK loop/collection/executor，不开第二 client/连接、不调用 search/LLM/BGE、不回写状态 |
| 内容保护与兼容 | 合成数据允许前后逐项摘要、来源库与原始记录保留、无语义写入/后台任务/模型端点连接；普通 SDK 管理语义、旧接口、关闭和重启重开仍兼容 |
| 前后端组合 | 参数/鉴权/错误码、真实候选 API 与浏览器组合，有限字段/正文截断/时间未知保留；运行路径点击后滚动和选择正确，冷开导航一致；不拿模型 mock 或 SDK 跳过当真实 SDK 证据 |

AA 契约来源为其独立树 `docs/development/hy-layer-data-contract.md`（2026-10-21 只读快照）。实现、测试路径及最终契约尚待 AA/Z 定稿；X 不修改该会话文件，也不为其填验收通过。背景语义写关闭必须由根/Z 实际审查后确认，不因命令需要而机械勾选。

## 后续候选绑定及生命周期顺序

1. Z 交最终清洁候选、AA/Y 契约和真实组合证据、完整构建逐文件清单/manifest/源码绑定，以及上述离线 proof、receipt、JUnit。根先独立审查；X 核对所有证据属于同一候选，不接受旧 receipt 或漂移后的自动重签。
2. 建立**新**部署 helper/config/frozen-plan，基线明确为 `34b2111`，另绑定最终候选、helper/依赖摘要、真实 SDK 新证据、完整新旧 dist、原/候选 proof 字节摘要及完整新检查点路径。上一轮 helper 的 `BASE=eaa65b5`、candidate、artifact、旧检查点均过期，不直接执行，不覆盖旧文件。
3. 准备门只写 X ignored 元数据。候选/proof/证据/检查点任何一项未定均为 pending，stop/apply 均保持未授权；根核对新哈希后分别明确批准 stop 与 apply-restore。当前 pending-binding 不可作为执行计划。
4. stop 前重新冻结当下校园状态计数和既有历史 unknown 摘要，reserved 必须为 0，其他忙碌必须为 0；任何新增/不同 unknown、状态变化或非免费策略即停止取证，不循环重试。38/1/0 是本次准备观察值，不能把它当作未来新快照的替代，也不自动接纳未来变化。先核对主线、当前 PID/创建时间/归属，保存新鲜当前状态，不沿用旧备份。
5. 仅经正式入口受控 shutdown 自有服务，备份完整旧代码/旧 dist/人工配置及新旧 proof、当前完整 Hy 引擎目录及 Chroma/伴随文件/owner 与 scope 证据、来源/角色/聊天旁库、paid/free 账本等，完成一致性与非目标核对。**stop 阶段不写新 proof**；停止后等根合入并推送精确候选。
6. apply-restore 另获准后，核对 main/远端追踪为候选、端口空闲和备份仍一致，再在停服窗口只替换经审的 proof 文件与新 dist。proof 用新文件排他落盘、校验和原子替换，保留旧字节；不手改摘要，不改 deployment/settings/模型/声线/cache/SDK，不初始化、迁移或重建个人空间。
7. 原 `verify_files` 只认所有 protected 文件不变，会拒绝新 proof；新 helper 必须仅对这一**精确目标**建立“替换前旧摘要、替换后候选摘要”的状态门，不把整个配置目录加入忽略，不放宽旧守卫。故障时保留现场，Git 与代码回退仍由根协调。
8. 唯一正式启动器恢复后核对版本/原语/proof 配对、ready/进程归属/声线 warm/保护资源与 paid 字节、免费账本仍为冻结状态；不产生新模型/合成/设备探针。逐层正式读取、浏览器实际内容及滚动验收的精确范围，由根结合最终契约另行明确，不能把准备授权解释为访问个人内容的授权。
9. 回退同时匹配旧代码、旧 proof 和旧前端，保留当前个人数据及新增内容，不用旧数据库备份覆盖现有库；不自动 Git 回退、清账、循环重启，也不以 proof 四字段或构建成功冒充真实体验。

## 本轮产物、验证与待交接

X ignored 目录 `data/test-tmp/x-hy-layer-data-release-prep-20261021/` 保存两份排他新文件，旧文件未覆盖：

- `readonly-preparation-snapshot.json`：SHA-256 `ec22c5a103b0425740ce4bd83038786a0e675e1fea938702a33888d2570046ca`，包含安全状态及受保护文件摘要，不含配置正文/个人原话。
- `pending-binding.json`：SHA-256 `3c9112d1c9e611794465b754ab45a3d43cc5e1d01ec8abb14780949800e30a53`，候选、构建、新 proof、证据与新检查点为空，stop/apply=false；只列拟允许的 proof 和 dist 两个变更目标。

本轮没有新增可执行生命周期脚本，没有运行真实 SDK 或模型测试；未声明 AA/Y/Z 实现或证据已经完成。文档只验证本文件链接及差异，不改 manifest。根交付候选与离线证据后，X 才实现并合成验证新的 proof 状态门/冻结门，再交精确 helper/plan 哈希审查；当前不具备部署放行条件。

实际检查：本文件本地链接检查与 `git diff --check` 通过；准备快照中的 33 个受保护文件及旧 helper/plan 摘要复核未变，新 proof 和可执行冻结计划均不存在。`check_docs.py --only docs/development/parallel/X-hy-layer-data-release-20261021.md --strict` 返回 1，仅报告本文件 `unlisted-document` / `unknown-selection`：按本轮文件归属，manifest 登记留主会话/Z 处理，不能报成严格检查通过。
