# V：Hy-Memory 预检、合成样本与低层预接入

日期：2026-10-19，Asia/Shanghai。工作树 `local/worktrees/v-hy-memory-20261019`，分支 `codex/v-hy-memory-20261019`，起点 `147cbc117d4f88f5775dd02076ab9970871238a8`。会话 ID `01a15363-8120-7400-a9db-8f9142104b12`。本轮为 A/B 与独立 C 的阶段交付，**完整接入/真实 SDK/真实模型实验未完成**；尚未收到主会话提供的 U 稳定提交 SHA。

## 实际交付

- [隔离接入指南](../../guides/Hy-Memory隔离接入与验证-20261019.md)：固定来源、许可证、独立环境/进程边界、所有者执行命令、数据出口/零预算、API 映射、冻结审计和接力清单。含 Hy 专属决策记录 HY-001；是否晋升正式 ADR 交 U/主会话。
- `config/examples/hy-memory/`：直接依赖声明、发布摘要、无密钥配置模板。模板不由运行时消费，没有自动端点或密钥回退；没有根依赖/锁变更。完整传递依赖锁等待所有者解析，不能称完全可复现环境已经落地。
- `src/longmemory/methods/hy_memory/`：仅显式注入 client 的低层 `HySdkBridge`、独立结构返回、来源 meta 规范化和离线 preflight。没有实现/注册 U 方法、管理 DTO、工厂或日用切换。无真实 client 构造入口，不导入可选 SDK 即可做模拟测试。
- `datasets/synthetic/hy_memory_dev_v1.json` 与 `hy_memory_holdout_v1.json`：开发集 12 条/3 会话/10 题，保留集独立 9 条/3 会话/7 题。保留集未用于适配调试、检索或问答；本地作者合成，不是外部盲测。历史映射只传事件字段，答案/评分标签不写入记忆。
- `src/longmemory/evaluation/comparison/hy_memory_preparation.py` 与 `experiments/configs/hy_memory_comparison_v1.json`：复用现有数据类型/评分计划，开发集准备检查、字节变更不明分类；生命周期覆盖重复事件、重复语义、失败、重启、冻结。没有新造通用评分平台或修改现有 comparison 装配。
- `tests/unit/methods/test_hy_memory_bridge.py` 与 `tests/unit/evaluation/test_hy_memory_preparation.py`：26 个新增离线用例；Fake 不实现 SDK 提取、存储或持久化。

## 官方预检与关键发现

只读核对 GitHub README、tags/commits/tree API、固定提交的 pyproject/client/config/history/reader，以及 PyPI 发布元数据；未拉仓库/包/模型。目标为有官方固定标签且源码版本一致的 `2.0.3`，提交 `2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed`。PyPI 2.0.3 wheel 摘要已记录，未下载核对包源码同一性。2.0.4 发布存在，但本次 tags 中未见同版本标签，不能直接以 main 代替固定发布源码。

SDK 许可 Apache-2.0；第三方和可选模型各自许可独立。Python >=3.9 不排除本机 3.12.13，**Windows 原生依赖与中文存储路径未验**。core 含 ChromaDB/Kuzu，关闭图并不去掉依赖；openai/pydantic 等完整传递版本未锁。拟由所有者独立环境解析完整 hash lock，禁止主环境混装、自动安装或换源；命令已写在指南，本机 uv 选项仅通过 help 核对，命令未执行。

实际 2.0.3 search 通道为 schema/normal/proactive；profile 为独立 API 且只按 user 过滤。业务来源用 meta 列表透传；metadata 是另一个 extra 通道。SDK 原生分数独立保留，不映射成旧 keyword/dense/fused；Hy L0–L7 不等同旧 L0–L3。失败可能已有部分写入，不能假报可靠归档；request_id 未证明幂等。最终方法持久账本待 U 契约后实现。

**检索并非默认只读**：`_spawn_search_dedup` 默认会将相似 L2/L4 标记 SHADOW，属于语义状态变化；可选访问计数/时间、history/cache/log 也须区分。模板列关闭开关但没有声称冻结成功。现有 comparison runner 要求磁盘摘要不变，目前不注册 Hy；建议关闭后封存源，每题独立副本，仍要查逻辑记录/遥测/排名状态，不豁免文件名。完整系统比较须明示协议差异，不能声称论文公平复现。

