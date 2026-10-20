# AI：L6/L7 与低延迟组合契约、审查和隔离整合

日期：2026-10-21。状态：第一里程碑已提交 `795beb2`；第二阶段正在隔离审查/组合接线。AC/AD/AE/AF/AG/AH 首期已接入本分支，AB 及各方向后续接口等待精确提交。日用发布未执行。本文是本轮公共任务书，功能交付、组合证据与日用发布分别记录，不能互相代替。

## 授权、范围与完成标准

所有者要求 L6/L7 完整接入及全部延迟方向开始实施，并保持日用可用。主会话协调资源、接口、审查与合入；各独立会话只提交自己的分支。AI 不自行领取其他分支、不 merge main、不推送、不部署、不改共享私有配置、消费副本、个人数据或日用进程，不访问日用端口，不加载 GPU 模型、不调用真实学校接口、不操作设备。

共同基线为 `a93258e903954525b88b7af79756aaffe2bd50d6`。AI 工作树是 `local/worktrees/ai-integration-review-20261021`，分支是 `codex/ai-integration-review-20261021`；侧栏项目标注不改变真实文件归属。保留学校免费 `DeepSeek-V4-Flash`、现有角色与声音、buffered 默认、增量实验状态及官方原 unknown 账本。保留 `0179789` 已有 system 顺序和推理边界修复。

AI 第一阶段完成标准：

1. 明确接口身份、取消/副作用边界、计时定义和文件所有权；把代码事实与提议区分开。
2. 标准库合成回放工具可离线检查跨方向事件契约，覆盖正常、续说、取消、过期快照、等待音、推理、跨轮串包及缺失播放证据；不能用模拟事件宣称业务实现通过。
3. 对现有真实模块运行相关隔离回归，报告实际范围与缺失证据。
4. 主会话交付功能提交后逐项审查，再按指定提交接入本分支、增加真实适配组合测试。没有提交时继续可独立核查，不用空实现占位。
5. 未触发生产生命周期；最终合入、GPU 独占、学校最小调用、日用切换及所有者真机体验各有独立证据。

## 会话与文件归属

以下 ID 是主会话实际创建结果。各会话的 `local/worktrees/` 都在主项目下。

| 方向 | 侧栏真实标题 | 会话 ID | 工作树后缀 / 分支后缀 |
|---|---|---|---|
| AB | 智慧圆屏 AB｜Hy-Memory L6/L7 完整接入 | `01a15ab0-09f3-7962-93b2-6b7e46cbac91` | `ab-hy-l6-l7-20261021` |
| AC | 智慧圆屏 AC｜中文话轮结束与 Smart Turn | `01a15ab0-0d29-7c31-a57b-702f28d8e164` | `ac-smart-turn-20261021` |
| AD | 智慧圆屏 AD｜CosyVoice 连续增量与自适应缓冲 | `01a15ab0-11e7-7330-91d8-132fc191126f` | `ad-cosy-continuity-20261021` |
| AE | 智慧圆屏 AE｜可取消的受控提前生成 | `01a15ab0-1582-7262-90b8-60e80a746a22` | `ae-preemptive-20261021` |
| AF | 智慧圆屏 AF｜学校 DeepSeek 缓存与模型首字优化 | `01a15ab0-1918-7fd3-9fb8-e7af65525954` | `af-prefix-cache-20261021` |
| AG | 智慧圆屏 AG｜TensorRT、vLLM 与量化验证 | `01a15ab0-1cd8-7243-9315-dfdea73dc5f9` | `ag-inference-engines-20261021` |
| AH | 智慧圆屏 AH｜L6/L7 展示与延迟观测 | `01a15ab0-21fa-7000-8a33-9832499b1272` | `ah-hy-observability-20261021` |
| AI | 智慧圆屏 AI｜低延迟组合契约、审查与整合 | `01a15ab0-25a3-7380-b682-681441e8b403` | `ai-integration-review-20261021` |

各分支名为 `codex/<后缀>`。不互发消息、不重复开工，接口由主会话转接。

| 方向 | 具体归属与现有锚点 | AI 的接合点 |
|---|---|---|
| AB | `src/longmemory/methods/hy_memory/`，尤其 `worker.py`、`settings.py`、`assembly.py`、`management_rpc.py`、`administration.py`、`sdk_bridge.py` | 真实后台队列/读写一致性证明、快照版本、管理屏障和关闭语义 |
| AC | 话轮结束 EOU（用户话语结束）及 ASR（语音识别）预取；`scripts/development/xiaozhi/voice_asr_prefetch.py`、输入边界 | EOU 判定结果、轮次与转写版本；启动安装次序 |
| AD | Cosy 服务、`cosyvoice_streaming.py`、`cosyvoice_segments.py`、播放/缓冲与 `voice_latency.py` | 音频 epoch（取消代次）、首有效答案包、发送与取消语义 |
| AE | 候选生命周期及预测；现有 `voice_prediction.py` 只提供影子统计 | 无副作用快照、提交门与废弃成本 |
| AF | `hy_memory/model_gateway.py`、供应商传输和缓存观测 | 真实 usage、首有效文本、固定前缀语义和未知保留 |
| AG | 新增引擎适配及基准文件 | 可用性/能力报告，禁止默默回退或抢 GPU |
| AH | Hy 前端、只读展示与观测 UI | 能力/证据/关闭原因，发送不能显示为已播放 |
| AI | 本文、`scripts/development/xiaozhi/launch_with_memory.py`、新增 `voice_combination_replay.py` 及其合成数据与组合测试 | 公共启动接线唯一编辑者；收到具体提交后才安装新方向 |

`model_gateway.py`、新增 `prefix_cache.py` 同属 AB 目录而由 AF 专责：AB 不同时改它们；如 AB 要新增后台调用语义，由主会话转接 AF。`voice_latency.py` 由 AD 编辑，AH 消费公开观测结果；AI 仅审查。文档清单由主会话登记本文及源码关联，AI 不越界修改共享清单。

## 基线代码核查

- `launch_with_memory.py:main` 先安装输入计时，再安装 ASR 预取/HTTP 保活，随后 fast response、latency、发送观察、等待音、回答归档、影子预测、内部结束提示隔离及持久会话。组合时必须保留包装顺序；新安装器应幂等、关闭时不加载重模型。
- `voice_input_latency.py` 在 `handle_voice_stop` 创建 trace，使用 VAD（语音活动检测）的墙钟尾时间估计端点等待，另用单调时钟计 ASR 处理。这个估计不是设备标注的真实停嘴时间，不能直接拼成精确 E2E（端到端）收益。
- `voice_latency.py` 明确以顶层 `chat` 为计时原点；`observed_audio_sender` 发送返回和等待音另判，实时答案交最终 socket 包装器。缺少设备 ACK（确认回执）时没有实际播放事实。
- `voice_diagnostics.py` 只保留固定白名单事件，每类每轮首次投递；其 HTTP 到达时刻与 `sequence` 不提供跨服务同钟时间戳，也不是逐音频包无丢失日志。
- `voice_asr_prefetch.py` 预识别 300ms 静音候选，不提前聊天；模型线程与正式识别共锁，取消协程不会假装终止仍运行的推理线程。
- `voice_prediction.py` 的封闭问题预测只有计数，没有模型调用、音频或持久化。不能将其称为 AE 已实现。
- `voice_prediction.py:install_voice_prediction_shadow` 的 `shared` 影子计数器由类级闭包持有，当前不是逐连接的候选容器；AE 的轮次/身份状态不能复用这个闭包作为隔离边界。仅影子计数，不能据此推断已有跨连接内容泄漏。
- `voice_latency.py:_has_output` 把工具调用也计入通用 `llm_first_output_ms`；有效答案首文本须使用过滤后的明确文本边界，AH 不能把该通用字段直接改名为首有效答复。
- `hy_memory/worker.py:create_sdk` 使用固定 2.0.3、`mode="pro"`，关闭 profile/system2/intention cache、intention 与图等；`assembly.py` 的管理回执明确要求 `semantic_background_writes_disabled=true`。L6/L7 必须由 AB 重建真实证明链，不能直接翻开关继续使用旧回执。
- `model_gateway.py` 分离最终答案与推理，流式请求声明 usage；中断/缺 usage 保留 unknown。新缓存统计不能把未知填零或释放历史预留。

