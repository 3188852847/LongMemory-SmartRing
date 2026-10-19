# V：Hy-Memory 预检、合成样本与低层预接入

日期：2026-10-19，Asia/Shanghai。工作树 `local/worktrees/v-hy-memory-20261019`，分支 `codex/v-hy-memory-20261019`，起点 `147cbc117d4f88f5775dd02076ab9970871238a8`。会话 ID `01a15363-8120-7400-a9db-8f9142104b12`。本报告保留两阶段记录；下面至“第二阶段”前为首轮 `1e03d1d` 的历史状态，当时没有 U 提交/SDK。当前已接 U，真实 SDK/Chroma＋模拟模型已验；真实模型质量与日用切换仍未验。

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

## 第二阶段：U 接力、安装排障与真实 SDK 隔离验证

主会话按所有者要求交付五个精确 U SHA，并追加有限装配/文档清单编辑归属；已顺序 cherry-pick，无冲突：

| U 原提交 | V 接入提交 |
|---|---|
| `83b5b6dcceca281acea718d0f4be75b3bfe302f0` | `5855e4e9f0c6ba07b7c60402ba6fcfc5345dc6db` |
| `b52e0e32d8f2c1c930698da3e1569c3dd5acd836` | `6fefb2662afd5b0c58a3f269b737c1d1a0f43acf` |
| `77c73421de2f55c891c3988bff5236e99e222b42` | `e12d336c49412981ed53e213a68cca4756b998e4` |
| `4deee7ba9cf155ce23028ed9a739a5b97845e8f1` | `68a752dca0aa4bbe8fd7de63f5ccfd0825c0c4eb` |
| `e4087f7c9090298a9966f8ab539068f4cdebca23` | `972793a5ed23c9f15e5a72fc9dd83c07e04105af` |

接力不是 U 全量验收/main 合入。保留 [U 原报告](U-memory-boundary-20261019.md) 的 489 passed/2 skipped、首次全量 2132 passed/7 skipped/4 failed 和 React 未构建状态；本轮组合定向结果不倒推这些检查全绿。

### 安装失败与实际安装

所有者先成功创建专属 `.venv`，原命令因 langdetect 无 Python 3 wheel 失败；仅放行 langdetect 后再次因 jieba 无 wheel 失败。原预检漏查直接依赖 wheel，是本轮命令缺陷，保留两次失败事实。主会话随后核对官方 PyPI/源码无原生扩展，只放行固定 `langdetect==1.0.9` / `jieba==0.42.1` 纯 Python sdist 打包；其他依赖保留 wheel 限制。没有全面允许原生源码编译、换源、改根锁或安装工具链。

所有者完成官方源完整哈希锁和同步，pip check 报 102 包兼容。主会话只读核实 Python 3.12.13、Hy 2.0.3、langdetect 1.0.9、jieba 0.42.1、Chroma 1.5.9、Kuzu 0.11.3；锁 SHA-256 `706ce91ace29062d86a73db6a5845d9081e5e5b87660f52de8737d6c7f0345d7`。API preflight 成功但未构造 client。本会话收到安装完成后才使用该环境运行，没有与所有者争用或执行安装/重新解析锁。

`Install-Isolated.ps1`/requirements/指南已修正两项例外，可接续现存空环境，已有完整锁复用，失败即停。脚本为 UTF-8 BOM，实际 PowerShell 语法解析无错误；没有执行安装脚本。此前“先交锁再安装”是首轮预案，不是新审批硬规则。所有者已完成安装，无需重装。

### 实际实现与边界

