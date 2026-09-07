# LongMemory-SmartRing

一个面向个人智能终端的长程记忆研究项目。

本项目以独立、可测试的 LongMemory Core 为研究主体，通过适配层接入 Xiaozhi Server 和 SmartRing-Plus 智能圆屏；当前圆屏合成记忆闭环已由用户完成实机最小验收。

> SmartRing-Plus 是基于 ESP32-S3 的智能圆形显示屏开发板，不是可穿戴戒指。

**日常启动：双击根目录 `Start.cmd`**，在小面板选择文字或文字＋圆屏，确认后启动并打开控制台。见[统一启动指南](docs/guides/统一启动.md)。原[终端使用说明](docs/guides/使用说明.md)保留用于实验与排障。

学校模型与官方 DeepSeek 测试使用两个独立且不提交的环境文件：日常启动读取 `.env`，助手代执行的官方 API 验证显式读取 `.env.deepseek.local`。填写位置、命令和调用边界见[模型配置分流指南](docs/guides/模型配置分流.md)。

**产品自定义候选：[自定义功能清单](docs/requirements/自定义功能清单.md)**。区分已有能力、候选新增与需验证能力，不代表全部承诺开发。

## 当前状态

VoxCPM2 本机 TTS 适配层已实现：固定权重在独立 CUDA 环境常驻，经环回 HTTP 接收小智 `CustomTTS` 文本并返回 WAV；真实本机请求得到 48 kHz、单声道、16 位有效音频。当前真实小智配置已由用户显式同步为 VoxCPM2，统一启动链已通过；React 声音窗口可查看后端、配置契约和本机模型就绪状态。圆屏实际声线与延迟仍由用户试听验收。见 [VoxCPM2 指南](docs/guides/VoxCPM2独立试听.md)与 [ADR-0025](docs/adr/0025-local-voxcpm2-tts-adapter.md)。

P2 新增声音设置：四种 Edge TTS 音色、固定文本联网试听和确认保存。入口 `/chat-react`，保存后需重启小智；实机听感待验收。见[声音设置](docs/guides/声音设置.md)。

P2 助手角色设置已接入 `/chat-react`：网页编辑、版本化保存；圆屏可检查并明确确认同步到小智配置，之后需重启小智，实机生效待验收。见[助手角色设置](docs/guides/助手角色设置.md)。

Web 控制台已渐进统一到 React + TypeScript + Vite + antd：聊天 `/chat-react`、L0/L1 记忆 `/memories`、L2 生活场景 `/scenarios`、设备 `/device`、个性化 `/settings` 与实验 `/experiments-react` 共用 React Router、AppShell 和外观状态；TanStack Query 管理服务器状态及不自动重试的写操作。实验页保留预检/确认分离、任务进度与逐题复核；原生入口暂留回退。组件测试使用 Vitest/React Testing Library。见[体验指南](docs/guides/React聊天页.md)、[技术策略](docs/architecture/technology-strategy.md)、[迁移清单](docs/architecture/react-chat-migration.md)与 [ADR-0032](docs/adr/0032-progressive-react-console-migration.md)。

Python HTTP 入口继续使用 aiohttp；Pydantic 2.13.5 已在聊天消息 POST 完成首个严格契约试点，保持原有 400 错误、响应和幂等行为，不进入 Memory Core，也不代表已决定迁移 FastAPI。见 [ADR-0033](docs/adr/0033-staged-technology-adoption.md)。

首批 Playwright 浏览器验收已接入：用临时 Fake 控制台验证聊天刷新恢复、React 页面导航、无第三方请求和只读实验禁止启动，不读取个人库或调用模型/圆屏。运行命令与失败 trace 位置见[React 控制台指南](docs/guides/React聊天页.md)。

P2：聊天页支持浅色/深色/跟随系统及字号保存，配置默认折叠。见[外观设置](docs/guides/外观设置.md)。角色编辑、显式圆屏配置同步及音色试听已实现；不改日常记忆算法。

P1 网页会话恢复已实现：列表、新建、切换、重命名，同一浏览器可刷新/重启续聊。采用独立旁库，不迁移原记忆库；旧未分组聊天不自动导入。操作与边界见[聊天会话指南](docs/guides/聊天会话.md)。

启动面板“网络与防火墙”可检查监听及项目规则；添加/撤销需明确确认与 Windows 管理员授权。圆屏已能聊天无需添加，普通启动不修改系统规则。

启动器已补充局域网地址发现、旧 IP 提示及显式“小智地址同步”（仅三个网络字段，私有目录备份）。不自动修改防火墙或圆屏 OTA；地址变化操作见统一启动指南。

已修复 Windows 下 uv 的 `.env` 路径导致控制台退出码 2：在明确的项目工作目录中使用相对 `.env`；更新后请重开启动面板。

2026-09-04 用户决定：先做愿意日常使用的可定制陪伴助手，再研究论文。已有文字/语音最小闭环、记忆管理、音量控制与实验中心保留；研究优先顺序已被产品主线取代。当前日常默认仍是规则提取＋关键词召回；P3.2 已增加显式可选的模型辅助提取和关键词＋本地 BGE 混合召回。