以上是基线事实，未表示 AB–AH 的新分支已经交付或日用已切换。

## 公共接口草案（由主会话转接，各方向确认后冻结）

下列字段描述语义，不冒充已经存在的生产 API。回放工具拥有独立 `synthetic-voice-combination-v1` 格式；功能模块交付后需要真实适配器，不能把回放状态机安装到日用系统。

| 边界 | 必须保持的语义 | 验收门槛 |
|---|---|---|
| EOU / 转写 | 每连接唯一轮次；`transcript_revision` 变化即旧候选失效；区分 `listening/tentative/confirmed/resumed/cancelled`；最终 ASR 与 EOU 确认分别有事实 | 中文句中停顿/否定/改口/“嗯…还有”/续说；模型超时或不可用回既有 VAD，不把未决判成确认 |
| 快照 | `memory_revision` 与角色/模型/工具策略身份共同绑定快照；读取必须无强度更新、惰性 L7 转换、隐式提取或队列写入 | AB 提供实际 SDK 路径证明；不把“仅检索”自动认定无副作用 |
| 候选 | `created→running→ready→adopted`，或任意未提交阶段 `discarded/cancelled/expired`；候选绑定轮次、转写修订、快照、音频代次和供应商身份 | 不归档、不写记忆、不执行工具、不发声；正式终稿、EOU、最新快照、身份一致才单次接管；失败走普通链路 |
| 正式提交 | 记忆接收用户输入和助手最终答案分别一次；续说、后台/管理修订、超时、断连、abort 必须阻止旧提交 | 不能仅用字符串相等代替版本/身份检查；工具候选不得提前执行 |
| 音频 | 每轮 `audio_epoch`；续说/打断/断开提升代次，TTS 消费、缓冲、流控和最终发送都核对；等待/答案分型 | 停止上游/关闭连接不等于已清空设备缓冲；首包后断流不得整句重播；逐块连续性与残音由 AD 给实际证据 |
| Hy 后台 | 任务有有界队列、来源、确定身份、状态和失败；后台写与 correct/delete 同一串行/版本屏障 | 管理后不能复活被删除/纠错的事实；重启、关闭 flush/drain、失败恢复实测；旧证明必须拒绝 |
| 缓存 usage | 区分供应商实际 hit/miss 字段、字段缺失、usage 缺失、断流；端点/模型/角色/系统前缀/用户尾部原语义不变 | 无 usage 不填零；缓存命中不能仅以快判；不为扩大命中挪动消息、泄漏推理或改变角色 |
| 开关/回退 | 每方向独立能力、已请求状态、实际激活状态和关闭原因；buffered 为默认，增量/提前生成为实验 | 不可用回既有已授权链路；不自动改供应商、模型、付费预算、GPU 引擎或生产配置；启动失败不遗留新进程 |

AB 的持久化/系统边界变化、AC/AE 的提交门及 AD/AG 的新框架绑定需要 ADR（架构决策记录）；编号由主会话协调。AI 当前只实现测试侧事件审查，不自行建立生产持久化模型或占用 ADR 号。

主会话随后已分配：AB 0195、AC 0196、AD 0197、AE 0198、AF 0199、AG 0200、AI 0201、AH 0202。仅按实质需要创建，AI 本次测试侧回放没有新增生产架构决定，不为占号新建 0201。

主会话转接的第一轮边界：AC 输入为 16kHz/单声道/60ms PCM（脉冲编码调制音频），须在清空音频前接管，续说作废；AD 正补有界 reader 与自适应缓冲，当前直接帧入队不能充当缓冲恢复证据；AE 仅 LLM（大语言模型）候选，不 TTS（语音合成）/工具/字幕/来源归档；AB 重建后台和管理证明链；AH 先以 fixture（合成接口样例）接 UI，真实 DTO（数据传输对象）待 AB/AD。AG 无 GPU 租约。以上为各方向正在实施的范围，未宣布已完成。

## 测量契约

主指标是**用户说完到首个有效回答声音实际播放**。等待提示、推理、静音包、连接提示不算答案。每条证据写明采集边界、时间原点/单位、单调时钟域、运行/轮次/修订/音频代次和证据来源，正文不入诊断。

| 事实 | 能证明的边界 | 不能据此宣称 |
|---|---|---|
| 用户尾声 | 设备/人工标注输入最后语音采样；VAD 估计单列 | VAD 端点检测时刻等于用户说完 |
| EOU 与 ASR 终稿 | 判定确认、最终转写交付 | 首个 partial 是终稿 |
| 记忆快照 | 同一 revision 可用的快照完成 | 独立 recall 耗时可直接加到端到端 |
| LLM 首有效文本 | 最终答案边界之后首个可读文本；工具/推理另计 | 模型任意 token 是有效答复 |
| TTS 首包 | 当前 epoch 的有效答案音频可用 | HTTP 头/空 FIRST/等待提示已回答 |
| 发送完成 | 当前 epoch 首答案包实际发送调用返回 | 音频已经被设备播放 |
| 实际播放 | 设备回执或同步采集/所有者人工结果，记录时钟转换误差 | 没连设备的电脑回放已验实机 |

不同时间域不能直接相减。若使用接收端事件序号，没有同步时钟转换/误差证据则只报告事件顺序。各阶段重叠、排队、取消成本单列，**不能把独立阶段耗时相加当 E2E**。合成回放的毫秒值仅用于验证差值与归属算法，不是性能测量。

同一数据/模型/角色/声线/工具/网络条件下成对比较 buffered baseline（对照基线）与候选，冷/热启动分开。中文停顿误抢话以标注完整话轮为分母；续说错误接管、错误入库、取消残音、音频断续、快照一致性、最终回答质量和工具一致性均单列。报告废弃候选调用数/token/运行时间，未知 token 保持未知。样本不足不报 P95（95 分位数）收益；回放工具只给样本量和中位数，不给收益推断。

## 隔离组合矩阵与后续资源建议

离线先覆盖：全开关关闭；AC 单开与 fallback；AD buffered/增量/首包前后故障；AE 与续说/改口/快照变化；AB 后台与纠错/删除/重启竞争；AF 缓存命中/未知与推理边界；组合开关及断连；两连接/轮次交错。AI 先交付合成事件检查与现有真实模块回归，SDK/模型/音频实测由对应方向交付后补齐。

GPU 独占建议：主会话先核对正式资源所有权并安排已授权窗口；一次仅一个方向加载，依次 AC → AD → AG，记录显存、模型/引擎指纹、冷/热、取消后占用和退出归还。AG 不与日用/Cosy/ASR 抢占，不自行停服务。没有窗口时继续 CPU/mock 回放；不把未跑模型写成硬件不支持。

