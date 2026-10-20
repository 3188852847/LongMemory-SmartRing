# X：Hy 逐层内容发布工具与证据接口

日期：2026-10-21。状态：**工具合成验证完成，最终候选及 root 分阶段批准待交接；没有正式生命周期操作**。本报告追加于 [准备记录](X-hy-layer-data-release-20261021.md)，不改写 `8393eab` 的准备结论，也不修改其他会话文件或 manifest。

## 工具范围

分支仍为 `codex/x-hy-layer-data-release-20261021`，发布基线固定 `34b2111d646cb1672bdad62603174e0da7c57f6b`。新工具均在 X 的 ignored 目录 `data/test-tmp/x-hy-layer-data-release-prep-20261021/`，旧 helper、旧计划及旧失败证据字节保持。

| 文件 | 职责 | SHA-256 |
|---|---|---|
| `deploy_layer_data.py` | prepare/stop/apply-restore/recover-baseline 阶段入口、精确 proof 状态切换、完整原保护集合与正式恢复核对 | `71b66a494eaa974beeb8e6575e6b622ebb101177cf7b86f5470f8dc33cc91575` |
| `layer_release_evidence.py` | 最终候选、真实 SDK 原始回执/JUnit、Z 审查、原语文件与前端绑定；只读验证，不签发 proof | `8579e3c8f9fc2120f4512cf1f137eafccc252a03f644c09f290f3eda424c3c2a` |
| `test_layer_release_tools.py` | 仅合成文件、伪 SDK 身份文件和隔离配置的工具测试 | `07ccbc21c51ce408a0c08627d7ee97092dd1130cfc61894f12e79f8147c4677f` |
| `Z-evidence-input-contract-v1.json` | 交 Z 的确切字段、原始 receipt 兼容格式、JUnit/源码/SDK/前端绑定算法 | `6da33723b728f0a412df6a197eeacf5c9b0d5d5030e0d111e54b4c0df2142cb5` |
| `pending-tool-config-v1.json` | 完整 schema 的待交接配置；候选、operator 最终提交、证据、新 proof、校园新快照和新检查点尚为 null | `022c62dfa6b3fa4b70d2e184f2c433ea9896e447bf09ff7faf53a1cd54a7affe` |

沿用上一轮已审生命周期主体，复制后修改为新基线和 `local/archive/hy-layer-data-release/` 新检查点域；没有执行旧 helper 或沿用旧执行参数。旧 operator library 仅调用 launcher/ps_json/listeners/docker 四个受审函数，未调用其旧 assert_code、配置、部署或预算修改入口；库和数据路径清单字节也进入冻结摘要。

## 提前交 Z 的证据接口

接口文件已经在工具最终收尾前单独交根，以便 Z 直接按同一格式产证。两组 evidence_suites 的 role 必须分别为 `legacy_management` 和 `layer_data`，不能复用旧管理的 JUnit 冒充新层测试。

每组接收既有 `hy_management_receipt.py` 的原生字段：version=1、kind=`verification_receipt_not_cryptographic_signature`、source 的 head/tree/python_source_sha256、SDK 解释器摘要及 Python/SDK 版本、rpc_source_sha256、status=completed、test_count、junit_sha256、semantic_background_writes_reviewed_by_caller=true、error=null。原工具的其他元数据允许保留；逐层补充 receipt 使用同样核心格式，**无需自定义签章或新 kind**。test_paths 是可选附加字段，若有必须与配置精确一致。

旧组仍要求原两份管理集成测试；新组明确配置真实测试路径，当前接力路径为 `tests/integration/test_hy_layer_data_sdk.py`。AA 当前 7 pass/0 skip 由根告知，不等于已取得最终 Z 候选的 X 放行证据：必须核对原始运行来源与最终候选相同，不能仅把旧 receipt 的 HEAD 改为新 HEAD。

JUnit 按 XML 实际 testcase 数组解析，拒绝任何失败、错误、跳过、空用例、重复 classname/name、DOCTYPE/ENTITY，以及 summary 的 tests 数与实际数组不一致。receipt 的整数 test_count、JUnit 原始字节摘要、配置完整 expected_cases 数组必须同时相符；每份声明的测试模块必须确实有 testcase。不是只检查 completed/零跳过布尔标记。

候选源码身份与原工具 `probe.source_identity` 算法一致：精确清洁 HEAD/tree，以及既有 src/longmemory 和 scripts/development/xiaozhi Python 文件规范化摘要；没有增加新的全仓扫描。原语指纹从候选的显式文件循环及 SDK_VERSION 静态取值计算，核对所有旧文件和新增后端 Python 模块均被绑定。真实 SDK 解释器只核对固定 V 路径和字节摘要；本工具准备阶段不执行或修改该环境。

