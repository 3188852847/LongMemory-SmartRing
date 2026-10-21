# AI：embedding 公开资源启动预备候选审查

日期：2026-10-21。独立基线 `98db9f692f1ec11df57e0a832555e925aaa89546`，分支 `codex/ai-embedding-resource-readiness-review-20261021`。AB `f04d24f01c6f60dbace902d4f6f02e1a312b73e5` 接为 `7e719f32`。本候选与当前日用发布分开；未部署或推送，不沿用旧管理证明。

## 源码、版本和边界

运行时代码仅 [sdk_observation.py](../../../src/longmemory/methods/hy_memory/sdk_observation.py) 新增三行：两行注释和一次公开 `openai.resources.embeddings.AsyncEmbeddings` 类解析。保留 Hy-Memory 2.0.3 的固定 SDK 源码/引用校验；不实例化客户端或资源，不调用 embed/search/getter，不新增网络、业务缓存预写或数据库操作。类解析仍会加载 Python 模块及类型定义，内存中的模块加载成本不是零。

核对所有者既有隔离环境代码：OpenAI 2.54.0 的 AsyncOpenAI.embeddings 缓存属性确实从该公开模块导入同一类，资源模块顶层主要导入类型/定义类；Pydantic 2.14.1、httpx 0.28.1、Hy-Memory 2.0.3 与交付回执一致。未安装、升级或修改 SDK 文件。

`worker.create_sdk` 在固定 SDK 实例建立后同步执行 `prepare_local_backends`，`ProtocolService.initialize` 只有 factory 返回后才发送 ready；父进程等待该 RPC，标准装配还等待 method ready。因此成功导入的成本进入 worker 初始化，不留到首查询。准备失败沿原结构返回 prepared=false、import/segmenter=0，不新增启动失败或放宽业务成功判定。这是尽力预备，不是对整个启动器所有组件耗时的保证。

语义 search 分支先调用 `_embed_service.embed` 再提供 query_embedding；旧 embed_rpc_ms 包装的是 embed_with_meta，故该路径缺失此阶段不代表零耗时。候选不改入口、v1/v2 白名单、测点包围范围或查询语义。

## 独立证据与限制

[AB 报告](AB-embedding-resource-warmup-20261021.md)及[七份完整合成回执](AB-embedding-resource-warmup-evidence-20261021.json)均已重算。证据文件 SHA256 `f1fdacbba8a3249ebc1be3ff29d7dd9029b866a6a7929a0b28c51b9dd45fad9c`；源码原字节 SHA256 `fb1d2c7d8a3a7ddc58b85851a12a18211e28c041190cfaf04c92f224a97335e8` 与当前完全一致。六个无剖析新进程的首次中位数 590.963→129.162ms、准备中位数 1035.232→1495.521ms 与原值一致。剖析进程单列，嵌套累计时间不相加。

AI 另以最终源码、显式 V 树 SDK、原 clean_environment、全新 owned 合成目录和随机回环端口，各跑一个 baseline/prepared 新进程：首次 **583.168→134.505ms**，第二次 2.732→2.729ms；准备 **1023.808→1484.159ms**。这是单对独立确认，不冒充三对中位数、统计收益或日用结果。原始回执在本树 `data/test-tmp/ai-embedding-resource-probe-20261021-01/`，七份证据复核在 `ai-embedding-resource-artifact-review-01.json`。

每次准备阶段均确认 HTTP 请求0、客户端/向量缓存0、SDK 状态目录已有文件字节不变；初始 SDK 建库与准备阶段分开。随后两次固定合成 query 禁用结果缓存，返回同一512维向量，本地 embedding 请求2、其他/外部请求0。socket 边界只允许该随机回环端点，进程审计拒绝 .env/local-config 读取；无真实 BGE、LLM、GPU、个人库或日用服务。

独立相关检查 **102 passed、0 skipped，33.64 秒**，报告 `data/test-tmp/ai-embedding-resource-review-01.xml`，覆盖未知 SDK 不导入、只解析不构造、失败回退、观测与取消、新旧协商、两个真实 SDK 新进程及真实 Python 3.10 薄桥。明确提供实际 `LONGMEMORY_TEST_HY_PYTHON` 和 `LONGMEMORY_TEST_XIAOZHI_PYTHON`，没有把缺参数跳过当作资源不可用。

CI 只新增 baseline/prepared 两个精确资源例外；模拟 SDK 路径缺失后 **14 passed / 2 skipped / 7 subtests passed，0.25 秒**，audit_report=(14,2)，报告 `ai-embedding-resource-ci-01.xml`。未扩模块/前缀豁免，未重跑 AB 全部旧组或当前远程发布 CI。

这些证据说明公开资源懒导入可以移到 ready 前，不是消除启动总成本。指定匿名生产样本约683ms，未重现旧4.6秒；缺口不能用相减当精确残差，本候选不能据此声称旧慢查询根因或真实日用提速。

## 冻结与管理证明接力

当前管理原语 SHA256 由 `fc9d53ea2b90be3d9a80846b21eec9b389f2dbe4393b51d8956f3013fcd103e8` 变为 **`1003fe901fa49bd2750242637b18744694f5bebdabfc3d06e0cf7a5eb262fdac`**。provider 仍为 `f425a3824f3771a16e7bd8df2b022376257c0d8f6673cd70c23d552a8943f717`，无需为了此候选修改提供器升级来源。