学校免费接口：主会话已对 **AF 专责会话**明确批准最多 6 次、单次最多 32 输出 token 的纯合成串行缓存探测，使用隔离审计账本、无重试、不改共享预算。AI 不执行真实调用。建议同前缀/同尾部与同前缀/改尾部分组，任何超时/断流/缺 usage 立即停止余下请求并保留 unknown；实际已用次数和真实边界由 AF 交付。学校模型调用不等于本地 GPU 验收，免费也不能绕过审计或旧预算隔离。

## 交接登记

| 方向 | 提交 | AI 审查/接入 | 验证与限制 |
|---|---|---|---|
| AB–AH | 待主会话交付具体提交 | 未接入 | 不读取同伴脏树，不提前声明功能完成 |
| AI 第一阶段 | 见本分支提交与主会话汇总 | 本分支独立实施 | 235 项隔离测试通过；无日用、学校/GPU/设备验收 |

主会话需接力：转发接口草案并收各方向实际导出函数/形状、统一 ADR 编号及共享清单登记、安排真实资源窗口、给出允许 cherry-pick 的精确提交与依赖顺序。后续追溯必须保留“任务 → 功能提交 → AI 验收 → 主库合入提交 → 会话 ID”，提交完成不表示可以归档未整合会话。

## 第一阶段实际交付与验证

文件均在 AI 工作树：

- [回放工具](../../../scripts/development/xiaozhi/voice_combination_replay.py)：只读有界合成 JSON，拒绝混钟、倒序、未知/正文承载字段；检查身份、EOU/终稿/快照提交门、候选单次接管、续说/管理修订/取消、禁止候选来源/记忆/工具副作用及旧代次发声。取消后的最终成本仅允许观察，不重新获得接管或发声资格；已接管后取消与推测废弃分开计数。未知 token/耗时保留未知计数。
- [合成输入](../../../datasets/synthetic/hy-advanced-combination-v1.json)：5 个纯事件场景，含 buffered、候选接管、中文停顿续说、管理修订与打断迟到包；没有真实文本/音频，不能计算中文停顿错误率或音频连续性。
- [工具测试](../../../tests/unit/development/test_voice_combination_replay.py)：32 项正反路径验证。
- [真实包装器组合测试](../../../tests/integration/test_voice_combination_boundaries.py)：5 项，将工作树真实 `FinalStream`、语音 LLM/TTS 观察器、发送计时、回答归档和影子观察按现有启动顺序组合；供应商/音频/传输/记忆存储全为进程内替身。覆盖碎片 think 过滤、system 在 user 之前且不污染原消息、单次归档、重复安装幂等、空输出/超时取消及 ContextVar 清理。取消测试只验归档门，不宣称已证明音频 epoch/设备残音。

工具运行命令（在 AI 工作树，使用主项目现有 3.12.13 解释器，绝不触发安装）：

```powershell
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -X utf8 -B scripts/development/xiaozhi/voice_combination_replay.py
```

退出码 0 表示正反场景的检测码与期望逐项一致，**不表示输入里所有事件都是安全路径**；1 表示检测结果不符，2 表示格式/读取失败。输出固定 `evidence=synthetic_replay_only`，`actual_playback_proven=false`。合成模拟 ACK 也不能变成真实播放事实；冷/热样本分开，只给合成发送中位数，不给 P95 或提速结论。此工具不是生产 `voice_diagnostics` 格式的解析器，不能将服务器 HTTP 接收时刻直接塞入同钟字段。

2026-10-21 实际检查：

| 检查 | 结果 / 范围 |
|---|---|
| 分支/状态/基线 | 开始时干净；`codex/ai-integration-review-20261021`，HEAD=`a93258e` |
| 解释器/源码来源 | 显式主项目 `.venv` Python 3.12.13 / pytest 9.1.1；`longmemory.__file__` 与组合模块 `__file__` 均核对来自 AI 工作树。系统稳定 python 为 3.13.16，未用它跑项目测试 |
| 新测试 | 32 工具单测 + 5 包装器组合测试，共 37 项通过 |
| 基线相关回归 | `test_voice_input_latency`、`test_voice_latency`、`test_voice_prediction`、`test_voice_asr_prefetch`、`test_voice_waiting_handoff`、`test_voice_web_search`、`test_hy_answer_content`、`test_hy_daily_stream`、`test_hy_provider_transport`、启动次序两模式 selector（指定测试函数）、`test_doc_maintenance`，共 198 项通过。等待音测试只读主项目已安装上游 Git 固定提交 `eb4b28c` 的调度器类，注入合成时钟，不启动其服务 |
| 最终同次运行 | **235 passed in 3.40s**；无 skip，非全仓测试，非 GPU/真实学校/真实 SDK 新功能或设备验收 |
| 官方文档查询 / 下载 / 依赖变更 | 本阶段只核本地源码，未联网、未下载、未安装、未改锁文件，无所有者下载需求 |
| 日用 / 设备 | 未连接日用端口、未改配置/个人库、未停服务、未打开串口、未烧录 |
| 文档严格检查 | `check_docs.py --only docs/development/parallel/AI-hy-advanced-low-latency-20261021.md --strict` 返回 1：`unlisted-document` + `unknown-selection`。原因是跨会话清单尚未由主会话登记；不能写成通过。正文链接另作直接检查 |
| 文档直接检查 / 登记候选 | `check_links` + `check_old_paths` 对本文 findings 为空；另只在进程内向清单副本加登记条目后 `audit(..., [本文])` 检查 1 份文档、findings 为空。未写共享清单，这不改变上行真实 strict 失败状态 |

主会话登记清单时建议使用：`status=draft`（接口尚未跨分支冻结），`review.state=verified`、`date=2026-10-21`，scope 仅为“基线源码核查、5 场景离线回放与 235 项测试；无 AB–AH 集成、日用/设备/真实模型性能证明”。`topics[].sources` 关联回放工具、合成输入、两个新增测试和 `scripts/development/xiaozhi/launch_with_memory.py`；最终生产能力继续归对应指南，不把本文设为日用步骤权威。主会话登记后须重跑严格检查。

未验证：AB 真实 L6/L7 后台持久化/管理一致性；AC 中文模型准确率；AD 连续增量听感、缓冲恢复和残音；AE 真实无副作用快照与候选调用；AF 学校缓存实际字段；AG 可用引擎/GPU 性能；AH 真 DTO 联调；任意同条件 E2E 收益与圆屏实际播放。AI 未编辑 `launch_with_memory.py`，因为新方向导出接口尚未交付；既有启动次序已回归，不用占位安装器冒充接线。

## 第二阶段：经主会话授权的隔离整合

主会话转接所有者新要求：查 AB–AI、安排接口接力，完成后审查整合，验证通过由主会话合入推送并恢复日用。AI 已获普通 cherry-pick/公共接线及共享文档清单、`docs/README.md` 登记授权；仍不合 main、不 push、不部署、不停日用、不动个人数据/设备。以下范围替代第一阶段“待批准接入”和“清单不归AI”的暂时边界；第一阶段 strict 失败是历史实际结果，保留。

### 实际接入顺序与提交