- 新增 Hy 专属 settings/method/assembly/process_client/worker，`bootstrap.build_hy_memory_runtime()` 只是有限显式接线；U 中立契约/运行时/来源账本未扩张。主解释器不导入 SDK；专属解释器以 `-I` 启动，JSONL 只经管道。显式凭据不进 argv/报告，不默认读取已有配置或密钥。
- U 账本先保存角色/时间/session，再只向 Hy 投递用户消息；助手仅平台归档。SDK 成功不编造逐项写轨迹。完成事件重开后持久回放，冲突载荷拒绝；SDK 非原生幂等，failed/uncertain 不盲目重试。state/source 分离，身份/资源文件校验，未取来源独占锁不启动引擎；引擎目录另有生命周期锁，不能用另一来源账本绕过活跃引擎拥有者；重开不建缺失库。
- 管理忠实支持 active 无查询列表、详情、原生 kind、存在时 gmt_created 记录时间、可得来源；query/非 active 筛选明确拒绝。revision 只作稳定只读内容摘要，不能当原子比较保证；纠正/删除/旧派生能力拒绝。HTTP 同 U 会话/CSRF/权限护栏，旧 L1/画像/情景/主动端点返回不支持。
- worker graph/intention/coding/search-dedup/strength/访问回写/搜索历史关闭；清理继承的密钥与 MEMORY 等环境，独占 home/temp/logs。默认网络拒绝，模拟 transport 在本地返回固定向量/固定测试事实，外部请求数 0；SDK token 估算强制其字符回退，避免隐式 BPE 下载。此估算和模拟响应不冒充供应商 token/质量。
- SDK HTTP transport 有单 worker 生命周期内跨 LLM/Embedding 总次数硬上限、端点范围、重定向拒绝，SDK/OpenAI HTTP 不自动重试。跨题目副本/回答器的整轮共享预算、token/金额硬上限未实现，不能把单 worker 上限当整轮上限；真实网络/密钥尚未授权，CLI 仅无密钥离线配置。
- `hy_memory_runner` 使用独立命名 `hy-closed-source-per-question-clone-qa-v1`，复用现有数据/评分/提示参考/4000 字符预算。构建关闭和同路径重开后封存，每题复制引擎并新建空来源账本，封存源摘要必须不变；原历史账本保留在构建目录。副本字节变化显式列出，语义不变仍未知，不放宽旧 strict frozen runner、不跨方法统一分数。错误与构建失败保留全部分母。

### 真实 SDK 实测与修复证据

1. Windows asyncio 的 socketpair 内部自连接被首版全 socket 禁网误拦，真实初始化失败为 OSError。已仅允许标准库 socketpair 上下文内的内部回环自连接；外部 Python socket/SDK HTTP 仍拒绝，没有允许日用端口。
2. 真实 SDK 构造、空管理列表、关闭/独立进程重开通过。pro graph-off 初始化 Chroma/cache；没有初始化 Kuzu 图库，不宣称图功能验收。
3. 首次模拟模型写入失败定位到 2.0.3 LLM `max_retries` 实际为总尝试次数，配置 0 会零尝试失败；改为 1，Embedding/OpenAI HTTP 仍为 0。没有修改安装包。
4. 真实 SDK＋模拟模型成功写一条合成事实，列表/详情/召回均返回原 `source_event_ids`；观察到 4 个本地模拟请求、0 外部 HTTP。关闭/重开保留一条；完成事件重放不增加写入，助手仅平台归档。
5. 禁用模型时真实 SDK 写失败，平台来源保留 failed；回执失败注入发生在真实 SDK 写入后，重开为 uncertain 且拒绝重试，实际引擎条目仍一条。没有跨存储 exactly-once 或失败必无副作用承诺。
6. 真实 SDK 最小逐题副本 smoke 已运行到报告/评分，Fake 回答仅验证工程链路。封存源摘要不变；副本实际观察到 `sdk/vector/chroma.sqlite3` 与 SDK 默认日志变化，未证明语义状态不变，不能作为冻结或模型质量验收。
7. 首次组合回归为 120 passed/1 failed，失败为深测试目录 copytree 的 WinError 206；独立复制复现目标路径估计 289 字符。实验内部 run/方法/题目目录改短并保留报告映射，不改系统策略或迁移 ASCII 路径。随后复制/runner 三项定向回归通过。