所有者意图是新库从零、旧库保留；当前没有操作旧库或日用切换。外部 LLM 会收到合成历史与提取上下文，Embedding 收到内容/查询，回答模型收到问题/记忆上下文；所有端点/模型/维度未配置，外部调用预算 0。pro 一次 add 可能多次调用模型/向量服务，预算必须在 transport/provider 层强制执行；模板没有预算执行器。

## 实际验证

已读取 V 树 AGENTS、本机公共 README/规则索引/通用/机器/Python 规则、project-doc-maintenance 技能与文档维护机制，按任务读取 method-boundary、research-platform、R 报告及记忆修复效果验证方案和 comparison 源码。没有访问共享私有配置、个人库正文、日用端口、设备或串口；没有修改全局/主环境、主动调度或根入口文档。

1. 借主 Python 3.12.13，只读使用已安装 pytest；每条终端命令显式 workdir 为 V。测试前 `sdk_bridge.__file__` 明确落在 V/src；pytest rootdir 同为 V，独立临时夹具沿现有规则管理。
2. `pytest tests/unit/methods/test_hy_memory_bridge.py tests/unit/evaluation/test_hy_memory_preparation.py tests/unit/evaluation/test_comparison.py`：**42 passed**（V 新增 26，既有 comparison 16）。测试参数/角色/历史时间/隔离范围/profile opt-in/meta来源、无结果、无效结构/输入、失败/异常不重试、关闭、版本门禁、评分标签隔离与保留门禁；不证明模型效果或 SDK 持久性。
3. 开发集准备命令成功：12 条历史/10 题，SHA-256 `eaa3015d89e26ba6d14cd1e6c3e39931ccf16ff2d72bb1368db4e26977d26440`，`sdk_run=false`、`answer_run=false`，待办明确列出 U/安装/端点预算/持久化/冻结/真实问答。
4. 正式 `check_docs --only <两份新文档> --strict --json` 返回 1：两个 `unlisted-document` 与两个 `unknown-selection`，正文检查数 0；不能报告正式 strict 通过。仅在内存临时登记 draft/reference 后调用同一检查器 `audit`，检查两份正文，warning/error 为 0，返回 0；只有实验计划链接为私有目录边界 note，未读取该目标。U 拥有文档清单，本会话未编辑它。`git diff --check` 通过，最终暂存后再核对。

没有真实 SDK/模型实验、性能/费用结论、日用实机验收或远程 CI；不报告质量统一分数。

## 交接与未完成工作

| 待接力 | 负责人/条件 |
|---|---|
| U 稳定 contracts/factory/runtime/管理契约 | 主会话交精确 SHA；V 才 cherry-pick，不自行从其他树复制或猜接口 |
| 最终 Hy 方法、持久重复事件/失败恢复、隔离进程装配 | V 在真实 U 契约上继续；当前低层不冒充完成 |
| SDK 安装/完整依赖锁 | 所有者执行指南命令，主会话核对传递依赖/许可；不触主环境 |
| Windows/中文路径、来源 meta、重启/部分失败/冻结 | 独立 SDK 和新合成目录，先做不收费存储检查，再按批准端点预算执行 |
| 外部模型/向量端点与可强制预算 | 主会话安排；不默认读密钥或调用现有服务，BGE 复用尚未验证 |
| 真实写入/召回/最终问答比较 | 相同历史/回答模型/提示/预算/评分，开发调试后才按计划验保留集；失败保留分母 |
| 清单登记和整合 | U/主会话；指南建议 pending/draft，本报告 reference；正式登记后重跑 strict |

清单 sources 建议：`src/longmemory/methods/hy_memory/**`、`src/longmemory/evaluation/comparison/hy_memory_preparation.py`、`config/examples/hy-memory/**`、两份数据集与测试；实验计划属私有目录边界提示，不添加到检查器允许读取目录。现行架构/方法文档由 U 更新；本报告只提供建议。

追溯：任务 V → 本报告所在本地交付提交（精确 SHA 随最终回复）→ 42 项离线测试通过、真实 SDK/模型与 U 接入 pending → 合入待主会话 → 会话 `01a15363-8120-7400-a9db-8f9142104b12`。仅提交 V 分支，不 merge、不 push、不向其他会话发消息。本阶段交付不满足整项完成/归档条件。