| 方向 | 主会话交付原提交 | AI 隔离分支对应提交 | 当前意义 |
|---|---|---|---|
| AC | `67ec9165641f6a9004e13837c7726c5586eea524` | `1217572` | 话轮状态与直接 CPU 适配；侧车及模型文件仍等接力 |
| AD | `fee1d86f489cf5cf49ab1d90d587ccf6ed76b7ee` | `7d132ea` | 有界 reader、自适应 PCM、队列/最终发送取消保护；真实 GPU 播放未验 |
| AF | `e8ce66d2d7c373dfb27ee6f9b45f27c2e3928717` | `6ed1a71` | 缓存/首有效文本观测；学校六次已用完，缓存字段未确认 |
| AE | `baedad5e5ce1f4da18bb3aefabeaeeecad954c78` | `5aad033` | 逐连接候选控制与 SSE 解析；实际快照/网关取消 ACK 桥仍等接力 |
| AG | `e6e8db5c82775360b920c3888a104fc0d0242938` | `61cc018` | 固定源码适用矩阵和隔离加速工具；不默认选择新引擎 |
| AH | `a741ec7ec6beb9f15f2c9675dfd4c10600d83779` | `e7f32a1` | 配置/实例/执行/内容证据分开展示；真实 AB DTO 后续联调中 |
| AB | 待精确提交 | 未接入脏树源码 | 只读取主会话允许的公共交付记录，按稳定候选接口先接公共门 |

每项先核文件归属、导出接口、记录和关键实现，再按上表顺序 cherry-pick，均无冲突。没有把隔离分支提交算作主库合入或生产放行。

### 本阶段公共实现

- `launch_with_memory.py` 接在输入计时/预取之后安装真实 AC 话轮模块。新增显式进程参数 `--voice-turn-end-mode` / `--voice-turn-end-model` / `--cosy-delivery-mode`，也可通过对应子进程环境输入。off 不导入模型；固定模型/依赖失败为 unavailable；enabled 缺真实校准决定不激活。buffered 为默认，adaptive 不自动开启。AC 常驻 CPU 侧车交付后再接独立工位，不自行安装依赖或调用 GPU。
- `MemoryRuntime` 初始化及写门实际变化时同步方法 `configure_background_writes`；失败保持前台暂停且不先改其他配置。新语义任务 Runtime 白名单、请求参数与 enqueue 写门共用原串行边界；只读 status/task 非阻塞，关闭中拒绝，cancel 可在前台暂停时请求，不声称 running 可回滚。
- 新增 `application/semantic_tasks.py` 固定参数白名单；新 `routes/hy_semantic.py` 由既有 `register_memory_engine_routes` 注册，全部只使用 peek 实例，不懒创建。读响应按主会话冻结为 AB DTO 顶层，status 附 runtime 门，读取附 `observed_at`；碰到保留附加字段冲突拒绝，不覆盖 AB 字段。权限、URL 和错误码见 [管理契约](../hy-memory-management-contract.md)。
- 新增 [ADR-0201](../../adr/0201-composed-runtime-write-gates-and-observation.md)，统一登记 13 份独立任务/ADR 和 7 个主题，补 `docs/README.md` 及管理/声音权威入口的窄范围说明。没有改根 README、CHANGELOG、ROADMAP 或原已接受 ADR。

### 第二阶段实际验证（持续追加）

1. `test_advanced_voice_bootstrap.py` + `test_hy_semantic_platform.py` + 既有包装器组合 + 两模式启动顺序 selector：**28 passed in 0.59s**。使用真实 Runtime/HTTP/会话/CSRF、合成方法/任务 DTO；这不是 AB SDK 后台一致性已验。
2. AC、AD、AE、AG 新模块与 AF 缓存、既有时序/等待/搜索/system/最终答案/流式预算/传输交叉回归：**331 passed in 10.82s**。其中 AD 本地 HTTP/Opus 使用合成音频，不能替代 GPU 模型或设备播放。
3. `check_docs.py --only` 对本阶段 17 份新/改文档实际 **0 findings，strict 通过**；此前未登记问题由本阶段真实登记解决，未屏蔽检查。
4. 公共门改动后补跑旧 Hy 管理/守卫/机制/逐层浏览、Runtime 证据/时间召回及文档机制：**109 passed in 1.87s**。与前述分组有交集，不相加冒充独立用例总数。

主会话已核对所有者下载的 Smart Turn ONNX：8,679,182 字节，SHA-256 `2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f`；AC 可继续真实 CPU/侧车验证，AI 未复制到正式资源。正式部署方必须逐项校验并明确复制到正式 `local/runtime/models/`，不能默默将可清理工作树当成永久资源。ONNX 加载不是中文校准通过，enabled 门仍保留。AG 的新小样本 CPU 量化结果等精确提交后登记，不能据此切换日用向量或重建个人索引。

仍未完成的真实接力：AB 最终提交和协议 2 证明；只读候选快照的实际向量/上下文/版本/校验令牌；AF 进入原网关审计的异步响应与 owned 请求退出 ACK（确认回执）；AE 声音事件/正式 prepare 后 fresh 校验与原取消门之间无 await 派发；AC 已装 Cosy Python 的常驻纯 CPU worker；AH 对最终 DTO 与任务状态；AG 新 CPU 证据/AD GPU 计划。普通 search、正式 prepare 不能用作候选快照。取消客户端连接不等于 owned 请求/供应商计算已结束，未知保持未知，计算槽保留至约定退出边界。

以上缺口正在由主会话转各自所有者，AI 继续公共实现与组合验证。软件模块默认关闭或 unavailable 只能说明安全降级，**不能写成用户要求的全部方向已完成**。

### 后续接入与真实公共边界核查

已按主会话逐项授权继续接入：AC `2c022a6→364e079`、`9eb2f98→d562d90`；AB `5a4c1ec→8e7f3d0`、投影修复 `eb031738→66a2b108`；AF `85b1d715→a5f75cd`、宿主服务 `bf317915→4803d303`；AE `07773e8→dee964554`；AG `d230d01→43eaf4c`、`f65a0e4→442bbc5f`；AH `ca1e488→c883d8f`、`70cad5b→ca5223e`；AD `fb9deec→30228f2`、WDDM 窗口修复 `172a355→16cf16df`。左侧为作者提交，右侧为 AI 隔离分支对应提交；不是主库合入提交。

真实 SDK 组合暴露出 `ManagedMemoryMethod` 来源包装器没有传递新能力，先前直接方法替身无法发现。AI 在该公共包装器新增显式受锁委托 `configure_background_writes/candidate_snapshot/candidate_validate`；读取不调用 archive/observe/recall，不泛化成任意 `__getattr__`。这同时修正了真实 Runtime 的后台写门穿透。

Runtime 候选读取使用宿主原网关的 CPU `embed(...,"query")` 及其已有编码锁，再调 AB 专用读取；不运行正式 prepare，不 reserve/归档/派生。候选票据额外绑定随机 Runtime 实例和配置修订，模型政策版本覆盖完整设置摘要、免费账本政策、嵌入配方身份、方法实现版本；凭据/端点只进内部摘要，绝不投给小智。角色、日期、历史由实际冻结 messages 和正式 messages 完整比对，不能用旧消息伪装 fresh。

只有实际正式 `prepare_round_screen` 才留下最多 64 条、30 秒有效的临时比对摘要，包含真实输入、记忆 context 和来源/正文证据，不复制正文、不新增持久表。confirm 要关联实际 `formal_turn_id/client_round_id/session_id`，完整比较后，在 Runtime 临界区内 fresh 校验引擎令牌并同步领取；完成/取消/关闭移除摘要。普通 search 和平台 round.status 均不能用来生成候选证明，后者本身会过期写状态。

