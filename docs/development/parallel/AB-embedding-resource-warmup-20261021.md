# AB：首次embedding资源导入定位与启动预备候选

日期：2026-10-21。基线 `e4d62aae3197adc8a392c04abed661ff9448f690`，新分支 `codex/ab-hy-embedding-resource-warmup-20261021`，沿用AB隔离树。本轮ROOT授权只读一份指定匿名数值回执、固定SDK离线复现，若证实可安全预备则交最小隔离补丁；不部署、不推送。v2约定与原交付分别见 [ADR-0202](../../adr/0202-first-recall-observation-negotiation.md) 和 [实施记录](AB-first-recall-observation-implementation-20261021.md)。本候选仍待AI审查，未经真实日用收益验收。

## 收到的事实与可得结论

仅打开ROOT指定的 `owner-memory-stage-details-01.json`，未打开同目录其他文件、正文或个人库。三轮详情均received。首轮runtime_request683.139ms、api_prepare680.861ms、hy_recall672.142ms、sdk_search670.155ms；getter59.810ms、HTTP响应头52.735ms、VDB query18.889ms、get6.865ms、list15.177ms。网关/BGE已包含在HTTP跨度，不能再相加。上层search与已列阶段的量级差约半秒；聚合项可能嵌套或并行，不能相减当精确残差。后两轮runtime_request约31ms；该回执不复现此前4.6秒。

生产该轮没有函数级剖析，因此不能把其每毫秒残差都断言归给某函数。以下固定SDK因果对照证明：同一路径的公开资源首次导入，确实会产生并可移走约462ms，量级与缺口相符。原匿名轮次标识和原始私有回执未复制入Git。

## 为什么没有embed_rpc_ms

仓库 `worker.py` 的 `operation == search and semantic is not None` 分支，先在SDK搜索loop运行 `client._embed_service.embed(query)`，再把query_embedding传给SDK search。固定SDK的 `EmbedService.embed` 经 `_embed_texts` → `_embed_texts_with_meta` → `_embed_openai`；没有调用 `embed_with_meta`。

现有 `SDKObservation` 的embed_rpc_ms只包装 `EmbedService.embed_with_meta`。固定 `reader_base.py` 在ReadRequest已有query_embedding时也跳过该方法。故此控制流会有embedding_truncate、getter和HTTP详情，却没有embed_rpc_ms；缺失不是0，也不证明没做embedding。实际SDK搜索loop直接调用embed的探针重现相同测点组合。本补丁保留原入口、阶段白名单和时间语义，不为了填字段改包围范围或制造空值。

## 实际首次耗时来源

所有者已装环境为Hy-Memory2.0.3、OpenAI2.54.0、Pydantic2.14.1、httpx0.28.1。已有prepare_local_backends只提前解析AsyncOpenAI类及jieba，尚未加载 `openai.resources.embeddings`。查询中的 `client.embeddings.with_raw_response.create` 首次解析client.embeddings时，`openai/_client.py` 的缓存属性导入公开资源；Python首先执行整个 `openai/resources/__init__.py`，连带admin、beta等资源及大量Pydantic类型。

固定SDK、真实搜索loop、合成回环服务的cProfile（函数剖析）中：首轮总781.546ms，AsyncOpenAI.embeddings同步属性累计633.220ms，其中resources包导入632.399ms；Pydantic模型元类构造648次，累计201.835ms。后两项为嵌套项，**不能相加**。with_raw_response包装/实际create位于该属性解析之后；本次证据不支持把这六百余毫秒说成HTTP建连、BGE或响应体解析。

测量探针为 `tests/fixtures/hy_embedding_resource_probe.py`。它使用现有create_sdk及搜索loop；只调用embed，输入为固定合成文本、use_cache=False，替身返回相同512维数组；随机回环端口拒绝日用端口，socket边界禁止其他目标。未加载BGE、GPU、真实LLM，不触碰日用服务。子进程采用原clean_environment的独占HOME/TEMP和状态目录；SDK自己的dotenv扫描不遵守标准dotenv开关，因此该探针另以进程审计拒绝.env/local-config打开，避免读取真实配置。生产代码不增加此探针或审计钩子。

## 最小候选与收益证据

运行时代码仅在SDK指纹和引用核验通过后的既有prepare_local_backends中增加一行公开类解析及两行解释：`getattr(importlib.import_module('openai.resources.embeddings'), 'AsyncEmbeddings')`。不实例化AsyncOpenAI或资源，不调用_get_client、embed或搜索，不创建HTTP连接，不预写查询/向量缓存。既有import_ms继续记录导入准备，segmenter_ms仍记录原分词准备；API、v1/v2、每个查询测点和错误回退结构均未变。

[完整合成回执](AB-embedding-resource-warmup-evidence-20261021.json) 包含一个剖析进程和六个不带剖析的新进程；比较顺序baseline/prepared/prepared/baseline/baseline/prepared。baseline只在准备阶段绕过新增的公开资源导入，其他实际准备代码不变，查询前恢复真实importlib；这是测试进程控制，不是生产开关。早期未清理继承环境的试探回执保留在本AB忽略目录，最终交付数字来自clean_environment＋配置读取拒绝的重新测量。