当前产品顺序：**P1 日常入口 → P2 个性化体验 → P3 日常记忆 → P4 可控主动交流 → P5 习惯驱动陪伴**。P1–P4 已形成可运行基础闭环：主动许可、勿扰与频率门控、定时问候、结果审计，以及绑定已接受 L2 的所有者批准话题素材均已实现。2026-09-07 的一次性开发授权实机验收证明，后台能在设定时刻向 SmartRing-Plus 圆屏终端播报带可追溯素材版本的记忆话题。当前主线转入 P5 的结果事件与习惯驱动陪伴，尚未实现自动习惯推断。

P3 目标已明确为四层个人记忆：L0 原始证据、L1 原子记忆、L2 场景、L3 用户画像。P3.1–P3.4 已完成共享 Runtime、模型辅助 L1 提取、混合召回、显式纠正/变化和运行期开关。L2 代码已推进到 V6：`/scenarios` 支持候选/复核、模型辅助预览、现实有效期、可审计手动结束，以及默认关闭的受控回答召回。L3 管理闭环已推进到 V8：`/personas` 支持人工候选、显式且不落库的模型草稿、分级证据门槛、L0 追溯、接受/拒绝与来源失效事件；个人库已备份迁移且 L3 为空，自动画像整理和回答注入尚未实现。自动识别变化、自动场景/画像整理、L2/L3 语义召回、撤销和跨层重建仍未实现。见 [ADR-0026](docs/adr/0026-layered-memory-and-knowledge-plane.md)至 [ADR-0043](docs/adr/0043-explicit-l3-model-preview.md)。

L2 设计已接受：先生成可追溯、需复核的时间化场景候选，确认前不进入回答；稳定习惯仍属于 L3。个人库已在一致性备份和用户明确授权后迁移到 V6，原有 L0/L1/L2 数量不变，生命周期事件从空表开始。可按 [L2 生活场景合成测试指南](docs/guides/L2生活场景测试.md)体验，设计与边界见 [ADR-0035](docs/adr/0035-reviewable-l2-scenario-candidates.md)、[ADR-0038](docs/adr/0038-audited-l2-lifecycle.md)和 [L2 第一版验收](docs/requirements/l2-scenario-memory.md)。

L3 采用“一条记录一个画像断言”，并区分用户明确声明和系统跨记录推断。系统推断的第一版保守下限为两个来源、三条用户原话和两个 UTC 观察日。当前由用户选择 L1/L2 来源，可手工填写或明确确认一次模型草稿，再复核候选；这不等于系统已经会自动总结习惯，也不会影响回答。见 [L3 验收需求](docs/requirements/l3-user-persona.md)和 [测试指南](docs/guides/L3用户画像测试.md)。

- [路线图](ROADMAP.md)：先后顺序与历史记录。
- [产品范围与验收](docs/requirements/companion-product.md)：各阶段做什么、怎样算完成。
- [系统架构](docs/architecture/overview.md)：模块、进程与数据归属。
- [技术策略与技术雷达](docs/architecture/technology-strategy.md)：当前技术栈、近期采用项、触发式候选与暂不采用项。
- [运行流程](docs/architecture/workflows.md)：当前步骤、失败行为和未来流程。
- [路线变更决策 ADR-0015](docs/adr/0015-product-first-companion-roadmap.md)：变更原因与边界。
- [分层记忆与知识边界 ADR-0026](docs/adr/0026-layered-memory-and-knowledge-plane.md)：P3 目标、来源隔离与框架边界。
- [共享常驻 Runtime ADR-0027](docs/adr/0027-shared-persistent-memory-runtime.md)：网页/圆屏统一实例、回环令牌与失败边界。
- [日常模型提取 ADR-0028](docs/adr/0028-daily-llm-l1-extraction.md)：L0 优先、显式失败与规则基线并存。
- [日常混合召回 ADR-0029](docs/adr/0029-optional-daily-hybrid-retrieval.md)：排名融合、本地索引与显式关键词降级。
- [运行期记忆模式 ADR-0031](docs/adr/0031-runtime-memory-mode-controls.md)：写入与使用解耦、双入口共享及 L0 边界。

## 2026-09-03 研究平台阶段记录（历史）

以下保留当时进展；其中“最新路线/下一步”按当日语境阅读。当前执行以文首与 ROADMAP 为准，测试数量是历史记录，不是本次重新执行的结果。

控制台新增[实验中心](docs/deployment/experiment-console.md)：实验列表、逐题回答/注入/来源对照、独立人工复核；现在可显式启用“冻结检索回答对照”的网页预检、预算确认、运行进度、停止后续请求和打开新结果。查看/预检不联网，真实模型只在确认后调用；原报告只读、新结果另存，不修改个人库。见 [ADR-0013](docs/adr/0013-local-experiment-viewer.md) 与 [ADR-0014](docs/adr/0014-local-experiment-jobs.md)。

项目处于 **产品优先路线的 P3 日常记忆后半段**：P3.1–P3.8 已完成；P3.9 的 L1→L2、跨时间 L2→L3 均已有持久账本、稳定选源、候选生成、独立风险复核和策略门控，并已建立 V13 复核审计与 Runtime 单一后台周期；官方模型隔离合成验收已通过，该能力在个人库仍默认关闭。论文方法比较平台保留，但暂不作为开发主线。