新 [候选协议校验器](../../../src/longmemory/application/voice_proposal_contract.py) 和 [内部路由](../../../src/longmemory/entrypoints/api/routes/voice_proposals.py) 冻结五类 POST：`/api/internal/memory/proposals/{snapshot,start,confirm,cancel,close}`，沿原内部 Bearer/回环鉴权。三项 stamp 均是真整数 `[0,2^63)`；connection/snapshot/session ID 为 32 位小写 hex，client_round_id 为 24–32 位小写 hex，formal_turn_id 为规范 UUID。query 非空≤16000，messages 最多128条 `[role,text]`、首项唯一 system、后续仅 user/assistant、正文合计≤32000，准备上下文不含本次 user。请求体≤192KiB，不收额外字段或 transcript 别名；tools_required=true 直接 miss，不提前执行工具。具体请求字段由校验器 `EXTRA_FIELDS` 唯一维护。

读快照返回 ready 的 snapshot_id/memory_context 或 unavailable/null；start 只返回 preparing/miss；confirm 仅 adopted 才有最终 text，miss 为 null；cancel/close 只有真实 owned 请求退出确认才返回非 closing 和 `owned_upstream_exited=true`，`provider_compute_stopped` 始终 false。费用 unknown 继续由原账本保留，不从 ACK 推定已结算。server 仅在现有内部 token 通路注册宿主实例，默认关闭，可显式 `--enable-voice-preemptive` / 子进程 `LONGMEMORY_PREEMPTIVE_ENABLED=1`；这项候选开关与 SmartTurn enabled 独立。AE 语音 RPC client 仍待精确提交后接入 launch，宿主类/客户端不得重复实现。

当前新增实证：

- 真实 SDK 原生语义/逐层读取组 **13 passed in 80.19s**，无网络、无 skip；此组是较早指纹的隔离回归，不能替代最终源码的 release proof。
- 新 `test_hy_semantic_platform_sdk.py` 在当前公共 Runtime/包装器下 **2 passed in 11.59s**：真实非空画像＋事实＋意图的候选与正式 prepare 完全一致并单次领取；历史展开场景保留差异并回退。首次测试误假设“最新条目候选能覆盖历史展开”，实际定位为 SDK 的 Current/When 历史格式与来源不同，按已声明 latest-only 边界改为正反两组，没有删正式上下文或放宽比较门。
- 公共协议/真实会话鉴权、Runtime 的实际正式摘要、跨 session/轮次/输入/内容/来源/设置/引擎失效、单次领取与启动关闭组 **54 passed in 0.43s**；它们仍不替代真正跨进程正常命中。
- 新增候选宿主和 AB 正式身份迁移问题仍在接力。发现既有 source 账本将 implementation_version 绑定为持久身份，semantic adapter 版本变化会拒绝旧账本；未修复并真实验证 pro→semantic→重开→pro 前不部署，不改个人 identity 表。发现冷 pro Runtime 的 semantic status 可能经 sdk_call 懒初始化，已交 AB 补只读 guard。

前端 Git tree 已独立比对：AI 与 AH `70cad5b…` 的 `web/react-chat` 都为 `43ecb03553163f675e437193345f26a7f77942f4`。由主会话转 AH 使用其实体依赖离线构建和交付 dist/manifest/tree 摘要，AI 不联接 node_modules、不安装。

### AD 独立评审与实机门

`172a355` 的 v2 项目模型窗口代码独立复审通过，**46 passed in 4.59s**。AI 的真实只读采集得到 WDDM、37 C+G、1 C，36 verified_image＋2 protected_os_logical；未运行 GPU。只允许主会话按 PID/创建时间/路径或明确系统逻辑身份逐条审查的桌面基线，C/unknown、未批准身份、PID复用、上下文变化均拒绝。C+G不改称纯图形，保留 `same_process_background_workload_not_observable=true`，不是物理独占。只读基线不授予 GPU 租约。

主会话随后安排唯一 `AD-GPU-20261021-01`，已关闭并恢复原 main=`a93258e` 日用 ready。AI 只读核对报告 SHA-256 `90b350633537d1e902a581c5df2eee06abb4104d86d588f68c39509065fc689b` 与逐项数值：真实 TTS-only 149.92秒，当前 uses_default_voice=true、选中声线暖机后测量；physical_playback/selected_voice_quality/full_ASR_memory_LLM 均未证明。每类/模式 n=3，不报 P95 收益。

| 文本 / 指标中位数 | buffered | adaptive |
|---|---:|---:|
| 多句首能量帧 ms | 1791.824 | 1585.521 |
| 长句首能量帧 ms | 1871.434 | 1514.748 |
| 多句 TTS 生成/交付墙钟 ms | 4409.465 | 5437.864 |
| 长句 TTS 生成/交付墙钟 ms | 7986.935 | 11617.542 |
| 多句预测供给欠载 ms | 156.382 | 0 |
| 长句预测供给欠载 ms | 645.414 | 0 |

音频时长配对一致，中位多句6760ms、长句13000ms；墙钟包含背压，不能据此声称额外 GPU 运算或整体计算更快，也不能把 TTS 首能量帧当用户停说→首有效答声。before_audio/buffering/after_audio 三例新增旧帧0、后继新轮52/58/57帧、服务active_requests=0。**after_audio前三帧未过能量门**，只能说出帧后取消，未覆盖有效发声后打断。设备已收帧不能被软件回收。

结论为可进入受控 adaptive 上线候选，仍保持 buffered 默认。正式发布技术门通过后，由所有者使用原角色/声音，分别比较短答/多句长答连续性；在确实听到开口及中途改问，核对旧声残留、字幕与新轮完整性，再连续两三轮看连接/声音和记忆一致性。SmartTurn 正式 EOU 继续原策略（合成中文初筛4/5误切未改善），不把候选启用绑死于其 enabled。听感/残音/新轮异常则回 buffered；AI 不把电脑声音或出帧当圆屏验收。

## 最终部署/回退操作计划（只交接，不在AI执行）

本计划由主会话持有操作责任；需要先补齐最终 clean commit、公共后端/候选真实跨进程与旧 source 身份兼容、最终精确指纹的无网络 SDK/管理/HTTP 回归、前端同 tree 产物和新协议2证明。未满足则继续原日用，不提前改配置或重签 proof。AG TensorRT/vLLM/量化候选不阻塞其他已证实方向，也不混入本轮日用默认。

1. **冻结/登记**：记录原 main/目标提交、SDK解释器字节身份、所有新原语摘要、前端 manifest/资源tree、实际部署配置/引擎/来源/管理/调用账本/stamp 精确路径、当前模型/声音/角色和运行期开关。所有检查点放主项目新建且不存在的 `local/archive/hy-advanced-release/<UTC时间-随机ID>/`，不覆盖旧档案。原付费 unknown 与 V/X/Y/Z/AA 发布证据/解释器引用继续保留。
2. **按所有权停止**：先用生产根的正式 control 读 status，重新核对 launcher/PID/创建时间/Job与监听归属；只有对应 owned 服务才执行 stop，再确认其整个任务树退出、目标端口释放。示例命令仅由主会话在生产根执行：

   ```powershell
   $releaseRoot = 'D:/03-项目/01-正式项目/智慧圆屏'
   $releasePython = Join-Path $releaseRoot '.venv/Scripts/python.exe'
   & $releasePython -B -X utf8 (Join-Path $releaseRoot 'scripts/development/launcher/control.py') status
   & $releasePython -B -X utf8 (Join-Path $releaseRoot 'scripts/development/launcher/control.py') stop
   ```