最终组合检查为 `tests/unit/methods tests/unit/entrypoints tests/unit/application tests/unit/architecture` 加 Hy 准备/runner、既有 comparison 及真实 SDK 离线集成：**549 passed / 2 skipped**（74.18 秒）。两跳过为本机符号链接权限、未显式绑定 Otto 固定资源；不是 Hy 测试跳过。四项真实 SDK 测试实际执行通过。新增 HTTP 合成用例使用系统分配临时端口，验证 Hy 经同一鉴权/来源管理、助手归档、旧端点/写能力拒绝，不访问日用端口。

随后补齐“另一来源账本不能绕过同一活跃引擎拥有者”的目录锁和实际诊断元数据，Hy 后端/runner/真实 SDK 18 项定向通过；最后完整 Hy 专属范围 **44 passed**（26.65 秒），覆盖最终运行代码。准备命令状态字段同步后另有 3 项通过；只做文档/注释更新未重复扩大业务测试。最终差异和敏感内容检查无发现，正式两文档 strict 再次通过。

新代码导入与 pytest rootdir 均核对为 V，借主解释器只读运行 pytest，SDK 实际运行在专属子进程。独立随机回环 HTTP 测试未连日用端口。没有访问个人库/共享私有配置/真实对话/设备，未开调度。独立原始证据在本树忽略的合成临时/实验目录，未提交原始产物。

### 后续主动交流重点与接口缺口

所有者新增方向：“后续，应该会侧重于主动交流能力的开发”。只记录后续重点，本轮没有扩为主动交流实现、开启调度或切换日用。现有许可、频率/时段/勿扰、在线/空闲、一次性跟进和结果账本保留；Hy Intention/到期字段不等于主动联系完成。

过渡路径为 Hy 提供相关记忆/事项证据 → 独立主动交流层判断是否/何时/说什么并执行许可/打扰控制 → 设备桥执行 → 回应/取消等结果可追溯反馈。精确缺口：

- `recall()` 当前仅上下文/可选来源，未提供中立的“待处理事项＋时间窗口＋状态＋证据版本”读取契约；未来按具体需求定义，不能把 Hy L7 塞成平台约定。
- 新后端旧圆屏完成关联、反馈和结果入账尚未适配；来源事件/本次回答/主动事项/设备播放回执之间缺少中立关联，不能复用旧 L1 ID 假装已接。
- 取消、回应、过期与已发送状态如何关联原事项/来源、保持许可检查和避免重复发送尚未定义；Hy 修订原子写能力不足，不能让调度层依赖其私有写行为。
- U 新引擎仍拒绝旧陪伴/跟进命令，server 非 legacy 不装主动调度。本轮继续保持此限制；后续独立定范围/验收，不重写旧主动代码或预建大框架。

### 当前接力状态

U 接力、SDK 安装、Hy 方法/只读管理/独立进程和比较副本入口已实现并作离线验证。剩余为真实 LLM/Embedding/回答模型、维度/出口/硬预算条件下的开发与保留比较，以及日用/设备/主动交流另行范围；未做效果结论。清单已按新增归属正式登记本指南/报告/源码主题。正式 `check_docs --only <指南> --only <V报告> --strict --json` 返回 0：检查正文 2 份，warning/error 0；仅实验计划链接为私有目录边界 note。没有依赖首轮内存登记，也不把链接检查当全篇语义或全仓验收。

追溯：V 首轮 `1e03d1df9e164966dc9c86207c1d8b7e363a30f4` → 五个 U 接力提交 → 本报告所在第二阶段本地提交（精确 SHA 随最终回复）→ 实际定向/真实 SDK＋模拟模型验收见上 → main 合入/推送待主会话 → 会话 `01a15363-8120-7400-a9db-8f9142104b12`。本会话不 merge、不 push、不向其他会话发工具消息，未归档。