最新路线：A 方法边界 → B 网页文字聊天 → C 最小跨方法冻结问答 → D1 LongMemory 算法升级 / D2 论文复现交替迭代。
**A 已完成**：`longmemory_v1` 包装复用旧规则；新方法接口将接收消息与召回分开，原 CLI/小智行为保留。239 项 Python、9 项 Node 合成回归通过。
**B 已实现**：新增[文字聊天页](docs/deployment/local-console.md#文字聊天网页入口)，共用 longmemory_v1 和已有记忆库，网页临时会话独立；展示真实写入、召回、注入和失败阶段。用户已开始实际使用，姓名问题暴露关键词召回局限，不代表两端数据库不共享。
**C 最小版已实现**：[历史回放与冻结问答](docs/research/method-comparison.md)，原子事实与原始对话分块两种方法、独立实验状态、相同上下文预算和逐题报告。默认 8 个合成开发题，4 个保留题本轮不运行。完整日常会话持久化、语义检索升级和 MemRL **未实现**。
网页新聊天不删除长期记忆；同一浏览器支持刷新和服务重启后的会话恢复。网页角色保存版本独立生效，小智仍用自己的配置，尚未自动同步。新角色的校园模型表现待用户体验。
本轮没有新依赖、schema 或个人库迁移，没有调用校园模型或替用户操作设备。开发预览只使用隔离合成库。
最新全量回归：391 项 Python、17 项 Node 测试通过。用户已完成首次学校模型比较，两方法各完成 8/8；原词面初筛均 5/8，存在措辞误判，见[独立复核记录](docs/research/comparison-dev-review-2026-09-03.md)。原报告与分数保持不变，未运行保留题。
**D1 提取条件完成首次真实最小验证**：用户已运行三组各 8/8，新增提取请求 7 次；新方法保留了旧规则漏掉的非第一人称研究方向，但姓名仍因关键词检索失败，且模型改写产生语义重复。原初筛 4/8、7/8、6/8 含措辞误判，不代表真实排名，见[本次复核](docs/research/d1-extraction-review-2026-09-03.md)。`longmemory_llm_extract_v2` 仅用于隔离实验，现用 v1/网页/圆屏不变；完整提取质量和语义检索升级未完成，见 [ADR-0010](docs/adr/0010-source-bound-extraction-candidates.md)。
**D1 检索消融完成首次真实最小验证**：本地 BGE 固定快照已校验，CPU 离线完成两份冻结事实库 × 两种检索器 × 8 题，共 32 次检索；充分来源覆盖分别为规则库关键词 4/6、向量 5/6，模型提取库关键词 5/6、向量 6/6。两库姓名均从未召回变为排名第一，但小语料 top-5 接近全量，不能据此声称问答质量提高；未知题噪声和语义重复仍存在。见[逐题复核](docs/research/semantic-retrieval-review-2026-09-03.md)、[实验指南](docs/research/semantic-retrieval.md)与 [ADR-0011](docs/adr/0011-frozen-corpus-semantic-retrieval.md)。本次不重新提取或生成回答；旧基线、网页、圆屏与个人库不变。
详见 [ADR-0008](docs/adr/0008-replaceable-memory-methods-and-research-protocols.md)、[验收范围](docs/requirements/research-platform.md)、[方法接口与限制](docs/architecture/method-boundary.md)。

**冻结检索后的首次真实回答对照已完成**：用户在校园网完成四组各 8/8，不重提取或编码。原词面初筛为 5/8、6/8、7/8、8/8；助手逐题复核为 6/8、7/8、7/8、8/8，两组毛色拒答被初筛漏判。姓名召回改善转化为本题回答改善，但 5/7 条小语料、未知题仅两道，不证明长历史或论文级表现。见[本轮复核](docs/research/retrieval-answer-review-2026-09-03.md)与 [ADR-0012](docs/adr/0012-frozen-retrieval-answer-replay.md)。下一步扩展带干扰事实的独立开发集；日常网页/圆屏仍不替换算法。

已经完成：

- [x] 明确 LongMemory Core、Xiaozhi 与圆屏终端的系统边界
- [x] 确定 Python 3.12、uv、SQLite、pytest 和模块化单体路线
- [x] 确定 V0.1 只实现 L0 原始对话与 L1 原子记忆
- [x] 建立工程骨架、协作规则、需求、ADR 和研究计划
- [x] 完成 SmartRing-Plus-B 基础硬件识别验证
- [x] 实现 L0 原始消息与 L1 原子记忆领域模型及来源追踪
- [x] 实现 SQLite 建表、L0/L1 持久化和跨应用实例重开验证
- [x] 实现确定性的第一人称陈述提取 Baseline
- [x] 实现基础关键词检索、受控上下文构建和 Fake 回答生成器
- [x] 实现聊天应用服务和 `build_application()` 装配入口
- [x] 建立单元、SQLite 集成和写入—重开—回忆端到端测试
- [x] 实现 L1 记忆列表、单条来源查看、删除及删除持久化验证
- [x] 实现可交互 PC 端 CLI 及聊天、查看、删除和退出命令
- [x] 补齐 src layout 打包配置、命令入口和安装状态回归测试
- [x] 实现精确重复记忆复用，并保留每次陈述的多条来源证据
- [x] 增加显式 ADD/NOOP 写入结果，固定未来 SUPERSEDE 接口语义
- [x] 分离记忆声明与来源证据，移除领域模型中的唯一来源字段
- [x] 增加单用户主体、事实有效时间和取代关系的数据结构
- [x] 增加 SQLite V1/V2/V3 → V4 非破坏性迁移、来源回填与人工纠正来源测试
- [x] 将助手回答作为带角色的 L0 原始消息持久化
- [x] 实现可配置的非流式兼容模型适配器、超时/错误处理和模拟 HTTP 测试
- [x] 实现元数据 JSONL 审计日志，跟踪写入、检索、上下文使用与回答失败
- [x] 建立固定合成样例与回答上下文消融评估，报告保留代码/数据/提示哈希
- [x] 验证两个独立 CLI 进程之间的 SQLite 记忆持久化
- [x] 用户在校园网完成真实接口调用、v1 合成问答与手动重启召回，助手已复核本地报告
- [x] 修复常见无问号提问误入库与拒答措辞漏判；新增 v2 合成回归数据和评分器版本
- [x] 用户完成 v2 校园网合成复验：有记忆上下文 8/8、无上下文 5/8，通过数仅指该合成集工程检查
- [x] 用户反馈厂商 B 版小智固件可配网和语音对话；尚未接入本项目记忆服务
- [x] 编译并实机运行 AXP2101 只读诊断：诊断期间电脑 USB 供电下报告恒压充电、4192–4193 mV、估算 100%；不等于小智运行时的同步读数
- [x] 核对厂家 B V2 下载固件：与厂家 Git blob 一致，内部校验通过；用户烧录后报告校验通过，待机照片及用户反馈确认低电量提示消失；电量精度和充放电切换尚未验证
- [x] 完整备份此前已配网的旧版小智，诊断后曾恢复且写入校验通过；该备份和原厂备份均保留，不是当前 B V2 的备份
- [x] 用户准备独立 Xiaozhi Python 环境，反馈依赖检查、FFmpeg 与 Opus 静音编解码验证通过；完整语音服务尚未启动
- [x] 用户反馈 SenseVoiceSmall 中文识别、SileroVAD 加载和 EdgeTTS 合成播放检查通过；提供无密钥配置模板、本机启动工具与流式验证命令
- [x] 用户在校园网完成学校模型流式检查（3 个非空内容块、5 字符）和本机服务启动；HTTP/WS 检查通过，助手只读确认 8000/8003 均监听 127.0.0.1；尚未接通圆屏或长期记忆
- [x] 准备显式指定 IP 的局域网启动模式与可撤销的窄范围防火墙脚本；修复 Windows PowerShell 5.1 中文编码解析问题
- [x] 用户提供圆屏接入自建小智后的 ASR、回复音频生成发送和再次监听日志；此阶段 Memory=nomem，不算长期记忆验收
- [x] 抽出共享 MemoryTurnService，实现小智本机子进程记忆适配、独立连接实例和安装/启动入口；138 项离线回归通过，含真实 Python 3.10 → 3.12 与 SQLite 重开召回，未替用户启用
- [x] 用户随后启用 LongMemory，提供猫名召回及未知毛色不编造的实机日志，并明确确认服务重启召回和来源查看完成；V0.1-Demo 小规模合成最小验收通过，不代表长期运行或通用能力验证
- [x] 静态审查用户提供的 elysia.skill ZIP，准备独立的爱莉希雅风格与普通助手候选文本，保留上游 MIT 声明；141 项离线测试通过，尚未修改运行中的人格或音色

尚未完成：

- [ ] 记忆撤销/恢复和隐私级彻底删除
- [ ] 语义重复处理
- [ ] 查清圆屏 0% / 未充电提示与实际电池充电状态是否一致
- [ ] 更大范围的真实模型对照与人工复核；当前小样例不代表通用能力
- [ ] 助手角色的系统性事实边界评估；用户已完成初步听感体验，语义检索等后续研究尚未开始
- [x] 用户已体验并暂时接受助手角色表达；未更换 TTS 音色，不扩大为全面人格/事实边界评估
- [x] 新增可选的本机音量控制技术验证入口，默认关闭，独立客户端令牌鉴权；不改固件或记忆核心
- [x] 用户确认唤醒后 B V2 音量通道操作可用；待机可能无活动连接
- [x] 实现本机控制台“设备与状态”页：查看连接、读音量、设置与回执核对，浏览器不持有设备令牌
- [x] 用户确认网页音量控制可用；设备页实机操作通过
- [x] 实现记忆管理页：已有库只读浏览、分页/文字筛选、来源查看，以及显式启用后的单条删除确认
- [ ] 记忆页真实浏览器体验；助手角色和运行记录页面仍待实现

当前默认闭环采用确定性规则、关键词检索和 Fake 回答生成器；真实回答器可显式启用，校园网首轮调用已由用户验证。问句过滤仍是有限中文规则，不保证覆盖所有表达；时间抽取与自动冲突更新尚未实现。已有数据库中的误提取记忆不会自动清理。

### 已完成演示与控制台历史进展（后续执行以文首及 ROADMAP 为准）

用户已决定提前圆屏演示：先验证私有部署模型接口并接入 PC 回答链路，补齐必要日志、最小评估和进程重启验收，随后立即进行 **V0.1-Demo：Xiaozhi + SmartRing-Plus-B 圆屏记忆演示**，不等待后续记忆算法研究完成。

配置的模型标识为 `DeepSeek-V4-Flash`，服务实际模型身份未独立核实。用户已完成校园网接口、自建小智链路及圆屏跨会话合成记忆最小验收；当前 HTTP 仍不加密。详细边界见 [路线图](ROADMAP.md)、[ADR-0005](docs/adr/0005-early-device-demo-and-private-model.md) 与 [ADR-0006](docs/adr/0006-xiaozhi-local-process-memory-bridge.md)。

当前厂家 B V2 低电量提示已消失，圆屏记忆演示已跑通。[七步启用指南](docs/deployment/xiaozhi-longmemory-demo.md) 保留用于复现。适配器逐轮保存用户 ASR 正文，暂不归档小智助手回答；PC 仍保存双方 L0。用户已体验并暂时接受 [助手角色文本](docs/third_party/elysia-skill-review.md)，不改记忆核心、不新增剧情 RAG、不切换音色。电量精度及充放电切换仍未验证。

本机控制台：设备与状态页已由用户确认可控制圆屏；React 设备页位于 `/device`，原生 `/` 保留回退。记忆管理页已实现分页/文字筛选、来源查看、错误纠正、事实变化、运行期开关和受限单条删除。圆屏自然记忆操作第一版也已接入：明确纠错、事实变化、来源询问和双轮确认删除均复用同一常驻 Runtime，歧义不猜测。用 `--database` 指定已有库，不自动建库；L1 删除仍保留 L0 原文。浏览器界面不等于设备常在线，进入聆听状态后才可能可控。启动与使用见[使用说明](docs/guides/使用说明.md)，最新自动验证数量见 CHANGELOG；本次没有替用户改写或删除真实数据。

## V0.1 目标

V0.1 需要证明：

> 用户输入一条值得记忆的信息后，系统保存其原始来源和规范化记忆；程序完全退出并重新启动后，仍能根据新问题找到该记忆并用于回答。

最小闭环：

```text
输入
  → 保存 L0 原始对话
  → 提取并保存 L1 原子记忆
  → 完全退出并重新启动
  → 检索相关 L1
  → 构建受控上下文
  → 生成回答
  → 验证来源与结果
```

### In Scope

- PC 端 CLI 文本交互
- 单用户本地实验
- L0、L1、SQLite 和来源追踪
- 基础提取、检索、上下文注入和回答
- 查看、删除和多来源证据追踪
- 固定测试集、必要日志和无记忆 Baseline

### Out of Scope

- SmartRing-Plus 实机接入和 Xiaozhi 正式集成
- ASR、TTS、Web UI 和公网部署
- 独立向量数据库、知识图谱和多模态记忆
- L2/L3、复杂冲突消解、遗忘、衰减和主动提醒
- 多用户和生产级权限系统

## 架构边界

```text
entrypoints
    ↓
application
    ↓
core ← contracts → adapters
    ↑
infrastructure
```

- `core`：领域模型、契约和记忆规则，不依赖 CLI、SQLite 或模型 SDK。
- `application`：组织一轮聊天和记忆管理用例。
- `adapters`：SQLite 与 LLM 的可替换实现。
- `infrastructure`：配置、连接、建表、日志和依赖装配。
- `entrypoints`：CLI，以及后续 API 和 Xiaozhi 入口。

领域异常统一放在 `core/common/exceptions.py`，不创建重复的 `infrastructure/errors/`。

## 当前仓库结构

下面是当前采用的唯一骨架。目录存在不代表功能已经实现。

```text
LongMemory-SmartRing/                              # 项目根目录
├─ .github/                                        # GitHub 协作和自动化配置
│  ├─ ISSUE_TEMPLATE/                              # Issue 模板预留
│  └─ workflows/                                   # CI 工作流预留，首个测试通过后启用
├─ data/                                           # 本地运行数据，真实内容不提交
│  ├─ databases/                                   # SQLite 数据库
│  ├─ logs/                                        # 运行与调试日志
│  ├─ exports/                                     # 用户主动导出的数据
│  ├─ backups/                                     # 迁移或危险操作前的备份
│  └─ audio/                                       # 后续语音阶段的本地音频
├─ datasets/                                       # 固定、可版本化的评估输入
│  ├─ synthetic/                                   # 人工合成样例
│  ├─ benchmarks/                                  # 外部公开 Benchmark
│  ├─ regression/                                  # 固定回归数据
│  └─ README.md                                    # 数据来源、格式和许可
├─ docs/                                           # 长期文档和决策记录
│  ├─ guides/                                      # 面向用户的日常操作指南
│  │  └─ 使用说明.md                               # 当前启动命令、参数、页面操作与排障
│  ├─ requirements/                                # 版本范围与完成标准
│  │  ├─ companion-product.md                      # P1–P5 产品范围与验收标准
│  │  ├─ 自定义功能清单.md                         # 自定义候选、当前状态和实施优先级
│  │  └─ v0.1.md                                   # V0.1 需求
│  ├─ architecture/                                # 架构和数据流
│  │  ├─ overview.md                               # 总体模块边界
│  │  ├─ workflows.md                              # 当前与拟议运行流程，含失败和停止行为
│  │  ├─ memory-pipeline.md                        # 记忆纵向流水线
│  │  └─ repository-structure.md                   # 仓库结构约定
│  ├─ adr/                                         # Architecture Decision Record
│  │  ├─ 0001-modular-monolith.md                  # 模块化单体
│  │  ├─ 0002-l0-l1-memory-model.md                # L0/L1 模型
│  │  ├─ 0003-local-sqlite-storage.md              # 本地 SQLite
│  │  ├─ 0004-memory-assertion-lifecycle-and-provenance.md # 声明、证据与生命周期
│  │  └─ 0005-early-device-demo-and-private-model.md # 提前圆屏演示与模型接入边界
│  ├─ development/                                 # 开发和排障指南
│  │  ├─ setup.md                                  # uv 与 PyCharm 环境
│  │  ├─ troubleshooting.md                        # 已确认故障记录
│  │  └─ campus-model-validation.md                # 校园网真实调用与合成验证步骤
│  ├─ research/                                    # 研究问题和评估设计
│  │  ├─ research-questions.md                     # 当前研究问题
│  │  ├─ baseline-plan.md                          # Baseline 计划
│  │  └─ evaluation-plan.md                        # 分阶段指标
│  ├─ hardware/                                    # 圆屏硬件事实与验证记录
│  ├─ deployment/                                  # 后续部署文档
│  └─ versions/                                    # 版本状态和复盘
│     └─ v0.1.md                                   # V0.1 版本记录
├─ experiments/                                    # 实验配置、运行产物和报告
│  ├─ configs/                                     # 可复现实验配置
│  ├─ runs/                                        # 每次实验的原始运行产物
│  ├─ jobs/                                        # 网页作业进度与去重台账，首次启动生成、不提交
│  ├─ results/                                     # 结构化结果
│  └─ reports/                                     # 可阅读报告
├─ firmware/                                       # 后续圆屏终端集成
│  ├─ smartring_plus/                              # 本项目设备端内容
│  │  ├─ main/                                     # ESP-IDF 应用入口
│  │  ├─ components/                               # 自有 ESP-IDF 组件
│  │  ├─ assets/                                   # 圆屏资源
│  │  └─ docs/                                     # 设备端说明
│  ├─ configs/                                     # 可提交的设备配置示例
│  ├─ patches/                                     # 针对明确上游版本的补丁
│  ├─ diagnostics/                                 # 独立硬件诊断，不自动烧录
│  │  └─ axp2101_readonly/                         # 只读 PMIC 状态与充电排查
│  └─ README.md                                    # 上游边界和使用约定
├─ notebooks/                                      # 探索性分析，稳定逻辑迁回源码
├─ scripts/                                        # 可重复执行的辅助脚本
│  ├─ development/                                 # 本地开发辅助
│  ├─ evaluation/                                  # 批量评估
│  ├─ maintenance/                                 # 导入导出和维护
│  └─ migration/                                   # 数据结构迁移
├─ src/                                            # Python src layout 根目录
│  └─ longmemory/                                  # LongMemory 主包
│     ├─ __init__.py                               # 包标识和版本
│     ├─ __main__.py                               # python -m longmemory 入口
│     ├─ bootstrap.py                              # 依赖装配
│     ├─ methods/                                  # 完整记忆方法的中立入口（阶段 A 已实现）
│     │  ├─ contracts.py                           # 消息、结果与方法能力；不依赖 L1/SQLite
│     │  ├─ factory.py                             # 通用白名单：v1 与原始对话分块；日常仍用 v1
│     │  ├─ longmemory_v1/                          # 包装现有基线，不复制核心算法
│     │  │  └─ method.py                           # 方法状态、接收消息、召回和资源释放
│     │  ├─ daily_llm/                              # P3.2 可选日常模型提取，L0 优先持久化
│     │  │  └─ method.py                           # 严格候选转 L1、显式 source_only 降级
│     │  ├─ dialogue_chunks/                       # 原始消息分块批处理对照，保留角色/会话
│     │  │  └─ method.py                           # 封存历史与关键词召回
│     │  └─ llm_extract/                           # D1 实验模型提取条件，不自动用于日常库
│     │     └─ method.py                           # 网络提取与写事务分离、来源审计及冻结重开
│     ├─ core/                                     # 不依赖外部技术的核心层
│     │  ├─ common/                                # 公共类型和领域异常
│     │  │  ├─ identifiers.py                      # 稳定标识符
│     │  │  └─ exceptions.py                       # 领域异常
│     │  ├─ conversation/                          # L0 原始对话
│     │  │  ├─ models.py                           # 会话与消息模型
│     │  │  └─ contracts.py                        # L0 存储契约
│     │  └─ memory/                                # L1 及未来记忆能力
│     │     ├─ models.py                           # 记忆与来源模型
│     │     ├─ contracts.py                        # 记忆存储和模型契约
│     │     ├─ extraction/                         # 记忆判断与规范化
│     │     │  ├─ policy.py                        # 提取规则
│     │     │  ├─ service.py                       # 原规则提取服务
│     │     │  └─ candidates.py                    # D1 候选协议、来源摘录及整批校验
│     │     ├─ retrieval/                          # 基础召回和上下文构建
│     │     │  ├─ service.py                       # 检索服务
│     │     │  └─ context_builder.py               # 受控上下文
│     │     ├─ l0_conversation/                    # L0 后续扩展位置
│     │     ├─ l1_atomic/                          # L1 规范模型与存储契约；旧路径兼容转发
│     │     ├─ l2_scenario/                        # L2 场景、来源、审计与复核契约
│     │     ├─ l3_persona/                         # L3 原子画像、来源与生命周期领域契约
│     │     ├─ conflict_resolution/                # 冲突处理预留
│     │     ├─ forgetting/                         # 遗忘机制预留
│     │     └─ consolidation/                      # 记忆整合预留
│     ├─ application/                              # 用例编排层
│     │  ├─ memory_runtime.py                      # 网页与圆屏共享的常驻记忆实例及串行边界
│     │  ├─ chat/                                  # 一轮聊天闭环
│     │  │  ├─ contracts.py                        # 回答生成器契约
│     │  │  ├─ dto.py                              # 聊天输入输出
│     │  │  └─ service.py                          # 聊天用例
│     │  ├─ memory_management/                     # 查看和 L1 删除；撤销能力预留
│     │     ├─ dto.py                              # 管理输入输出
│     │     └─ service.py                          # 管理用例
│     │  └─ scenario_management/                   # L2 候选创建与人工复核用例
│     ├─ adapters/                                 # 外部技术适配器
│     │  ├─ device_control/                        # 本机小智控制桥客户端，不进入记忆核心
│     │  │  └─ xiaozhi.py                          # 保管令牌、限制字段、处理未知执行结果
│     │  ├─ storage/                               # SQLite 存储实现
│     │  │  ├─ sqlite_conversation_store.py        # L0 SQLite 实现
│     │  │  ├─ sqlite_memory_store.py              # L1 SQLite 实现
│     │  │  └─ sqlite_scenario_store.py            # L2 事务、证据门槛与复核实现
│     │  └─ llm/                                   # LLM 实现
│     │     ├─ fake.py                              # 可预测测试模型
│     │     └─ openai_compatible.py                 # 后续真实模型适配
│     ├─ infrastructure/                           # 跨模块基础设施
│     │  ├─ config/                                # 环境变量和运行配置
│     │  │  └─ settings.py                         # 类型化设置
│     │  ├─ database/                              # SQLite 连接和结构
│     │  │  ├─ connection.py                       # 连接与事务
│     │  │  ├─ definition.py                       # 当前数据库版本与完整结构
│     │  │  ├─ schema.py                           # 初始化与连续迁移调度
│     │  │  └─ migrations/                         # V1→V4 各代可追溯迁移
│     │  └─ logging/                               # 日志配置
│     │     └─ setup.py                             # 脱敏日志初始化
│     ├─ entrypoints/                              # 外部入口
│     │  ├─ cli/                                   # V0.1 命令行入口
│     │  │  ├─ app.py                              # CLI 启动
│     │  │  ├─ commands.py                         # 管理命令
│     │  │  └─ presenter.py                        # 输出格式
│     │  ├─ api/                                   # 本机控制台 HTTP API
│     │  │  ├─ __main__.py                         # python -m longmemory.entrypoints.api
│     │  │  ├─ server.py                           # 白名单静态资源与设备接口
│     │  │  ├─ security.py                         # 同源会话、CSRF、Host 与安全响应头
│     │  │  ├─ memory_backend.py                   # 已有库装配、L1/L0 浏览和写操作前快照核对
│     │  │  └─ routes/                             # 分功能 API 路由
│     │  │     ├─ memories.py                     # L1/L0 列表、双向来源、纠正和单条删除请求
│     │  │     ├─ memory_mode.py                  # 网页/圆屏共享的运行期写入与使用开关
│     │  │     └─ memory_runtime.py               # 仅回环、令牌鉴权的小智 Runtime 接口
│     │  └─ xiaozhi/                               # 后续 Xiaozhi 入口
│     │     ├─ adapter.py                          # 协议适配
│     │     └─ mapping.py                          # 消息映射
│     ├─ evaluation/                               # 评估逻辑
│     │  ├─ metrics.py                             # 分阶段指标
│     │  ├─ runner.py                              # Baseline/实验组运行器
│     │  └─ reports.py                             # 报告输出
│     └─ prompts/                                  # 可版本化 Prompt 资源
│        ├─ extraction/                            # 提取 Prompt
│        ├─ generation/                            # 回答 Prompt
│        ├─ evaluation/                            # 辅助评估 Prompt
│        └─ consolidation/                         # 后续整合 Prompt
├─ tests/                                          # 自动化测试代码
│  ├─ unit/                                        # 快速单元测试
│  │  ├─ core/                                     # 核心规则测试
│  │  ├─ application/                              # 用例编排测试
│  │  └─ adapters/                                 # 适配器测试
│  ├─ integration/                                 # 多模块和真实 SQLite 测试
│  │  ├─ database/                                 # 数据库集成
│  │  └─ memory_pipeline/                          # 记忆流水线集成
│  ├─ e2e/                                         # 写入—重启—回忆闭环
│  ├─ web/                                         # Node 原生前端状态测试，不访问实机
│  ├─ regression/                                  # 已修复问题回归
│  ├─ data/                                        # 测试内部小型 fixture
│  └─ conftest.py                                  # pytest 公共夹具
├─ web/                                            # 本机控制台；全部资源本地托管，无 CDN
│  ├─ index.html                                   # 设备与状态页面
│  ├─ memories.html                                # 原生记忆页回退，由 /memories-legacy 提供
│  ├─ chat.html                                    # 文字聊天和逐轮记忆轨迹
│  ├─ experiments.html                             # 实验档案、逐题对照和人工复核
│  ├─ react-chat/                                  # 渐进统一的 React/TypeScript/antd 控制台工程
│  │  ├─ src/                                      # 聊天、L1/L0 记忆页、设置组件与 API 封装
│  │  ├─ dist/                                     # 本机构建产物，不提交 Git、日常无需 Node
│  │  ├─ package.json                              # 固定脚本和直接依赖
│  │  └─ pnpm-lock.yaml                            # 可复现的前端依赖锁
│  ├─ assets/                                      # 当前本地资源，只有白名单文件由后端提供
│  │  ├─ app.js                                    # 会话、状态轮询、音量操作和纯文本渲染
│  │  ├─ state.mjs                                 # 可独立测试的状态与结果映射
│  │  ├─ memories.js                               # 记忆页面交互、纯文本来源显示和删除确认
│  │  ├─ memory-view.mjs                            # 记忆元数据、时间与分页文案
│  │  ├─ experiments.js                            # 实验选择、逐题请求与追加式复核操作
│  │  ├─ experiment-view.mjs                        # 可测试的实验文案和纯文本证据展示
│  │  ├─ experiments.css                           # 档案列表与横向对照卡片样式
│  │  ├─ console.css                               # 响应式本地样式
│  │  └─ favicon.svg                               # 本地站点图标
│  ├─ public/                                      # 早期骨架预留，当前不由后端公开
│  ├─ src/                                         # 早期模块化位置预留，尚未搬迁
│  │  ├─ api/                                      # 后端请求
│  │  ├─ components/                               # 通用组件
│  │  ├─ features/                                 # 业务功能
│  │  └─ styles/                                   # 全局样式
│  └─ README.md                                    # 当前前端方案、边界与启动入口
├─ .env.example                                    # 安全配置示例
├─ .gitattributes                                  # 换行和二进制属性
├─ .gitignore                                      # 密钥、数据和构建产物排除
├─ .python-version                                 # Python 版本固定
├─ AGENTS.md                                       # 人机协作规则
├─ CHANGELOG.md                                    # 已完成变更
├─ ROADMAP.md                                      # 后续版本计划
├─ pyproject.toml                                  # Python 项目与工具配置
├─ uv.lock                                         # 由 uv 自动生成的依赖锁
└─ README.md                                       # 项目总览与真实状态
```

### 骨架约定

- Python 包目录使用 `__init__.py`，它可以合法为空。
- 普通空目录使用 `.gitkeep`，避免 Git 丢失目录。
- `uv.lock` 必须由 uv 生成，不能手工创建空文件。
- 未实现模块只表示扩展位置，不写成当前功能。
- `src/` 本身不是 Python 包，因此不放 `src/__init__.py`。
- 许可证尚未决定，因此暂不保留空 `LICENSE`。

## 开发环境

```powershell
cd "D:\02-项目\LongMemory-SmartRing"
uv sync
uv run python --version
uv run pytest -p no:cacheprovider
uv run longmemory
```

`uv sync` 会把 src layout 项目以可编辑方式安装到 `.venv`。CLI 也可以使用 `uv run python -m longmemory` 启动，默认数据库位于 `data/databases/longmemory.db`。

当前自动化测试覆盖项目安装状态、领域模型、记忆提取、基础检索、聊天编排、SQLite 重开持久化、记忆来源查看、L1 删除、CLI 交互和最小端到端闭环。`-p no:cacheprovider` 仅关闭 pytest 的本地缓存写入，不影响测试行为。

PyCharm 解释器选择：

```text
D:\02-项目\LongMemory-SmartRing\.venv\Scripts\python.exe
```

## 数据与隐私

- L0、L1 默认保存在运行 LongMemory 的电脑或私有服务器，不放在圆屏中。
- `.env`、真实对话、SQLite、原始音频和运行日志不得提交。
- API Key 只通过环境变量或本地密钥配置提供。
- 测试优先使用合成数据。
- 每条 L1 必须保留 L0 来源，且支持查看和删除。

## 路线图

当前产品主线见 [ROADMAP](ROADMAP.md) 的 P1–P5。下列原版本标识仅为历史候选，不再作为执行顺序；基础小智/圆屏演示已经前移完成。

```text
V0.1  PC 文本版 L0/L1 持久记忆闭环
V0.2  语义检索和混合召回
V0.3  分类、重要度和去重
V0.4  冲突更新
V0.5  遗忘、衰减和整合
V0.6  L2 场景记忆和 L3 用户画像
V0.7  Xiaozhi Server 适配
V0.8  SmartRing-Plus 圆屏终端接入
V0.9  长周期实验和主动记忆
```

## 参考资料

历史里程碑见[本机控制台决策](docs/adr/0007-local-console-and-device-control.md)；设备页实机操作已确认，[记忆管理页](docs/deployment/local-console.md)已实现。当前优先级以 ADR-0015 和产品路线为准。

- [SmartRing-Plus](https://gitee.com/VIEWESMART/SmartRing-Plus)
- [Xiaozhi AI 开发资料](https://xiaozhi.dev/)
- [Xiaozhi ESP32](https://github.com/78/xiaozhi-esp32)
- [Xiaozhi ESP32 Server](https://github.com/xinnan-tech/xiaozhi-esp32-server)
- [TencentDB Agent Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory)
- [VibeVoice](https://github.com/microsoft/VibeVoice)：语音模型候选资料，暂不接入。
- [voice-studio](https://github.com/mjlzz/voice-studio)：语音工作台与离线 TTS 参考，暂不接入。

2026-09-03 用户决定：上述两个语音项目先收藏，优先完成主线；当前先体验已有爱莉希雅风格提示词，继续使用 EdgeTTS，不启动音色优化或新增依赖。

## 许可证

许可证尚未决定。正式引入第三方代码前，需要分别核对其许可证和保留声明要求。