3. **一致备份**：在已证实停止后，复制**完整 Hy 引擎目录**（Chroma/Kuzu、新 `semantic.sqlite3`、管理账本、scope/state stamp 与相关侧文件）、平台 source/round 账本、校园调用审计及其存在的 WAL/SHM、相关人工配置/偏好/角色/声音档案与旧证明。保留路径相对关系，检查前后逐文件大小/SHA-256；来源和审计必须同一停机边界，不能只备份向量库或只复制主 sqlite 文件。备份包含私有数据/密钥，不进Git；运行中变化或仍有owner则中止这一步定位，不继续复制成“成功”。
4. **逐项应用**：先合入已审代码和同 tree 前端产物，校验下载到 AC 的固定 ONNX 大小/摘要后，由部署方明确复制到正式 `local/runtime/models/smart-turn-v3.2/`；已有不同文件不盲覆盖。侧车显式使用正式 Cosy Python，不将工作树资源当永久依赖。保留校园模型精确名、原声音/角色和 buffered，SmartTurn 先 off/shadow。按已验证迁移方案开启语义能力，使用最终代码实际SDK验证产生的新协议2证明；不复制历史字典或仅改摘要来假称验证。
5. **重开原入口**：若使用新进程环境开关，必须退出旧launcher，再从携带这些环境变量的新进程执行 `启动智慧圆屏.cmd`；仅向旧launcher发送 start 不会更新其环境。日用启动仍走根唯一入口，不直接起另一套服务。候选宿主与语音侧启用必须同时匹配，缺任一端降级并报告；自适应音频只作为本次受控实验单独选择，不顺带开启所有候选引擎。
6. **只读健康/层状态**：核对 owned 服务 ready、原端口/设备路由、校园/声音/角色标识和 provider策略；读取真实 Hy semantic/status 的 protocol2/mode/graph/epoch、Runtime门、L6/L7的保存/覆盖/隔离状态和单任务回执，检查前端产物身份。查看不得懒启动、跑普通search或后台生成。技术检查不自动向个人库发合成对话，不发未经本轮调度的学校请求。通过后才安排所有者真实文字/圆屏与听感/插话验收。
7. **受控回退**：停止同一 owned 服务，保全失败时当前状态和新日志/审计。优先按已经过“pro→semantic→pro”实测的**新代码保守模式**恢复：语义能力关闭、buffered、候选关闭、对应当前代码的 pro 证明，按原入口重开；新 pro 保留图/任务并在后续写入时隔离保留图式。此测试不等于旧 `a93258e` 写入器具备相同失效能力。真正旧代码/旧前端撤回须另验其对已新增图/任务/当前source与后续写入的兼容和隔离，未证明时不把旧代码回退列为可自动执行。所有新增/现有个人来源、费用unknown、派生与任务证据保留，不删除Kuzu/任务账本、不重建索引、不覆盖个人数据库。若代码无法兼容当前状态或已有新对话，保留当前完整检查点并报告精确阻塞，不能拿写前备份覆盖新增记录来换取“恢复成功”。数据恢复属另行精确授权范围。

操作交付追溯表最后由主会话填写实际停止/备份/应用/健康/回退或接受时间与证据摘要，以及“任务→提交→AI验收→main合入提交→会话ID”。本计划未执行任何生产生命周期；AD临时窗口恢复原版不等于新版发布。

## 追加组合检查点：真实 SDK、RPC 与上线阻断项

本批新增接力：AE `0a9531b7924fa24d540295a2f51cc6cbff729c48` → AI `76843487`；AH 离线发布记录 `1c272770e101fb49acb4a189cfe90c11ecffb25c` → AI `d73a2f89`。此前真实校园 harness/收据、稳定 source 身份、3.10 RPC/null/多通道等接力已经进入同一组合树；历史分组测试数量不相加作为最终覆盖数。

AI 实际修复 ManagedMemoryMethod 包装层缺少显式 `configure_background_writes` / `candidate_snapshot` / `candidate_validate` 委托导致底层能力不可达的问题；不增加任意属性穿透。Runtime 初始化及配置变更同步同一写门，失败保持关闭；候选读取不写来源、不跑普通 recall。正式 prepare 在内存暂存有界/短期的本轮身份、查询/上下文/完整来源哈希，确认在同一 Runtime 锁内新鲜复核并同步领取；命令、反馈、跟进、预算回执以及内容/来源/策略变化均不能直接采用候选。没有把“最近一轮”当当前线程实际 Memory 回执。

`test_voice_proposal_sdk_rpc.py` 的三个场景在实际固定 SDK、真实 Managed/Runtime、实际 AF 网关/独立合成免费账本、正式五种候选路由与原 prepare/cancel 路由、既有鉴权、所有者既有 Python3.10 子进程 RPC 上 **3 passed / 17.58秒**。供应商只用随机回环 HTTP 合成响应，学校调用0；projection 场景画像1＋事实4＋意图1六项全部进入实际模型载荷，来源/上下文一致可 adopted，包含历史链的正式上下文差异及 Runtime 策略变化均 miss。分阶段证明正式 prepare 前来源文件无变化、journal 事件空、SDK 模型计数和语义任务未增加；没有发助手完成或假装设备已播放。该组仍使用合成角色/标准消息，**不是实际 ASR 接线已通过**。

上线前仍须处理或取得对应证据：

- **真实 L2 来源**：AB 校园收据 `new_l2_semantic_provenance_complete=false` 是质量/派生管理阻断项。新 L2 从四个旧 seed 概括习惯却只挂 future 事件，不算本轮用户直接事实；不能靠文档脚注或补齐可读 ID 假装语义来源完整。AB 正在离线复现并处理来源依赖/未证实内容隔离。最终需复核旧来源纠错/删除及后续 L6 不会重新引入该概括；不追加学校请求、不批改个人库。
- **共享模型排队**：AI `test_voice_gateway_background_contention.py` 实际网关/独立账本、受控函数供应商替身复现：后台持锁160ms时正式回答167.655ms后才进入供应商，本次顺序hy→hy→answer；候选排队可取消（0.077ms本样本），不等于取消已在飞背景。旧 model_ttft 从拿锁后计，掩盖该等待。AF 已由主会话授权实现有界准入优先级，保留上游并发1和原预算/unknown/关闭ACK；此处是修复前对照，最终须重跑实际HTTP与SDK后台组合。不能以reader耗时推断最终回答不受影响。
- **实际 ASR 当前消息**：固定上游 ASR 会把包含content/language/emotion/speaker的JSON字符串送入当前用户消息，正式记忆 prepare 另提取content。候选协议当前单一query同时用于记忆和追加模型当前消息，不能同时绑定两份实际载荷。需分别冻结/复核记忆查询与模型当前消息；不得剥掉正式元数据或弱化上下文以制造命中。原角色、时间、声纹及联网工具约束仍按最终真实模型载荷比较；已配工具时不能抢答绕过搜索。SmartTurn off/shadow 不作为禁用原ASR候选的理由。
- **冷语义读取**：HTTP/provider已禁止懒装配，但现有 HyAdministration.semantic 仍可能经 sdk_call 懒启动未初始化的自定义引擎；正式装配总是ready不抹掉该接口边界。须底层明确拒绝cold读取并给实际对象测试。

