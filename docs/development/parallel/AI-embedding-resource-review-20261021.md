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

本组合通过审查后冻结，按 ROOT 已授权的 `hy_management_receipt.py --managed-semantic`、已有 V 树 SDK/小智3.10/AB合成捕获，在新排他目录实跑必要219项，生成匹配新身份的实际 proof 与外围回执；此提交时尚未执行，结果另在下节追加。旧 d978… proof 不适配此新身份，不能复制或手改。ROOT 决定后续是否停机、备份及部署；AI 不操作共享配置、个人数据或设备。