Z 的审查 JSON 还绑定同一 source/fingerprint/sdk、背景语义写关闭审查对应的精确源码 diff 摘要/路径数组、两组 receipt/JUnit/cases 摘要与实际数量、前端源提交/tree/manifest/完整资源 tree，以及目录 schema 与 46/8/3 数组。资源 tree 沿用上一轮算法：逐路径累加 UTF-8 相对路径、NUL、文件 SHA-256 ASCII、LF 后再 SHA-256，不能替换为清单 JSON 摘要。完整字段与规范化 JSON、cases 排序规则均在接口文件中；这是审查元数据，不是新的证明签章。

## proof 精确状态门与保护集合

只允许 `local/config/hy-memory/management-verification.json` 这一目标进入旧/新状态。配置必须给出旧字节摘要、独立暂存的新 proof 路径和新字节摘要；新文件仍须是原有四字段形状，rpc 摘要匹配已验候选，两项 true 都不能手填替代真实证据。

stop 阶段仅核对旧 proof 并完整备份，不替换。apply 获单独批准、主线及远端追踪匹配候选、数据/旧 dist/保护文件校验通过后，才将经审的新字节排他暂存、复核、原子替换到精确目标，并保存旧 proof 和状态回执。未知当前字节、目标变化、旧备份缺失、候选 proof 漂移、暂存碰撞或重复 apply 均拒绝；原子替换失败保留旧目标与暂存证据，不自动循环重试。

停服指令前重新确认旧 proof；正式启动前按本阶段 old/new 状态重新核对 proof 与完整保护文件。其他 protected 文件仍逐文件核对，且新增了完整路径集合校验：不能因允许 proof 改变而忽略整个 config 目录，也不能漏掉意外新增的配置文件。恢复分支只接受已知的新 proof 转回已保全旧 proof，仍须 root 指定已恢复的代码提交和空闲端口；不覆盖未知 proof、不恢复旧库覆盖当前数据。apply 失败仍保留服务现场，Git 回退归 root。

原始校园历史 unknown 摘要固定为已批准的 `487e2320d66317f1c25965c951ebd6943bf7874fe6619dfb35b505d2d5b81529`，只能有 1 条 unknown、0 reserved，不能通过改配置把另一个 unknown 重新冻结放行；本次 completed 总数须在最终冻结时新鲜核对。count 类型也拒绝 bool 冒充整数，paid/free 策略、API/设备/延后/TTS 忙碌检查保留。

## pending 不可执行与最终冻结

真实运行过的新 prepare-only 输出为 `prepare-tool-v3.json`，status=`pending_inputs_no_production_actions`，仍有 30 个待交接字段。文件 SHA-256 为 `39ab5304ce98aaf48ddc8c2dd16bd927337fcf876ac4de66d24ab0502c1bcc7d`，内部元数据摘要为 `1711d09cbcb19c53bb164bc464806903b398d6c302ff9164013076dd13be7f98`。**此摘要不可用于申请正式阶段放行**。

pending prepare 不检查正式资源或账本，只写 X ignored 元数据。即便伪造 status=ready、pending_inputs=[]，深层 schema 仍会发现 null；stop/apply/recovery 都在阶段派发前拒绝。完整计划还要求 operator 为精确清洁提交（包含无正常 untracked 文件），helper/证据模块/共享库摘要未变，重新读取的候选、证据与计划一致。

最终候选到齐后只填入明确交接的提交、证据和资源，运行 prepare-only 形成完整新计划；不猜候选、不自动从当前 HEAD 自证、不对不匹配证据自动重签。root 审完整 helper/plan 后分别给 stop 与 apply 指令。正式逐层内容浏览是用户已要求的本机 UI 只读范围；当前工具准备尚未读取新层，后续收据仅保留状态/计数/摘要，不复制真实正文。

## 实际验证与限制

36 项工具测试全部通过，零失败、零错误、零跳过，语法检查通过。合成验证包含：完整两组绑定正例、原生逐层 receipt 兼容、错候选/错 SDK/错原语/错 JUnit/错前端、缺模块、pending/伪 ready 拒绝、三种生命周期派发阻断、精确 old→new→old、未知 proof/异常私有配置拒绝、原子替换故障保留现场，以及校园 unknown/reserved/忙碌门。

回执 `synthetic-tools-validation-receipt-v2.json` SHA-256 为 `69e291a53ee7700b89a947246472efad687b72b275ec8a2d1c30f5110f68ba5e`；原始日志 `synthetic-tools-final-v2.log` 留在同一 ignored 目录。源码/原语/JUnit/proof 文件在隔离合成目录真实读写，Git 元数据由 mock 提供，SDK 文件不可执行。**这些是部署工具合成测试，不是最终候选或真实 SDK 验收**。

测试后旧 helper/plan 摘要及准备快照中的 33 个受保护文件仍一致。没有停止、启动或替换生产资源，没有调用 SDK、模型、合成、Docker 操作、串口/固件，也没有读取新层个人内容；没有新 proof 签发。旧分支与所有历史 ignored 证据保留。

本文件链接和 Git 差异检查通过。文档 strict 检查返回 1：X 树中两份新报告尚未登记，产生两个 unlisted-document，且本文件为 unknown-selection；按本轮归属留主会话/Z 登记，未修改 manifest，不能声称该严格检查通过。