AH离线发布候选已由AI只读逐文件重算：45文件、1,835,506字节，规范树SHA-256=`278ed5f109b2ffcce9246e5f26719dd6add19d94f9b5e7d28bcee4dc48a9a1ef`，manifest=`fff8f17b610f6bb55cd83f518a831eb73a9359c6f89332ace572c0caa774df53`；与当前前端tree及共享assets tree匹配，关键构建输入与7张截图摘要均匹配。未在AI安装/复制依赖、未重建或切换生产dist，浏览器视觉结果沿AH精确同产物证据，不能替代组合HTTP/日用。

AG `flow_trtexec.py` 静态审查及CPU契约/source绑定组 **18 passed / 0.83秒**，未导入GPU模型。固定资源/参数/10组数值计划、逐阶段Job 6GiB/2CPU与墙钟限制存在；但execute仅窗口ID非空，尚未核验AD v2 WDDM项目模型窗口和精确桌面基线，不能阻止未知owner混入；当前不接受执行准入。另需将全流程22分钟/唯一自有外层Job、固定解释器/依赖与源码摘要绑定到窗口接力。工作区大小是采样限制、GPU显存是观察阈值，均不冒充硬物理独占。没有自动停服务、下载、混装、重试或删除外部结果；此实验不阻塞其他已验方向。

本检查点另实际运行：旧pro→semantic→pro及旧semantic source别名重开 **2 passed / 35.44秒**；公共Runtime/实际SDK/五路由/宿主/3.10 RPC/启动/文档机制组 **158 passed、7 skipped / 33.78秒**（7项缺显式冻结宿主ref，未当通过）。补入确切AF `0ea551a90c7ef04863dc887c8295627059edfe1d` 后，3.10 RPC全组和新增管理uncertain撤销测试 **69 passed / 10.77秒、无skip**；这两组有交集，不相加。补充Runtime管理尝试在来源归档前递增候选版本，因此SDK正文未变但平台可能running/uncertain时仍会撤销旧候选，不让原生digest遗漏来源管理隔离。

随后冻结AI代码提交 `2eea38e2b2f12cd3f610eb0fbf9963dbbe2b2c35`，工作树clean，并将 `LONGMEMORY_TEST_VOICE_HOST_REF` 指向该精确提交重新归档宿主源码；同一公共组合组 **166 passed / 41.91秒、无skip**。SDK解释器只读使用V工作树的所有者已安装环境，3.10子进程只读使用原小智环境，导入实现/脚本来自AI工作树，不下载、不复制环境/依赖、不触及日用端口。另方法层全组 **467 passed / 50 skipped / 10.47秒**：50项是旧探针/截断对照仅认本树`local/runtime/hy-memory`路径、本树未装SDK源码所致，不算通过；不为抹掉skip建立联接或复制SDK。该全组与166组有交集，均不是尚待AB/AF新修复的最终release证明。

后续公共临界区审查修正：候选CPU编码移出Runtime锁，保留原网关编码锁；编码完非阻塞重取Runtime锁，再核对原Runtime修订、使用门、网关/编码器实例，失效或忙直接回退。不能持Runtime锁等待编码器而让正式prepare被可选候选拖住。新增受控阻塞编码测试确认前台可取锁，配置变化后迟到向量不进入引擎快照；首轮失败是合成模型服务替身遗漏status()，补齐其契约后整组 **81 passed / 29.38秒**（公共门＋实际SDK/RPC＋真实AF宿主），没有改系统实现来迁就测试。

AI也只读核对原校园 `raw-models/model-{3,6,10,14}-{request,response}.json`，不复制正文/库或追加学校调用：S1与协调请求均确含四个seed完整原文；两个响应中的61字L2正文SHA-256均为`df816339ced67c876fedad75b20f0a2065d53d7916dc8eb22ce1b735ab73f173`，与公开收据一致。基于该实际捕获正文、公开条目ID/meta和当前AI HyMemoryMethod实代码，回放桥/召回投影＋管理叠加替身，normal正文原样返回且来源仅future；overlay只查询该新L2 ID，未查询旧seed ID，即使旧seed被标为blocked也不能由现路径自动传递到新L2。这是当前缺口的具体反例，尚不是完整SDK纠错/删除重放；AB仍负责持久依赖/来源隔离修复与原SDK离线回归。该手工探针首轮因未指定src而解析到主环境editable安装，在对象构造前失败；重跑明确将AI src置首并断言import路径。探针未访问日用服务、个人库或学校，未在Git保存原捕获正文。

## AF前台优先准入接入（待AB实际后台接线）

主会话交付AF `3308a8251706da0cb0289ed9ec2cb0dccfa02b87`，AI核对调度/网关/候选ACK/测试后无冲突接入为 `1eb3ea0c`。单上游槽继续沿原锁、预算phase、真实owned传输和unknown；显式background仅允许hy，新同authority路由`/hy-background/v1`，默认/未知标签保持required_hy；模型body不取得调度权。优先次序answer→required_hy→candidate→background，同级有界FIFO，排队不reserve。候选抢占必须匹配实际request_id/owned退出/ledger关闭回执，ACK前不得归还槽；错误ACK隔离并阻止新provider请求。正式或后台在飞请求不被此抢占取消。

`local_settings('hy',work_class='background')` 和 `complete('hy',body,work_class='background')` 已可用；Bearer保护的`GET /hy-background/v1/admission`只给空闲建议，不持lease、不reserve，不授权运行SDK。AB须在任务标running/进入原子evolve之前先查建议，忙仍pending；实际内部LLM请求仍须走background路由并由SDKBudget可信同authority白名单认领，不能全局改/hy类别。路由属当前进程策略，不改变持久模型/来源身份。该SDK侧接力尚未交付，AI没有擅改AB worker/semantic文件或生产proof。

AI在组合树实跑准入、原候选、流式回答与宿主 **99 passed / 6.56秒**，包括AF真实随机回环HTTP竞争/延迟ACK/错ACK隔离/关停唤醒场景。AI原共享锁反例现按显式background重跑，保留在飞后台160ms受控屏障，实际顺序hy→answer→hy；本样本正式请求到provider168.450ms、独立model_queue166.600ms、拿槽后过滤首文本0.110ms。排队候选取消0.077ms且无预留；总实际3次原预算请求、unknown0。固定sleep改为等answer真正入队后使用perf_counter保持屏障，避免将sleep参数当Windows实际时长。此处供应商为受控函数替身；真实HTTP顺序另由AF专属测试覆盖，不声称已完成实际SDK后台组合、学校性能或用户停说→答声提速。

冻结AI `c2a6b501` 后，以该精确HEAD归档AF宿主，重跑公共Runtime、真实SDK、多通道正式HTTP/3.10 RPC、候选/准入/启动与文档机制组合：**179 passed / 43.25秒、无skip**。本次覆盖实际投影匹配可采用、历史/策略变化回退和各级取消/关闭，尚未覆盖AB待交付的背景任务原子操作前建议查询/内部路由，不用准入12项代替SDK真实标记已接线。