本组合通过审查后冻结，按 ROOT 已授权的 `hy_management_receipt.py --managed-semantic`、已有 V 树 SDK/小智3.10/AB合成捕获，在新排他目录实跑必要219项，生成匹配新身份的实际 proof 与外围回执；冻结时尚未执行，实际失败与复核结果见下节。旧 d978… proof 不适配此新身份，不能复制或手改。ROOT 决定后续是否停机、备份及部署；AI 不操作共享配置、个人数据或设备。

## 首次管理验证失败与有界复核

AB 的补验记录 `154977402f67493adeb064fc426554a6e55aea44` 已接为 `d2d27fa6cfad8d69e2ff3195354b06fa2442255f`：保留原130通过/1项因缺voice参数跳过，另记录真实3.10.20匹配解释器单跑1通过，不合写为一次131项运行。

首次工具实测该清洁 HEAD，输出目录 `data/test-tmp/ai-embedding-resource-managed-proof-20261021-01/`。结果 **218 passed / 1 failed，451.66秒**，工具正常拒绝签发，receipt status=failed/error=management_pytest_failed，**没有生成 management-verification.json**。原失败目录、临时标记和回执均保留。

唯一失败为 `test_hy_daily_lifecycle.py::test_daily_requested_profile_injection_without_scope_fails_and_closes_owned_gateway`。它在原 `HyState.ready → _write → Path.replace` 将合成 `hy-state.tmp` 替换为 `hy-state.json` 时收到 PermissionError/WinError5，未到预期 `profile_injection_scope_unproven` 判断。assembly.py 与98db日用代码完全相同。失败两路径长度155/154、文件非只读；事后 Restart Manager 仅查询这两个合成文件，无当前持有者，不能倒推失败时的占用者或归因防病毒软件。

在新合成目录，用一个不允许 delete-share 的目标读句柄调用原 `_write`，实际复现同类 WinError5且保留tmp，证明这是该文件访问条件下的已有失败分支，**不是已证明本次发生了该种占用**。诊断回执为 `data/test-tmp/ai-embedding-resource-marker-failure-diagnostic-01.json`。此操作不接触失败原件或个人库，不改权限、不终止进程。

定位后，在另一全新 pytest 目录仅验证对应单例：**1 passed，5.84秒**，报告 `ai-embedding-resource-marker-case-isolated-01.xml`。它不替代完整219项，也不改写首次失败或声称文件竞争已修复。本轮不扩大为持久化写入修复、不新增自动重试或放宽断言；保留上述限制后，以新的清洁文档 HEAD/新排他目录完整复核一次。若再次失败则停止签发并交 ROOT 决定独立故障范围。

## 完整复核成功与实际证明

第二次固定完整验证的清洁实测 HEAD 为 **`8c7a791691098a64080f20b7f365e4c41da0ecc1`**，tree `e79bdf0d2ef8348ea8c1b90833761e01e18214f7`。业务源码与首次失败时一致，仅多记录诊断的文档提交；未修持久化逻辑、改变权限或重试策略。本次 **219 passed、0 skipped、0 failed/error，467.40秒**，工具退出0，按最终 `1003fe…` 原语身份新生成七字段协议2证明。这是单次完整运行，不是将首次218通过与单例1通过拼接签发。

排他输出为本 AI 树 **`data/test-tmp/ai-embedding-resource-managed-proof-20261021-02/`**。可交 ROOT 的候选文件为该目录 `management-verification.json`；外围结果为 `receipt.json`，不可混淆。没有复制旧 fc9d/d978 证明或写正式配置。

| 原字节证据 | SHA256 |
|---|---|
| 新 `management-verification.json` | `875d1eb5f7750ddc3ef4a23a812997433bdb8182e22db7c64b44b4c4a266dcdc` |
| 新 `receipt.json` | `e3ee764df65e3620040ecca4331b8d7cb57adc2e75112119fbbe5f2eaa496300` |
| 新 `junit.xml` | `e99960cce823e507fb38abf80d1acbc949d3a6290e3fe57eaffb0ec519912d2c` |
| 新 `pytest.log` | `0bc4a0cb0aae423f7d955881175634a5f6b69d3a8ff4ba706d4ceaa87a018ea8` |
| 全部 longmemory/xiaozhi Python 文件名＋规范化字节 | `5925f73b045379a4db9d2ac698da1c803aca9ae15a7c0e87f1909a0b787040e1` |
| 首次失败 `-01/receipt.json`（保留） | `90df4cf50b54cb02d1fca6a73c1737b57de94e1d449ac4fa2684126a7f4848bb` |

AI 独立重算源码、原语、证明精确七字段、两个解释器、JUnit219项无跳过/失败、日志与回执摘要，均匹配；复核回执为 `data/test-tmp/ai-embedding-resource-proof-independent-review.json`。也检查首次 receipt 仍failed且没有proof。工具内与独立检查都在干净树完成，本次收尾只改本文及清单，不将新文档 HEAD 写进实测回执，不再重签。

首次 WinError5 的实际持有者和触发原因仍未确认，复核成功不代表该既有原子替换问题已修复。ROOT 合入前应保留此边界并核对最终源码与上述实测身份一致；部署、真实首轮收益和设备体验仍未执行。当前日用98db及其已成功CI不因本离线候选改变。