| 不带剖析的新进程 | 首轮embedding(ms) | 第二轮embedding(ms) |
|---|---:|---:|
| baseline 1 | 596.118 | 2.960 |
| baseline 2 | 588.962 | 2.744 |
| baseline 3 | 590.963 | 2.795 |
| prepared 1 | 124.550 | 2.967 |
| prepared 2 | 130.498 | 2.783 |
| prepared 3 | 129.162 | 2.834 |

首轮中位数590.963 → 129.162ms，差461.801ms；对应本地准备中位数1035.232 → 1495.521ms，增加约460ms。这是把原首次同步导入移动到服务ready之前，**不是消除启动总成本**。这些为合成测量，不能保证生产同等收益、不能声称解决旧4.6秒。剩余首请求仍含客户端构造、真实回环及其他处理成本；本候选不继续扩大预备范围。

每个最终探针在预备阶段都核对：HTTP请求0、SDK状态目录文件字节摘要不变、客户端缓存0、向量缓存0。随后两次查询返回完全相同的固定向量，总计本地embedding请求2、其他请求0、外部HTTP尝试0。没有通过先发假请求或写库获得收益。初版测试曾把RequestBudget.attempts（含本地请求）误当外部计数，已按实际report口径更正；生产预算代码未改。

## 交付与验证

单元覆盖公开类只解析不构造、原计时/结果结构、导入失败原回退、未知SDK不导入。真实SDK集成覆盖baseline/prepared的预备文件摘要、空缓存、零请求及两次query行为和既有详情键；没有写脆弱的绝对耗时断言。

初轮相关回归 **130 passed / 1 skipped，38.34秒**，包含SDK观测/基础与v2契约、新旧协商、预备baseline/prepared、原回环网关、固定SDK执行器取消以及轮次持久化回归。当时跳过项为未显式提供小智voice解释器的跨Python薄桥，源码导入明确指向本AB树。

ROOT随后提供主仓既有小智3.10.20解释器：`local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/.venv/Scripts/python.exe`，实际SHA256核对为 `8ce49d96ecba2dfd13b3cc99b5d8a18f6c0ad82bacf0df2f5d17a3df6a9cd203`，与给定身份相同。按用例入口设置正式 `LONGMEMORY_TEST_XIAOZHI_PYTHON` 和既有 `LONGMEMORY_TEST_HY_PYTHON`，**只补跑** `tests/integration/test_hy_roundscreen_sdk.py::test_python310_real_provider_to_http312_and_real_hy_sdk`：**1 passed，4.36秒**。该项验证3.10真实provider→随机回环3.12 API→真实Hy SDK合成存储的归档、记忆与完成回执，外部HTTP尝试0；没有启动小智日用服务或模型。原130组未重复运行，原跳过现已补齐；不能把两条命令写成一次131项运行。

新增/变更仅本准备函数、其单元测试、独立探针、两模式集成测试、数值证据及本记录。SDK安装文件、provider、worker路由、API、v1/v2键、SDK入口与query时间语义均未改。共享documentation-manifest仍由ROOT维护，AB另交候选检查清单。

本隔离树管理RPC组合身份变为 `1003fe901fa49bd2750242637b18744694f5bebdabfc3d06e0cf7a5eb262fdac`；sdk_observation.py原始字节SHA256 `fb1d2c7d8a3a7ddc58b85851a12a18211e28c041190cfaf04c92f224a97335e8`。provider仍为 `f425a3824f3771a16e7bd8df2b022376257c0d8f6673cd70c23d552a8943f717`。未修改或重签生产proof；AI合入其最终源码后必须重算组合身份，不能直接套本树指纹。回退即撤销新增公开资源解析行，原首轮行为恢复。

精确候选运行时代码提交为 `f04d24f01c6f60dbace902d4f6f02e1a312b73e5`；补充交接只改本文，不改变源码或实验回执。基线e4的组合摘要独立从Git原字节重算为 `fc9d53ea2b90be3d9a80846b21eec9b389f2dbe4393b51d8956f3013fcd103e8`。assembly.management_primitives_identity包含sdk_observation.py，管理验证逐字比较rpc_source_sha256，所以**本候选必须新管理proof，旧proof不能复用**。证明结构、SDK版本、管理权限/业务行为及v1/v2协议均未改；不增加绕过开关、不自动签名或写生产证明。AI应以其整合后的完整源码重算、核对既有管理/语义验收条件，再由ROOT安排生效。本候选本身无需替换provider、修改其升级白名单或私有配置。

本分支不合main、不推送、不部署、不向其他会话发消息。最终仍需AI审查，由ROOT安排原范围内生效核对与真实首轮/后续轮比较；本次不申请或执行额外模型窗口。