实际语音桥的下一项仍为独立冻结记忆query和ASR JSON模型当前消息；它应位于语音表达/联网编排的最终模型输入边界。搜索配置走函数工具接口时，当前不执行工具的候选必须miss；动态时间与声纹不能冻结/省略来制造命中。需分别验可采用的无工具/上下文稳定场景与正确回退场景，不能据标准RPC成功宣称当前日用搜索配置下已有候选命中。只读检查launcher/setup均沿os.environ.copy继承本次进程参数，仍需新启动器生命周期才能变更已运行服务环境；本次未操作该生命周期。

## 托管包装边界与AD起音诊断追加

主会话已将memory query/ASR JSON消息协议演进交AE/AF，cold semantic拒绝懒启动交AB；AI不重复编辑这些所属实现。补充 `test_managed_memory_proposals.py` 验真实公共ManagedMemoryMethod：另一线程持锁时候选snapshot/validate必须在解锁前返回busy；关闭后拒绝三种显式代理；缺能力不借recall、observe、wait_until_ready、任意sdk_call或来源journal操作补齐；read_status/valid=false及写门失败原样保留，不隐式重试；旧引擎无后台门保持兼容。新增边界与既有backend/Runtime组 **62 passed / 1.40秒**，未发现需要修改包装器实现的新问题。

AD `b88fc80597d773005ba5f5bf3644b8061316d807` 记录经审查接入为AI `20dbe2c1`。AI只读实算 `cpu-onset-diagnostic.json` SHA-256=`8857a77fd7358e8502682a6f9b20d1430aacda9f0ed4002cb245e58271ef1d7c` 及分析源=`c216701f0e1626fe01df31389749e0d44c0c2cf46518cd458b9dc69688436dd2`，与交付一致；没有重写原报告/诊断、载GPU、重采样、裁PCM或操作设备。

原AD表中的首能量帧数值均为**包可用时刻**。计入前面60ms帧按FIFO依序播放，按每条曲线先递推`start[i]=max(arrival[i],start[i-1]+60ms)`再加帧内标记并分别取中位数，200门估计能量起点为：

| 输入 | buffered ms | adaptive ms |
|---|---:|---:|
| 多句 | 2106.112 | 1963.010 |
| 长句 | 2242.531 | 1879.855 |

此估计假定先前队列空、额外设备预缓冲/传输/声卡延迟0，不包含ASR/记忆/LLM、语言学有效词或实际听觉确认。原1.586/1.515秒不能改称adaptive播放首声，也不能强行相加独立中位数。原生严格近零前缀仅8.667ms，保留80–120ms保护后可证裁剪收益0；240–560ms低能量开头不能按200门一刀删掉，弱中文起音应保留。本批不实现裁剪、不为此追加GPU窗口。n=3仍不报P95收益；真实连续性、声音听感及已有效发声后的打断/残音仍待所有者，buffered默认不变。

## 冻结实际模型当前消息输入协议（公共校验先行）

主会话冻结外层version1、输入协议2的兼容演进。snapshot仍只收query作为记忆查询；start/confirm必须成对新增`input_protocol:2`及完整`model_user_message`，历史messages不含当前user，由AF宿主追加该真实字符串。纯文本旧格式不带二者并沿query=currentuser兼容，新语音桥一律显式2，不因JSON难匹配自动降级。当前消息不解释/重组ASR JSON，全文参与候选/正式比较，query仍单独参与记忆/来源校验；工具、时间、角色、声纹变化均应miss。

AI仅改公共 `voice_proposal_contract.py` 和正式HTTP契约测试：两字段缺任一个、protocol为1/3/bool、空白/非字符串/无效UTF-8均拒绝，snapshot/cancel/close不能夹带新字段。模型当前消息加历史文本总量≤32000字符，query仍≤16000字符，请求体仍≤192KiB；没有额外模型额度。旧请求和响应不变。实际鉴权HTTP验证v2字段原样送宿主、无效组合在调用宿主前400拒绝。契约/包装/Runtime组合 **78 passed / 0.44秒**。这时AF/AE尚未交付v2实现，不把替身分派当真实ASR采用已过；等待精确提交后组合，不直接重复其文件。

后续精确接力：AB来源保护`92d40492658d0f972435bc73d218e1f683bba649`→AI`167efac5`，AF双输入宿主`06a332baae5416fcdbad2790dc71c162152e5da2`→AI`f1a09481`，AC所有者下载入口`4c2fbd31195d7e84db0ff9615002106b141d9ccd`→AI`f4681e57`。公共校验额外对齐AF原文本上限：model_user_message自身≤16000字符，模型当前消息与历史合计≤32000；未扩大原额度。AF70项宿主＋公共HTTP＋AC离线下载入口测试 **146 passed / 13.33秒**；此后新增自身上限断言及真实SDK/v2正式HTTP三场景，后者与契约组 **49 passed / 34.52秒**：完整raw ASR消息原样进入模型、元数据仅变emotion即miss、tools_required在预请求前miss且模型调用0。Python3.10子进程旧协议仍通过，新协议真实桥仍待AE交付，不能据本组宣称实际ASR回调/播放已经接通。

AB实际捕获反例的完整SDK离线回放和单元门 **10 passed / 73.13秒**，包含原源码缺陷对照、guarded/旧库upgrade及纠错/删除后召回/候选/后续SDK提取不复活、重开后仍隔离；外部HTTP0。新`provenance.sqlite3`已在HyState.ready()登记为状态必需文件，完整检查点须连同其SQLite伴随文件保留。但AI另用实际SDK projection合成库核验发现profile/proactive正式和候选均没有“语义来源未证实”标识，已交主会话转AB；单纯可读来源meta/当前画像/未来意图标签不能代替来源完整性。新L2分页有provenance字段，现前端未消费其细分状态，需AH接力后重新绑定前端产物。

AI受控SQLite成本测量（合成Store、不载SDK/模型）：begin_add在1000节点打开3000连接、279.404ms；10000节点打开30000连接、2827.577ms。不是生产性能或P95。AB负责同ledger/audit/retired批读和同规模对照；正式网页ChatBackend.run仍同步prepare_user，因此本轮不能把此新增扫描当轻量。圆屏prepare使用defer_slow_observation=true，但既有后台完整observe仍保守持Runtime锁，不能借模型准入优先级掩盖该串行边界。网页改为延后提取不是来源门最小修复：会改变当前轮可检索内容、模型失败/取消后的提取时机；应先批读并量化新增成本，若改网页须独立验证原话持久化/失败/取消/重开，不仅切参数。未放宽来源安全或提前改写现有网页契约。

当前日用适用性已只读核实：保存首选pipeline/realtime、搜索configured=true；实际正式launch_with_memory进程命令也为realtime，未输出命令全文/密钥，未连接日用端口。当前web_response函数工具和精确实时时间路径下，此纯无工具候选必miss，不能静默关搜索/冻结日期来假称生效，也不应默认打开必废弃的请求。发布时保持候选双端关闭；无工具可采用只作为支持边界证明，待另有正当完整工具/时间载荷方案才讨论当前日用实效，其余来源/调度/TTS可独立验收。

未来模型下载只提供所有者入口 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/development/xiaozhi/Download-SmartTurn.ps1`；固定官方revision/大小/SHA、断点临时文件保留、正式文件仅校验不覆盖。所有者本次已完成下载校验，无需重跑；AI未执行该入口或联网。正式模型目的路径仍为`local/runtime/models/smart-turn-v3.2/smart-turn-v3.2-cpu.onnx`，只有正式部署方核验后复制已有文件，不把工作树当永久运行资源。
