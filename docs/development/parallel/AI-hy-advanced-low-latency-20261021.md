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

## 部署/回退计划记录（由末尾执行清单补全，不在AI执行）

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

## 实际后台准入与可信日用装配

AB背景路由`afd6b7d15dadeebc70623c1e2f510ec4ae963581`→AI`692ddde6`；冷语义读取`48a19305a334a9346b643d96258daeade316f467`→AI`f87ebc74`。AI审查同authority精确background别名、ContextVar跨原生线程的受控作用域、task running之前建议查询及原始请求预算；没有把所有Hy请求降级。cold真实对象/管理入口/忙与关闭组合 **40 passed / 0.42秒**，验证不触发factory/SQLite/子进程/SDK导入，不仅是外层HTTP peek。

AI公共bootstrap在owned网关启动后，仅随已验语义模式设置运行时`background_priority_enabled=true`；pro模式false，人工settings中此标记必须不存在或false。llm/embedding仍以原`/hy/v1`托管端点建立，只有AB的后台scope改写LLM请求，稳定provider/source/settings身份不变。公共部署/装配、AB单位与实际SDK路由组 **30 passed / 13.19秒**。没有读取或修改生产配置值或重签proof。

新增`test_hy_background_gateway_combination.py` **1 passed / 7.26秒**：真实SDK/Kuzu/Chroma/Runtime、真实自有ModelGateway及原单槽/合成独立免费账本、随机回环HTTP供应商替身。实际原生evolve在模型忙时保持pending、仅查询建议而不预留；候选排队取消不占新额度；在飞后台结束后正式voice SSE先完成，再运行实际原生evolve并观测background类别；后续实际SDK add仍为required_hy，原生自动evolve再沿background。无新增学校请求、GPU或个人数据。SDK/HTTP组合未以原生reader耗时代替整轮延迟，也不取消在飞背景。

主会话决定本轮保持网页同步observe行为，只修账本批读并量化实际prepare/recall新增成本。网页异步队列仅为有明确行为变化的后续候选，未实现，不在本轮为它改提取/取消/最终写入语义。

生产交接精确路径已由主会话白名单提供，AI不读取其私有值：部署描述`local/config/hy-memory/deployment.json`中的python为`local/worktrees/v-hy-memory-20261019/local/runtime/hy-memory/.venv/Scripts/python.exe`；state_directory=`data/memory/hy-campus-daily-20261019`；source_path=`data/databases/hy-campus-sources-20261019.sqlite3`；调用审计=`data/databases/hy-campus-calls-20261019.sqlite3`。现行sdk_version=2.0.3、embedding_dimensions=512、include_profile=true、model_mode=disabled；托管真实模型由managed_gateway/network_authorized及现有模型档案装配，不能改成不存在的ultra模型枚举。开启字段是semantic_layers_enabled，运行期background标记由可信bootstrap提供。最终协议2 proof须由融合源码实际SDK回归产生，旧4字段background-disabled证明不能只改hash/字段冒充验收。完整引擎检查点须包括sdk目录、hy-state.json、engine.owner、scope/stamp、management.sqlite3、semantic.sqlite3、provenance.sqlite3及所有现存WAL/SHM/其他伴随文件；来源/调用审计与人工配置同时按停机边界保全。最终可执行命令及新前端产物将在剩余门通过后固定，不执行本节生产操作。

## 最后来源、桥接、加速与前端接力

精确接入AE `0ee9e0aa9c5e792dbf72a17c8e99041f80e3d128`→`a13ac040`、`5501aa22425804a6f66765fa89ad012537d20187`→`ac540d32`、`92eedb0bf18440273db450faa448743cb659757f`→`cd32baaf`；AH `66e76b2f`→`f16668f1`、`54ae8a40`→`70178ef5`、`86c159c9`→`f34c059c`；AB `118cc996238a238574bf12ccc0129c9b8e9a7b13`→`2b8e39ca`；AG `e4dc45cd70b377d93e20f6d20942609d4f5dac84`→`3e77ef50`，均无冲突。

AE完整有效输入、连接状态与RPC模块组在冻结`70178ef5`上实际 **156 passed / 58.44秒、无skip**；包含七个真实SDK/正式HTTP/Python3.10组合场景。仅证明已有输入/RPC边界；生产`voice_asr_prefetch._Ticket`尚无候选proof输出/事件回调，`launch_with_memory.py`尚未安装候选RPC桥，`voice_latency._ObservedLLM._call`也尚无最终采用逻辑。这是待实现链路，不是仅缺实机测试。AI未编辑这些AE文件，已向主会话给出`baseline_asr_provisional/continued/confirmed`、`start_effective/confirm_effective`与最终输入捕获的接力边界；后续AE独立实现，不把默认关闭改写成方向已完成。

AG新回执门CPU测试组 **90 passed / 2.16秒**：已修非空ID不足，要求主会话新签的限时AG窗口、同checkout/output/清洁commit/绑定摘要、WDDM精确进程上下文、单外层Job与子进程继承、每次容量/导出/引擎前后复核和仅回收自有Job。旧AD窗口已关闭且显式拒绝复用。没有加载模型、查询/运行GPU、停止日用；驱动资源、真实引擎和数值十样本仍待新窗口，不默认启用，也不阻塞本轮记忆/调度主链。

AI在最终来源批读源码独立执行`ab_hy_provenance_cost.py`，新忽略目录`data/test-tmp/ai-final-provenance-cost-20261021-01/`。1000节点同规模三次中位数旧287.388ms→新6.655ms，10000节点旧2788.949ms→新48.935ms；SQLite连接3000/30000→1，逐组断言旧依赖集合全部保留且只增`legacy:unverified`屏障。范围仅合成Store的`begin_add`，不载SDK、模型或网络，不能宣称正式prepare/recall或用户整轮提速；真实SDK的额外分段成本由冻结组断言与diagnostics另验。

AH最终发布只允许`ah-release-provenance-54ae8a40-20261021/dist/`。AI只读逐文件重新计算45文件、1,838,948字节、tree SHA-256=`c5b2779d2b63980b9183561467ac423e30012dbf3a38d57216d0c28b86bb9ac5`、manifest SHA-256=`8760f1c25b01a876394af413b58734d479b021b4404fa7771b0ede6bfa3201eb`；融合前端tree=`85c8bf6945a3fea0b6f2bdb3da3546b0873a09ec`与共享assets tree=`3cc3fce0066fb30dcea0ac15e383fbde1a491929`精确匹配。五项源码输入、八张当前截图、类型/构建日志摘要均一致；dist与本次L0/L7浏览器已测目录逐文件相同。旧`70cad5b`/`66e76b2f`发布候选已失效，不混用。264引用和固定隐私扫描0发现为AH原验收，本次不执行其脚本或重建依赖。此处不部署、不把截图当真实后端验收。

## 协议2离线证明入口

扩展既有`tests/fixtures/hy_management_receipt.py`，保留旧背景关闭模式不变；新`--managed-semantic`与旧`--reviewed-semantic-background-writes-disabled`互斥。要求显式既有SDK3.12.13/2.0.3、语音3.10.20、AB原捕获目录、完整HEAD、清洁源码、全新ignored证据目录。固定25个测试入口覆盖旧管理/逐层RPC、真实原生归纳与只读意图、捕获纠错/删除后不复活、pro重开/rollback、真实后台与正式模型竞争、正式HTTP/3.10有效输入、冷/锁/来源门；独立BGE性能测试不属于此proof范围，不借skip放行。

进程沿原Windows Job先归属再放行，全部新数据/环境/临时文件隔离；无私有环境、代理、学校调用、GPU或日用端口。JUnit须零fail/error/skip且有case，并包含固定关键真实场景；前后HEAD/tree/源码、管理原语、SDK与语音解释器摘要一致才生成七字段协议2 `management-verification.json`及外围`receipt.json`、JUnit和原始pytest日志。新增入口门控与旧兼容组 **38 passed / 0.37秒**，这些模拟测试不替代真实冻结运行。

proof实际匹配SDK版本和管理原语内容摘要，不绑定工作树路径或HEAD；外围receipt绑定完整源码身份。主会话仅当融合后的源码、管理原语和SDK解释器身份与此实跑回执一致，才可把同一候选proof复制到正式配置；同一提交快进到main且字节不变无需仅因路径变化再跑。若业务源码变化须重审受影响验证；不可手改旧proof字段/摘要。正式ASR安装桥后续接力不属于本次候选链完成证明。

首次冻结`ee03aec75c2d6788fb67fd52043385712ef5b18f`运行 **210 passed / 9 failed / 373.16秒，无skip**，工具正确拒绝签发，失败回执与JUnit/log完整保留在`data/test-tmp/ai-managed-proof-ee03aec7-20261021-01/`。九项均在生命周期夹具创建SharedBudget深层SQLite路径失败，尚未进入目标业务断言；其基目录嵌套在较长回执名下，预算文件路径255字符，journal再加后缀。短路径同名SQLite创建复核成功。修复仅把受管模式的pytest目录设为本工作树`data/test-tmp/mr-<随机8hex>/`并写入receipt，仍排他、ignored、不联接、不清理他人目录；不改预算实现、夹具历史部署相对路径、用例或门槛。旧模式路径及兼容契约不变；失败证据不覆写。修复后重新冻结完整入口，不把210项和九项补测拼成伪造成功回执。

短路径下工具38项＋原失败生命周期/可信bootstrap九项 **47 passed / 58.82秒，1 deselected**；仅未选入另需明确BGE资源的独立CPU性能测试。此处定向验证工具路径修复，不作为协议2成功回执。主会话已安排AE在另一隔离树基于ee03继续真实ASR适配实现，默认关闭且不改当前冻结源；本核心proof不混入其未验代码。

## 由主会话执行的精确交接清单

以下只是可审查操作说明，AI未在生产执行。所有步骤在主项目`D:/03-项目/01-正式项目/智慧圆屏`，由主会话先确认服务/端口/Job归属；不在隔离工作树启动日用。

1. 登记当前main、目标融合提交、生产SDK解释器SHA-256、当前配置/角色/声音身份和运行开关。正式Python固定为`local/worktrees/v-hy-memory-20261019/local/runtime/hy-memory/.venv/Scripts/python.exe`、3.12.13、SDK2.0.3；不移动解释器，不安装依赖。
2. 使用现有入口退出旧启动器：React按钮“停止服务并退出面板”→确认“停止并退出”，等`shutdown_complete=true`并复核owned子进程和端口释放。等价既有接口是从`data/control/launcher-web.json`读取`origin/token`，核对`control_token_digest`与当前`launcher-control.json`令牌摘要及所属实例后，对同origin的`POST /api/launcher/actions`发送`{"action":"shutdown"}`、Authorization Bearer；轮询`GET /api/launcher/status`的`shutdown_complete`。不在日志打印令牌。`control.py status/stop/start`只控制服务，**没有exit/shutdown命令**；单独stop不足以更新旧启动器环境，不能补造命令。
3. 新建不存在的`local/archive/hy-advanced-release/<UTC时间-随机ID>/`。在同一已停止边界逐文件复制并核验大小/SHA-256：完整`data/memory/hy-campus-daily-20261019/`（含sdk/Chroma/Kuzu、hy-state.json、engine.owner、management-scope/stamp、management.sqlite3、semantic.sqlite3、provenance.sqlite3及所有实际侧文件）；`data/databases/hy-campus-sources-20261019.sqlite3`、`data/databases/hy-campus-calls-20261019.sqlite3`及各自所有现存WAL/SHM/其他伴随文件；`local/config/`完整人工配置/偏好/角色/声音/旧proof；`web/react-chat/dist/`当前前端和本轮实际启动使用的会话库/附属账本。平台round回执沿同source journal保存（`bootstrap.py`的SQLitePlatformRounds），不能另猜一个round文件名。若实际启动会话库不是公开默认`data/databases/xiaozhi-demo-v1.db`，由主会话从正式实例参数核精确路径后纳入，不在AI读取私有参数或漏备份。清单/摘要保存在私有检查点，不提交Git；任何文件仍变动先查owner，不声称一致。
4. 审查、整合并推送目标源码后，复核业务源码/RPC/前端tree与冻结回执相同。生产前端目录为`web/react-chat/dist/`，从AH最终45文件dist暂存校验后替换；旧目录已完整归档。校验manifest/tree及逐文件清单后再启动，不把旧/新目录增量混拷，不使用两个失效候选。由主会话按文件清单执行；本AI不删除/移动生产目录。
5. `local/config/hy-memory/settings.json`仅按本目标设置`semantic_layers_enabled=true`；`model_mode=disabled`、sdk_version=2.0.3、embedding_dimensions=512、include_profile=true、原managed_gateway/network_authorized与原选模型维持。`management_writes_enabled`、`management_exclusive_profile`、`background_priority_enabled`必须不存在或false，由已验装配动态授权；不能直接写true绕过proof/bootstrap。身份计算排除语义/运行期开关，`deployment.json.settings_identity`及hy-state/source身份无需重签或SQL改写，正式重开`create=False`，路径缺失须报错不能建空库。
6. 主会话将冻结工具实际生成、七字段完整匹配的`management-verification.json`候选复制到`local/config/hy-memory/management-verification.json`，同时归档外围receipt/JUnit/log摘要与精确测试清单。当前管理原语摘要覆盖`worker.py/process_client.py/management_rpc.py/sdk_bridge.py/short_embedding_input.py/sdk_observation.py/observation.py/layer_data.py/semantic.py/candidate_snapshot.py/method.py/assembly.py/provenance.py/settings.py/background.py`，名称和规范化源码共同入hash；不能仅改旧proof摘要。外围receipt的实测HEAD不随后续纯文档提交改写。
7. 新PowerShell进程中固定本轮开关，再运行唯一根入口。下面命令仅供主会话执行，AI未运行：

   ```powershell
   $releaseRoot = 'D:/03-项目/01-正式项目/智慧圆屏'
   Set-Location -LiteralPath $releaseRoot
   $env:LONGMEMORY_PREEMPTIVE_ENABLED = '0'
   $env:LONGMEMORY_TURN_END_MODE = 'off'
   $env:LONGMEMORY_COSY_DELIVERY_MODE = 'buffered'
   & (Join-Path $releaseRoot '启动智慧圆屏.cmd')
   ```

   这里关闭的是已存在的3.12候选宿主；3.10生产候选桥尚未安装，**没有另一个已实现的环境开关可以冒称双端生效**，AE接续实现后再补其精确入口。本次禁止在宿主上另传`--enable-voice-preemptive`。实际搜索配置必miss，不发送无资格候选请求。
8. 受控声音试听可在另一次完整shutdown/新入口后仅改`LONGMEMORY_COSY_DELIVERY_MODE=adaptive`；沿原角色/声线，听感、有效开口后插话、残音和后继新轮另验，异常回buffered。SmartTurn最多另选shadow：正式`LONGMEMORY_TURN_END_MODEL=$releaseRoot/local/runtime/models/smart-turn-v3.2/smart-turn-v3.2-cpu.onnx`、`LONGMEMORY_TURN_END_PYTHON=$releaseRoot/local/runtime/CosyVoice/.venv/Scripts/python.exe`，模型8679182字节/SHA-256=`2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f`。所有者已下载，只由主会话核验后复制现有文件；不运行下载入口、不沿用AC工作树为永久路径。shadow不改变正式EOU；没有新的中文校准批准不设enabled。AG引擎保持默认关闭，另需新窗口与真实十样本证据。
9. 启动后先核owned ready/原设备路由、前端manifest、原模型/声音/角色、Hy protocol2/mode/graph/epoch与Runtime写用门、L0/L7来源标签及单任务回执；只读查看不代跑search、建任务或写合成个人记忆。真实两三轮文字/圆屏、保存重启后可检索、听感/打断由所有者进行。学校真实模型质量、长期L6归纳有效性不因本次禁网合成回归宣称通过。
10. 若需回退，先按同一owned shutdown保全失败时当前全量检查点。优先保留新代码，用`semantic_layers_enabled=false`、buffered、候选off及**与当前代码匹配、由旧模式入口真实生成的四字段pro proof**重开；该证明不是本次七字段proof的手工删字段版本。可用同工具`--reviewed-semantic-background-writes-disabled`（不带managed-semantic）单独生成，固定原管理/正式HTTP组；仅在确实准备pro回退时运行，不为重复数字复跑本轮。原图/任务/provenance均保留。不能把旧a932写入器或写前数据备份直接覆盖新增对话来声称无损回退；不兼容须报告具体阻塞，数据恢复另按精确范围授权。

主会话实际操作后补“AI任务→冻结提交/最终交付→AI验收→main合入/推送→停机检查点→实例健康→所有者体验→会话ID”追溯。本AI仅提交自己分支，不merge main、不推送、不执行生产配置/服务/个人库写入。

## 最终核心冻结验收与实际协议2候选

实测冻结HEAD=`f5906827d98ce4d2665d5e6b83b04ee1ebda58fa`，源码tree=`eba6d064fd90b39c3874107327b8d18c52f41dcb`，规范化Python业务源码摘要=`65260b66713243a2d3567901384ee5e19c2aee7e2f6dbf80dfda1dd877532a61`。完整固定入口 **219 passed / 429.82秒，failures=0/errors=0/skipped=0**，不与旧分组相加。旧管理/逐层读写、原生L6/只读L7、真实捕获对照及纠错/删除/升级后不复活、pro/semantic重开、实际后台准入及正式回答竞争、冷读取、来源批读、正式鉴权HTTP与3.10输入协议2均在同一运行覆盖；模型/网络均为隔离合成/既有捕获，无新学校调用、GPU、日用服务或个人库。不是远程CI结果。

成功证据唯一目录：`D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ai-integration-review-20261021/data/test-tmp/ai-managed-proof-f5906827-20261021-01/`。`receipt.json.test_paths`保存精确25个入口（18文件＋七个生命周期节点），JUnit实际219个case零skip；不能仅看旧管理两文件五项或本文摘要代替。工具读取SDK元数据Python3.12.13/SDK2.0.3、语音3.10.20，执行前后完整源码/管理原语/两个解释器字节相同才签发；没有手工编辑生成JSON或生产配置。

| 证据 | SHA-256 |
|---|---|
| management-verification.json（七字段协议2候选） | `83ef38351de8c6849a6e39d934cebc93932f95b9fb4f60a562329c835568d532` |
| receipt.json（含精确测试清单/短临时目录/源码绑定） | `31e22cfb2d1089635147ad0bd79cd6d374f110ba11a752f5a36fcb4dcf6261c1` |
| junit.xml | `bdb83b43055c9b6b4792143ba507669280723f71c9c91939bd81aac6040ab705` |
| pytest.log | `9c706c089057718176164d7090cd9fdd1086cc1a45b53ba9326ffc2f679f7321` |
| 当前15项管理原语（含文件名与规范化源码） | `562630a13eeda478674e85454df245de4a38554af52ecaa43f374fa16147720c` |
| 白名单既有SDK Python3.12.13解释器 | `560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e` |
| 既有小智Python3.10.20解释器 | `8ce49d96ecba2dfd13b3cc99b5d8a18f6c0ad82bacf0df2f5d17a3df6a9cd203` |

本候选可由主会话在已审融合代码快进到main、业务源码/管理原语/解释器及前端tree与上述证据一致后，按停机备份边界复制到正式`local/config/hy-memory/management-verification.json`；路径不参与proof匹配，不因工作树变生产根而重跑。文档收尾HEAD可以不同，但`receipt.source.head`必须保留实测f590；主会话复核`git diff f5906827..目标HEAD -- src scripts tests web`为空或逐项解释受影响变化。本轮收尾仅改本任务书、ADR与清单，不重新伪签原回执。若后续AE实际安装桥合入则属于新业务变化，另按影响验证，不能自动沿用本文“候选链已完成”的不存在结论。

以下为工具复现入口，**当前成功候选已生成，不为重复数字再执行**；以后代码变化确需重验时指定新清洁已审HEAD和全新目录，不覆盖本次成功/失败证据：

```powershell
$releaseRoot = 'D:/03-项目/01-正式项目/智慧圆屏'
$verifyRoot = Join-Path $releaseRoot 'local/worktrees/ai-integration-review-20261021'
$verifyPython = Join-Path $releaseRoot '.venv/Scripts/python.exe'
$verifyHead = (git -C $verifyRoot rev-parse HEAD).Trim()
$verifyArguments = @(
  '-I', '-B', '-X', 'utf8', (Join-Path $verifyRoot 'tests/fixtures/hy_management_receipt.py'),
  '--source-root', $verifyRoot, '--expected-head', $verifyHead, '--managed-semantic',
  '--sdk-python', (Join-Path $releaseRoot 'local/worktrees/v-hy-memory-20261019/local/runtime/hy-memory/.venv/Scripts/python.exe'),
  '--voice-python', (Join-Path $releaseRoot 'local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/.venv/Scripts/python.exe'),
  '--capture', (Join-Path $releaseRoot 'local/worktrees/ab-hy-l6-l7-20261021/data/test-tmp/AB-CAMPUS-L6L7-20261021-01'),
  '--output', (Join-Path $verifyRoot 'data/test-tmp/新建且不存在的验收目录')
)
& $verifyPython @verifyArguments
```

完整验收退出后才执行额外成本诊断，未与其并发争用SDK。新合成projection库、实际固定SDK/Kuzu/Chroma与Runtime、8维禁网模型替身、温进程，每种三次；记录`data/test-tmp/ai-final-prepare-cost-20261021-01/summary.json` SHA-256=`f1ff03ba40242e4832aa06832623ce6ae9a1a9bd021e1b213be013090dca6a37`，脚本SHA-256=`625d36d4414fce9ccc16751b763219041b5cb84a3062dfc83858562208adf313`，保存实测HEAD和每次分段原值：独立原生recall中位52.493ms；网页等价同步`Runtime.prepare_user`总102.002ms（observe50.405、recall52.631）；实际provenance begin_add2.641ms，已有节点11/13/15、ledger连接各1、audit0；圆屏`prepare_round_screen`延后路径55.744ms，断言准备阶段未触发新begin_add，随后只cancel不发助手完成。外部HTTP0。分段中位数不能直接相加；该诊断不含HTTP渲染/ASR/LLM/TTS，不是生产512维模型、before/after对照、P95或日用端到端收益，也不声称网页同步observe已异步化。

可供主会话放行的是以上已验证的记忆/来源保护、管理/后台准入、界面与保守语音配置技术门；部署与所有者真实体验仍由主会话执行。AE真实ASR安装/最终采用继续独立接力，当前搜索必miss且候选关闭；SmartTurn仅off/shadow、adaptive需听感验收，AG无新GPU窗口/十样本验证，不默认启用。不把这些未完成方向归为全部完成，不提前归档仍有任务的AE。

## 生产接力与CI追加发现：公共反馈热修

主会话报告core已ff到main并推送`28dc78ff`，按所有权停止旧实例后取得90文件/14,606,958字节完整检查点`local/archive/hy-advanced-release/20261020T214505Z-2c76f0c5/`，清单SHA-256=`6cad195a19c923d0cccf7405fdced1feaf99b6b99fbdd14a299719d9190319c7`；已复制真实proof、AH最终45文件dist和固定ONNX，settings仅开启semantic_layers_enabled，原模型身份/声线档案保持。新launcher52056创建UTC `2026-10-20T21:48:37.285837Z`、正式入口及API/TTS ready，候选0/SmartTurn off/Cosy buffered。上述是主会话操作证据，AI没有访问个人库、停止服务或改配置。CLI先前ready=false已由主会话确认是启动时间差，随后true，不记录为同实例状态矛盾。

初次语义status的epoch0/ready_epoch-1、task_counts空、graph_available=true/schema_state=isolated与代码默认一致：图存储可用，但本受控epoch尚无完整归纳回执；不证明没有任何旧图节点，也不据此推断迁移失败。唯有evolve完整完成且期间epoch未变才ready；隔离时L6不注入，L7仍只读过滤，不为健康外观自动enqueue/evolve个人库。主会话保留了该状态与原调用审计38 completed＋1 unknown，真实归纳/体验不据此验收。

GitHub Quality `39503121912` 在28dc后端收集失败，四项分别缺requests/numpy/PyYAML；AI只读主会话提供的公开合成CI日志。在隔离树以原锁console/dev闭包屏蔽其它已安装依赖，并模拟工作树外专属资源不存在，完整入口首次 **3538 passed / 14 failed / 177 skipped / 217.45秒**。这是受控缺包/资源边界复现，未重建干净环境、未安装/联网、未触生产；原始log/XML在`data/test-tmp/ci-minimal-20261021-01/`保留。资源声明和测试前提修复分开提交，不把原四项collection修好就称CI通过。

其中实际公共缺陷为`prepare_round_screen`把`feedback`字典当对象访问`.recorded`，候选宿主关闭也会在“你刚才记错了”等明确反馈路径报错。修复后仅当feedback为None才允许候选资格；跨session未记录和同session已记录的反馈均走原逻辑且不得采用已有候选。新增真实SDK/平台round/原反馈账本两场景先完成原轮、取得有效只读候选，再验证两种反馈结果及claim不调用候选；没有VoiceProposalHost/ASR安装，不发真实模型请求，不改个人库。

同时修正架构门的两个真实违规，未加白名单：Runtime不导入HyLayerDataBusy，使用中立方法契约MemoryReadBusyError，由Hy HTTP入口兼容两类异常并维持busy/503；应用候选宿主自行持有其异步清理语义，不导入具体Hy provider_transport，不编辑该方法传输模块。SDK十五项管理原语摘要仍为`562630a13eeda478674e85454df245de4a38554af52ecaa43f374fa16147720c`，现有proof的实际原语匹配不变；业务源码已变，不能声称原219已覆盖新修复。

新反馈SDK两项、候选宿主清理/正式HTTP/Hy层读取组 **120 passed / 14.77秒**；另公共架构、原平台反馈、请求外层计时与修正前提后的独立启动器组 **47 passed / 2.70秒**，不相加作为新完整覆盖数。生产文件热修与CI/dev/夹具修复独立提交，主会话可先审查部署已知坏路径；后续冻结提交上的实际HTTP/3.10输入回归另补，不修改旧proof文件或旧receipt.source.head。

公共热修已独立提交`89001d49110845ff7dd7f97ba5eb96075db3a07b`。随后按该精确提交归档宿主，实际SDK反馈、正式HTTP/候选RPC、原生记忆匹配和3.10完整消息组 **17 passed / 122.43秒、零skip**；JUnit=`data/test-tmp/hotfix-wire-01.xml`，SHA-256=`d61dffbd171b2c43322ebf8f40a1faec77902ac105dca85954066147eb9c0454`。未发现该热修新增阻断；原219仍只属于f590，不重签或改写其来源。主会话已独立审查并安排owned停机检查点部署，AI未触生产。

## CI夹具前提修正（与公共热修分开）

只改测试前提，不改业务断言或生产模块：启动器偏好现行版本7，旧测试仍断言6；validate_config已增加ws/http端口关键字，旧lambda不接受；setup明确核验已安装提供器，合成服务必须准备当前公共provider字节。脚本按真实同级目录独立加载，并保持各自control模块优先，不再依赖全套收集偶然留下的sys.path。计时夹具通过object.__new__跳过init，须显式补齐新增内存formal票据和现行prepared/feedback/receipt形状；原先锁顺序、耗时及正文不泄露断言保持。

父进程取消/超时/来源变化三项在child_process边界注入失败，不执行SDK，preflight仅需可指纹化的自有合成文件，不能借用本机SDK使CI意外依赖安装。它们改用两份独立当前HEAD源码快照，适应checkout默认浅检出；真正SDK双版本对照仍固定87a25e2/ae53f729、保留专属资源要求，不为CI另取历史或降为同版性能对照。加速模块的真实CPU torch对象替换/量化两项精确标识已有CPU torch要求，其余合成/Job测试照常执行，不引入torch dev依赖。

以上前提修正参与第二次完整受控CI运行 **3550 passed / 181 skipped / 229.82秒，零failure/error**，并通过实际backend_quality报告护栏；未ignore/deselect，requests/NumPy/YAML合成测试已执行。之后额外核出的仅当前HEAD快照变化再做真实无历史仓库的定向验证，不为它复跑全部3550或把前一次数字伪称新冻结全面证明。本机受控环境不是干净安装，更不是远端通过；远端仍需主会话合入push后的Quality结果。

夹具/前提修正独立提交`18f86eab47b15c3d141d0b4418d6ed1883598dfb`。从该提交只导出公开src/scripts/tests/pyproject到本树新合成Git仓库，核对只有一个commit且87a25e2/ae53f729对象不存在；导入源码断言属于该合成src。定向运行校园探针文件 **13 passed / 6个精确SDK资源skip / 10.83秒**，含三项父进程失败路径全部执行通过；原历史双版本SDK组保持缺资源跳过。实际报告护栏亦通过，JUnit在`data/test-tmp/ci-shallow-source-20261021-01/result.xml`。不把它冒充真实性能双版本对照，不联网fetch，也不初始化/改动主项目Git。

## CI/dev依赖与资源契约交付

依赖方案按主会话新增授权执行：requests==2.34.2用于既有无模型HTTP/超时边界，numpy==2.5.2用于PCM数值与固定上游控制流替身，PyYAML==6.0.3用于真实配置投影。三者全部来自原uv.lock确定版本/原来源/原制品；仅增加根项目dev引用和对应锁元数据，逐项验证43个外部包记录完全不变，`uv lock --offline --check --python <原主Python>`通过。替代的生产惰性import/标量替身/整模块skip均未采用；没有改AD生产模块、安装包、联网解析、升级锁版本或混装三套Python。console运行依赖/semantic extra不变，不引入torch等大依赖。

完整入口取消原requests文件ignore和installer单项deselect；原六模块/配置的yaml缺包例外撤销，入口强制导入console和这三项dev依赖。新增`scripts/ci/backend_resources.py`明确181个可缺资源/宿主能力用例，包括全部参数及固定原因；短向量函数49个长参数以显式有限输入组合构造完整ID，不前缀/模块通配、不从未来报告自动放行。真实SDK/3.10/原始捕获/CPU BGE、CPU torch两项、固定Otto素材、FFmpeg与两项具体symlink权限边界各自保留准确原因；新的用例/参数/不同原因/任何失败或collection error仍拒绝。资源护栏合成自测 **7项通过**，其中旧yaml例外、未知参数和错误资源原因必须失败。

第二次完整本地受控记录目录`data/test-tmp/ci-minimal-20261021-02/`：backend.log SHA-256=`fae8fcb0e49731b77bb64b9100dc3bf5d7191a3f05c49a35ec4d4c21ced3315e`；backend.xml=`79e9e145a0c167e5dcfb1d067e60527cfff8c63638c189c6dab2f0978e20c409`；boundary.json=`25f19acb581b576770ba87bddc788954ebff9dea4b883fd0d41afed52b2e569b`，列出从console/dev锁闭包计算的允许包和屏蔽模块；replay.py=`39410086dea915b0116af74061b899fd630a3d07df29f932415869c87142046f`。屏蔽仅在独立测试进程内，工作树外local资源只模拟不存在；不改安装目录/全局环境，不连接日用端口。第一轮14失败与初始化复现日志单独保留，未覆盖成成功。

此后src/语音/前端业务字节保持890热修一致；本CI/dev提交不包含AE适配或AH前端改动，不再触发业务原语变更。远端Quality39503121912的失败记录保留，新远端结果由主会话整合推送后核实，本地通过不能提前写成远端通过。

主会话后续报告890已按新owned检查点在本机热修：`local/archive/hy-advanced-release/20261020T222107Z-feedback-88534a/`共93文件/14,715,389字节，manifest SHA-256=`ec7ec0ea021a8016f27895fae13cc046caf46a29c5731af00e44782e7efa62be`。旧launcher及监听owner退出后，main本地ff到890；此时remote仍28dc，等待CI修复同批正常push。新launcher33512创建UTC `2026-10-20T22:23:03.424590+00`，control readytrue/TTS readywarmtrue；semantic仍预期初始isolated0/-1、无任务，调用审计仍38 completed＋1 unknown；配置/声线/前端字节未变。AI没有复读个人库或执行这些生产操作，不把主会话报告当自己测量。主src/xiaozhi业务摘要为`c62d3fb11c568a69580bf39daaf7e96f6beead9341c4d2edf42af2ba0cf50739`，与隔离热修源码一致；管理原语与原proof字节保持，旧219回执不修改。

## AH前端CI测试修正接入

按主会话明确授权审查并顺序接入AH `0d5d33f441ad5637d3ed76a8d966dae3b320c648`→AI `6ac7bbe1`，`09c2d912110c16a99d9458e9889621ead85d072f`→AI `d2e45a1edb29d96f3eb999d55c32ea165b9f48de`，无冲突。差异仅`MemoryApp.test.tsx`、`RoundDisplayApp.test.tsx`及AH记录；生产组件/配置、依赖锁、超时、原业务断言和零重试保持。作用是将角色查询限制到当前任务/条目/dialog/editor，等待query status=success而非不充分的fetchStatus=idle，并把会被后台轮询抢走的一次性响应改为按endpoint稳定响应及实际状态切换。没有增加skip或架构/测试白名单。

AI没有在本树安装/复制node_modules、重跑全量组件/browser或改生产dist，而是复核AH原始完整证据与其精确源码/工具/锁身份。`ci-full-after.json`实际63文件、348/348通过、pending/todo/failure均0，摘要=`903a13d100c6c7f1d850b71f63b7c7a31e4c06f7f0e38869fe824ec7c134a33d`；对应日志及typecheck/build日志均与交付回执一致。这是AH本地双worker实跑并由AI核验；修复前本地同样348通过，远端五项未完整复现，局部查询耗时/fixture竞态证据不能冒充远端已绿。

新的前端Git tree=`64c17c8e6e3f950fed66360632b748fda677c1d4`，与融合tree精确匹配；旧85c8…不能写成新源码身份。新发布绑定SHA-256=`e30c7d507b9edfbc2432e35b9eaca3a340b994c60410c11bab101dfe750b3f4c`，外围delivery-receipt SHA-256=`f546c4cf74dfea3fc41a9843dab5f67b2e1614669a47ca4a3d733e335f20ce01`，位于AH树`data/test-tmp/ah-release-ci-0d5d33f4-20261021/`。AI逐项重算完整45文件、1,838,948字节、264处本地资源引用与manifest导入键、五项构建输入、八张既有截图及交付证据文件摘要，均一致；不是执行交付的verify脚本后照抄结果。

新dist与此前AI核验的54ae8a40候选逐字节相同，规范运行产物tree仍=`c5b2779d2b63980b9183561467ac423e30012dbf3a38d57216d0c28b86bb9ac5`，manifest仍=`8760f1c25b01a876394af413b58734d479b021b4404fa7771b0ede6bfa3201eb`。主会话已报告生产部署该同摘要运行字节，因此本次测试修正不需替换生产UI；实际生产目录仍只由主会话操作，AI没有访问/变更它。Python业务/管理原语/proof均保持890热修边界，本次也没有接入AE或采用AG引擎；后续新远端Quality由主会话正常整合推送后验收。

## AE公开启动融合、AG失败取证接入（2026-10-21）

在主会话已合入并推送的 `49083dbd3eceedbf9f36f1fba91bc7b7703f0c89` 后，按明确授权审查AE四个提交并接入：576906ff→02f43719、f9f6d62c→443ea24e、e6450b55→d35f12d0、555c1858→f36f113d。融合实现6045fe0e，计数诊断3ed96bdc/d871437b；冻结实际业务源码 `d871437b9797c274b40a84171221a6af0027e10d`。本分支不merge/push、不操作日用服务、个人数据、GPU或设备。

公开 `launch_with_memory.py` 新增 `--enable-voice-preemptive` / `LONGMEMORY_VOICE_PREEMPTIVE_ENABLED=1`，默认关闭；只有pipeline/realtime组合允许，错误组合在加载厂商/私有配置前拒绝。宿主原 `LONGMEMORY_PREEMPTIVE_ENABLED` 仍独立、默认关闭。`_ObservedLLM`在连接初始化时自动绑定所属adapter的私有provider，不改共享实例。公开预览回调使用实际intent、provider方法和正式网页配置读取语义，不执行get_functions/工具、写历史或缓存旧时间；function_call即使空工具描述仍有direct_answer，搜索配置加functions能力同样在候选RPC前跳过。当前日用有搜索工具时预期零候选，不以关搜索换命中。

独立审查补上两处生命周期缺口：快捷寒暄可能不进入原生chat/LLM，因此adapter安装于快捷回复/计时/完成捕获外层，仍先于创建连接；完成捕获器安装后可选调用guard_history，撤权门必须先于助手捕获，覆盖无需provider的固定回复。原生TTS DTO、快捷寒暄及Cosy最终音频发送包装使用合成输出检查；新发声时即使sentence_id未换，旧排队/迟到帧仍丢弃，同批有效新包保留。保留原0.3秒确认界限；增加confirmation_deadline/confirmation_failed计数和显式阻塞确认测试，验证一次正式prepare、一次原provider回退及owned请求收尾。

首轮6045fe0e组合实际 **1 failed / 12 passed / 102.87s**：reset_worker在候选采用断言失败；当时缺少计数明细，原因未定位。原报告保留 `data/test-tmp/ai-proposal-real-sdk-6045fe0e-01.xml`，SHA-256=`7da497ab67714d948192b420e6e259db3b7befa920dca02489caddb38d76ef63`。3ed96bdc只补失败时不含正文的计数诊断，后续六次独立同场景冷启动均通过；该事实不能证明首错由环境或0.3秒超时造成，也不宣称已定位修复。本轮未增加重试、放宽期限或删除原采用断言，失败历史不改写。

最终冻结d871437b使用真正公开install helper/能力回调、自动私有绑定及正式completion，不再在SDK客户端手工注入preview/formal metadata或bind_provider。宿主与语音脚本均来自固定Git对象，voice关键8文件逐字节核对；3.10不导入longmemory。真实SDK2.0.3/正式Runtime/HTTP五路RPC/本地Gateway SSE共11场景，加热修反馈两场景，**13 passed / 87.55s / 0 skipped**。报告 `data/test-tmp/ai-proposal-real-sdk-d871437b-02.xml` SHA-256=`54a38dee28a03b35cde5e817071256d557edc30e61846ae67f7c232cefbce6db`。覆盖实际原ASR、端点reset、正式prepare恰好一次、六项完整记忆、输入变化miss、工具零RPC、打断/新轮/队列撤权；均无学校或外部HTTP请求，合成库和随机端口隔离。

最终适配/预取/输入输出计时/SmartTurn/RPC/连接与快捷回复/启动器，加AG四组与文档机制合计 **464 passed / 20.72s / 0 skipped**，报告 `data/test-tmp/ai-proposal-ag-final-d871437b-01.xml` SHA-256=`bc1320cad4f3a25b7fe8559117f71358785a98593f3517fbd0ee0cf3659c9e30`。这组不包含上述13项SDK组合，不合并计算成一次执行；早期357项＋7子测试、AG独立99项与后来的464项有重叠，不能相加冒充覆盖量。

按主会话最新明确授权，backend_resources.py新增 **37项精确name/parameter/reason**：26个显式固定上游源码场景、11个显式SDK/3.10场景；[逐项对照JSON](../../../tests/fixtures/voice_proposal_resource_cases.json)不参与运行时放行。缺资源实测16 passed/37 skipped，正式audit_report返回(16,37)，报告 `data/test-tmp/ai-proposal-resource-final-01.xml`；报告护栏7项通过。原有声明与普通requests/numpy/PyYAML缺失拒绝规则保持，未改workflow、Playwright、e2e或前端。此处不是完整远端CI通过证据。

AG `76e8d28bf39c53d0f9eb1463a0237e3b8b22950f` 独立审查后接入为 `62d4fff8`。公开Job查询共享结构，不改内存/CPU/时限；异常路径在关闭自有句柄前保存前后计量、阶段日志摘要和子进程退出码，并同时保留并发准入拒绝。查询失败仍清理，关闭AG-FLOW-GPU-20261021-01防止复用旧许可；不豁免stale PID或新增外部上下文。AI实际四组 **99 passed / 3.06s**，含轻量真实CPU Job，报告 `data/test-tmp/ai-ag-accounting-review-62d4fff8-01.xml` SHA-256=`478a17e5914173d5e0d42cfb421c5b7c5bba82c3856cd6c854a1fcf040d1d2cf`；11模块在既有小智3.10解释器AST检查通过。

AI独立核对AG已生成CPU小图report/probe/receipt/source-analysis四份原字节摘要均与其交付一致，并逐一重算四个ONNX字节与摘要、16项allclose、最大误差3.5762786865234375e-7、CPUExecutionProvider、未初始化CUDA/加载真实Flow标记。Job峰值525000704字节、退出0和清理0 active来自AG既有receipt，本轮没有重跑该小图，更没有GPU重试。小图不证明真实Flow可导出、6GiB根因或性能提升；001仍关闭、无真实ONNX/engine、buffered日用保持。旧219管理proof和SDK原语不变，src/longmemory相对890无差异，不用旧proof替新桥或GPU新目标背书。

5份直接相关公开文档及清单窄范围audit为checked_documents=5/findings=[]。生产、真实识别/声质/打断/延迟/圆屏体验和新远端Quality均另验；首轮SDK失败仍是已披露未定位项，不以本轮后续通过抹除。主会话补报远端39513701635后端3552 passed/179专属资源skip/323.34s，组件/类型/构建success；浏览器143项为68 fail/72 pass/3 skip，AH继续定位。此为主会话报告，与AI此前受控最小依赖3550/181及本段本机结果分别记录。


主会话后续决定先推候选分支并以workflow_dispatch验收Quality，待AH生产会话修复/完整浏览器交付经AI审查后冻结最终候选；main和当前ready服务先保持。完整远端通过后，主会话才安排owned检查点、ff/准确dist部署和main推送。此为发布顺序决定，不是上述动作已发生或全部技术已启用；AE/AG本段提交与后续AH接入分开。

## AH完整浏览器修复最终接入与候选放行

主会话后续授权完成AH最终审查，顺序接入 `d3571b2ce5e6e85ce6fbc5a2e7f2134106f06300`→AI `7f6cb6b6`、`dfa0747c5fa81edc8c34bd0d3685e9b274b29af3`→AI `b7083ce0`、`a4be7cb1eb5dd0f9be4e2f6cca88edcf7368fa8f`→AI `5b116366573184c2304c46c443721b4350921847`，无冲突。AI新增端口保护另为 `c52825e9`，未交叉改AH冻结树。后续本次收尾仅编辑本AI记录与共享清单，业务/前端字节保持5b116366。

生产改动仅ChatApi.bootstrap同页面模块内共用在途Promise：同源Cookie由浏览器共享，所有并发客户端取得该一次请求的CSRF；成功、HTTP错误、JSON错误或请求异常均经finally释放，旧Promise的清理不会清掉新的在途请求。不新增令牌持久存储、不缓存完成结果、不自动重试业务写请求。后端Host/Origin/Sec-Fetch-Site/CSRF、中立客户端错误、no-store和写请求same-origin保持；不同页面依次初始化时沿后端既有Cookie复用，不把同页面内存锁宣称为跨标签同时冷启动的协调。后者仍不覆盖，AH记录已有明确限制。确定性旧代码回归实际csrf_rejected与修后成功原始JSON均复核；未把远端首开禁用唯一归因于该竞态。

测试前提差异分别核对：全站引擎身份、旧引擎业务失败矩阵与新增“准备档案”键盘步骤由显式合成夹具补齐；诊断主机每例经实际会话/Origin/CSRF后只重置本进程合成事件，不扩大生产容量100或删除日用日志。默认两个项目分别普通/诊断，观测专用fetch从当前请求origin生成；已有定向配置显式覆盖单项目，避免继承新增项目。真实SDK文件逐字节原文移至e2e-live，由需显式资源的原z-live配置保留，未用Fake替代真实SDK。无新增测试skip、重试、超时放宽或业务断言删除；普通项目的observability排除与专用项目的匹配成对，逐项收集证明不是漏跑。

AI重算三份原收集JSON及哈希并逐项比较[143原用例映射](AH-ci-browser-collection-20261021.json)，134普通＋8诊断＋1独立真实SDK无遗漏重复；新增1冷会话用例后默认143项＝原142合成＋新增1，独立真实SDK本次仅收集未执行。AH最终350组件的JSON实际63文件/350 pass/0 pending，类型/构建原日志和提交/工具绑定一致。完整CI入口浏览器实际运行在d3571b2c：143收集、140 pass、0 fail/flaky/retry、3项原有Otto固定素材skip，237973ms；AI逐例核对结果和零retry。后续dfa聊天专用配置只改projects覆盖，另4/4 pass、10511ms，无诊断混入；不宣称dfa又重跑完整143。

主会话指出日用端口范围后，AI在独立c52825e9增量中将普通与诊断配置共用的纯校验器移到browser_test_ports.mjs，拒绝8000/8003/8766/8767/8768/18000/18003/18767/18770；默认18777/18892、端口范围、互斥检查和既有超时不变。固定Node24.19.0仅运行原4项收集护栏＋新增2项端口护栏，**6/6通过**，配置语法检查通过；没有依赖安装/复制/联接，没有重跑AH完整node套件。公共清单旧真实SDK来源已改为e2e-live，映射中的original_file仍保留历史原路径。

准确新产物为AH树 `data/test-tmp/ah-release-browser-dfa0747c-20261021/dist/`，45文件/1,839,032字节。AI逐文件检查相对路径、字节数、SHA-256、无额外/source-map文件和固定凭据/私有路径/fixture内容指纹；重算manifest导入图、完整264处本地引用及其归属，91张新截图逐一核摘要，五项构建输入及六项AH验收源码输入绑定均核实。实际完整/聊天测试的默认dist、预先冻结清单、新候选45项逐字节一致。上述为AI独立脚本检查，没有执行AH核验脚本后照抄结果；AI没有重跑浏览器或视觉宣称新功能验收。

新规范运行摘要=`bcde5ee77a08fa513942c7f13ffe60885e7a3c4acfe237f5dac4975886679af1`，manifest=`5e94e8fea73e850d7335feac0fc3e3f190e67a3e761cdce08b07986b0b308b00`；release-binding=`09c37ca9968f4576203a8a9bfeaaff98245eb21bd4af790702f15b7947b1183f`，delivery-receipt=`27327ca4b80202b2f255533b9b35625e87e63ac81d2e4679ca12c74846024df9`。相对旧c5产物净增84字节，包含真实bootstrap修复，不能复用旧dist部署。AH构建源为dfa、前端tree=`a2d622edf976bf49325c09ee703a35d29f72f4af`；融合前端tree=`43c6c7282cc2466bd8d1922a04a2701418bd5cc2`，二者前端差异仅playwright.config.ts端口校验提取，生产src、五项构建输入、shared-assets tree逐字节/对象一致。AH原回执不改成AI新tree；AI另存 `data/test-tmp/ai-ah-release-review.json` 记录5b时独立等价核验，不冒称融合树重新构建。原有八层/provenance生产组件未变，相关完整浏览器仍通过；真实模型/设备另验。

按主会话要求，在本树通过原入口 `python scripts/ci/backend_quality.py` 实际完整运行，**3593 passed / 200精确资源skip / 0失败 / 234.13s**，报告护栏返回成功。JUnit `data/test-tmp/ci/backend.xml` SHA-256=`40f58b19765331dea8bcca07662266028b65a204b9bf538e3c71e5ead30a33a6`；完整日志 `data/test-tmp/ai-ah-combined-backend-01.log` SHA-256=`9aa37e61afafb3fbf350f621ebbccd8bb9c94872049d75f559f5f488f81e71aa`。实际3793用例逐项无failure/error，本轮新增37项资源name/reason均精确匹配声明；没有用缺普通依赖跳过放行。本次完整入口未设置SDK资源路径，不能替代前段d871固定真实SDK13项；本机3593/200、远端旧3552/179、受控最小3550/181是不同条件，不混写。

源码/产物审查未发现新增阻断项，可由主会话按既定候选分支调度远端Quality；本地成功不等于远端已绿。AE首轮SDK失败仍未定位且完整历史保留；跨标签同时冷启动不覆盖；3个Otto素材验收与1个独立真实SDK浏览器本轮未执行。候选仍保持提前回答双端默认关闭、buffered日用及原已选模型/声线；本会话未推送、部署、停服务、改个人数据或操作GPU/设备。主会话完整远端验收后再决定准确新dist切换。

## ROOT发布报告与实机失败（2026-10-21，未完成收尾）

以下是ROOT主会话在发布后发来的执行报告；AI仅据报告维护公开记录，未亲自停止/启动服务、读取私有备份/配置/个人库或实测设备。此前“未推送/未部署”对应AI交付阶段，现由本段补充后续事实，不改写当时证据。**最新状态：所有者实机验收FAILED，字幕遮挡且无法打断；ROOT已报告buffered恢复并ready，但字幕/打断修复与复验未完成，不能按验收通过收尾或归档。**

ROOT报告候选分支的Quality `39518824436` 对冻结业务提交 `944b83bac013aa008f3b05db8b12d6042e686eae` 全部success，随后main已快进至该提交并普通推送。该候选远端实际后端3577 passed/216精确资源skip/264.43s，组件63文件350通过，浏览器143 scheduled/140 pass/3 skip/0 unexpected/0 flaky/247651ms，完整原始日志由ROOT保存在检查点quality-full.log；这些数字不同于AI本机3593/200和AH本地237973ms，不混写。main自动Quality `39520018676` 同属944；ROOT已将frontend failure定位到两项组件用例：MemoryApp日常纠正、RoundDisplay皮肤等待回读，均5s超时；根因待AH定位，不通过rerun充绿或放宽原5s界限。失败原始日志为ROOT检查点内main-39520018676-frontend.log。ROOT最新确认该次main运行已completed failure：frontend两项超时、backend success；不写成main全绿。候选远端通过、main合入、部署就绪与实机体验分别记录。

ROOT核对owned旧launcher33512及其16个祖先链实例全部退出，7个端口释放后，取得完整停机备份：93文件/14,715,389字节，manifest SHA-256=`8a9b23ee558012196ec80921fb1c9d5fb7f4e0479b96f002170aae9932a7499a`，检查点为主项目 `local/archive/hy-advanced-release/20261021T000628Z-944b83ba-d3b53e/`。该路径和摘要来自ROOT报告，AI未访问或解析其中内容。新45文件dist逐项复核为1,839,032字节、规范摘要 `bcde5ee77a08fa513942c7f13ffe60885e7a3c4acfe237f5dac4975886679af1`；ROOT保留旧dist，17份私有配置原字节保持，未以旧c5产物替代本次会话修复。

ROOT通过正式入口创建新launcher14536，创建时间UTC `2026-10-21T00:13:37.515519+00:00`（北京时间08:13:37.515519）。本次启动请求中host/voice候选均为0、话轮结束识别off、CosyVoice声音交付模式为adaptive；adaptive只经本次子进程环境请求，没有回写持久设置。当前接口未暴露实际声音模式，因此这份证据只证明请求参数及下述服务状态，不能写成已证明真实adaptive播放或已定为持久默认。此前buffered默认与回退边界保留。以上是失败反馈前的启动状态；所有者随后明确拒绝本次adaptive实机体验，ROOT随后报告已恢复buffered并ready，adaptive未被接受为持久默认；恢复就绪不代表字幕或打断缺陷已修复。

ROOT报告control/runtime ready，TTS warm ready、active=0、generation=false、restart=false，八层只读入口可读；语义派生仍初始epoch0/ready_epoch-1、isolated、无任务，没有为了健康状态生成个人任务或假对话。调用账本仍38 complete＋1 historical unknown、0 reserve，未清除旧unknown。OTA地址保持原值，Docker和设备均未操作。这些是ROOT发布时报告的状态，不是AI复读个人库或新发起真实模型/声音会话的测量。

任务追溯如下；“合入944”仅指已发布的业务交付，不代表本次实机验收通过。后续docs-only记录不属于944业务提交，其整合状态由ROOT另行记录。

| 任务 | 交付提交 | 实际验收边界 | 合入提交 | 会话ID |
|---|---|---|---|---|
| AI整合AE/AG及后端精确资源登记 | d871437b、2bb0da48、a512a4f6 | 固定SDK组合13项、合成464项；首轮SDK失败原因仍未定位 | 944b83bac013aa008f3b05db8b12d6042e686eae | AI：01a15ab0-25a3-7380-b682-681441e8b403 |
| AI审查AH完整浏览器交付并补端口保护 | 7f6cb6b6、c52825e9、b7083ce0、5b116366、944b83ba | AH本地350组件/140浏览器通过＋3既有素材skip，AI完整后端3593/200及产物独立核对；ROOT报告候选Quality39518824436全绿 | 944b83bac013aa008f3b05db8b12d6042e686eae | AI：01a15ab0-25a3-7380-b682-681441e8b403 |
| ROOT受控发布与所有者实机验收安排 | 944b83ba＋新bcde产物 | ROOT报告owned备份/停机、普通推送、新服务ready；所有者实机FAILED，ROOT报告已恢复buffered/ready，缺陷待修 | 944b83bac013aa008f3b05db8b12d6042e686eae | ROOT：01a1534f-3c56-78c1-9e13-4777422a67bb |

所有者实机反馈经ROOT转达：“字幕很多都被遮挡了，与圆屏不适配。无法打断”。本次adaptive验收明确为 **FAILED／待修**，不能用服务ready、候选CI全绿或本地合成通过抵消。ROOT已保存检查点内adaptive-failure-timing-metadata.json及adaptive-owner-rejected.json；AI没有访问该私有元数据或代填实机结果。ROOT已完成owned重启并报告恢复buffered：launcher9680，创建时间UTC `2026-10-21T00:21:22.992765+00:00`（北京时间08:21:22.992765），control ready、TTS warm ready、active=0/generation=false/restart=false；恢复状态存于ROOT检查点health-buffered-restoration.json。17份私有配置字节保持，没有回滚个人对话或944代码；ROOT最新health-buffered-restoration.json读取快照为53 completed＋1 historical unknown、0 reserved；48条是停机前快照，38条是原发布时点，均不能当作恢复后的当前计数。ROOT未进一步归因恢复后新增5次的来源，未读个人正文，也未手动enqueue、生成合成对话或重置额度。新停机保全为93文件/14,978,741字节、manifest SHA-256=`8a896a4301d102b16a68bf9a22ee8f7aa8faaa7ae69a0f62b1925e4a2b2de7e9`。这些均为ROOT报告，AI未访问保全内容或操作恢复，buffered ready不抵消本次实机FAILED。

ROOT已将音频与自然打断定位修复交AD、字幕适配交AH，AI保留整合审查角色，不给AD/AH直接发消息。本轮暂停新增特性及AG试验，保留944业务字节；buffered已报告恢复；字幕/打断修复与所有者重新实机验收完成前，不按已验收归档相关会话。main两项组件超时另由AH取证定位，不推定与这次设备反馈具有同一根因，不rerun充绿、不放宽5s。

ROOT转述所有者进一步明确：字幕被圆边裁掉，stop已识别但旧声继续。AH报告板级字幕上移38px后，基类SetChatMessage又将其bottom复位为252×48，正在准备隔离审计补丁、安全区预览和离线编译计划；尚无固件写入许可。AD报告已在固定上游复现client_abort可复位、旧轮缺永久撤权的代码缺口，正在修候选关闭时的音频撤权与诊断；这项代码发现不等于已证明所有者故障原因。AI尚未取得并独立审查这些后续补丁，不将方向或复现写成修复完成。AH不改AD公共音频/launch文件，若需helper装配，待交付后由AI整合审查；本阶段不交叉改生产或944冻结业务。


保留未定位的首轮SDK失败、跨标签同时冷启动不覆盖、host/voice候选关闭、SmartTurn off、TRT无真实engine等限制；字幕、自然打断及真实声音/延迟/设备体验当前待修或复验。原219项及其管理proof仍仅属于 `f5906827d98ce4d2665d5e6b83b04ee1ebda58fa` 的固定边界，没有重签或改称944的新全量证明。ROOT未授权AI操作生产、个人数据或固件；本次记录更正不扩大执行范围。

## 字幕与打断候选的隔离接力（2026-10-21）

本段补充上述等待交付之后的实际工作。AI工作树 `local/worktrees/ai-integration-review-20261021`，分支 `codex/ai-integration-review-20261021`；仅隔离源码、合成数据和随机环回端口。未操作日用8767/8000/8003、模型/GPU、私有配置/个人库、串口或设备，不推送/合main。此前实机FAILED保持；候选离线通过不能代填owner体验。

接力关系如下，均尚待ROOT正式候选流程：

| 来源任务 | 固定来源提交 | AI接入/修正 |
|---|---|---|
| AD进程内永久撤权 | b0973bbd | 05bac372；安装顺序、普通完成/严格摘要接线57b448d8，领取竞争修复0bc29b5f |
| AD设备线协议 | 修订3 2b8242e5；服务端ff6ef6e6 | 3d68e8bc、4e65515c；0970e5bf补EOS后撤尾、控制stop、准入预算、wire领取屏障，合同现为修订4 |
| AH组件查询与可见性 | 84fa8e4e、0fddd882；AI d286b4cd，AH等效e5fcca1e | 87b5e181、97dc79c5、d286b4cd；AH冻结验证记录38a04d4b接为2fbf0ab6 |
| AH字幕/消费者/镜像 | e63441a4；最终验证记录055a7f39 | 0ac69371、197837b7；0970e5bf另补两份审计patch的精确LF属性 |

软件接口冻结 **`0970e5bf5f5c4672344bf74377eb505f00a676fe`**。前端tree `2d06c0dd5081eab580618cfbca6978477f5d0d60`，`device.ts` blob `0cd6ae2c0fc8e4ab5bec74c76999b523e06d36fb`；与AH e5fcca1e相比，前端唯一差异为该文件的可选状态类型，两个流程测试blob相同。后续197837b7只接AH固件测试/记录，未改变web tree；ROOT已安排AH按该最终精确类型接力构建。不能将此前AH完整350/构建直接标成这棵最终web tree的验证。

### 实现及证据边界

普通candidate OFF也安装永久音频撤权。actual executor.submit捕获不可变代次，旧排队chat不会重新prepare；助手put在共同屏障内拒绝撤权后的文本。真实MemoryProvider先取得Memory锁，再以音频/wire短锁检查并原子领取pending；RPC、磁盘及等待Memory锁不占音频锁。外层检查通过后才发生ASR撤权也只能cancel，不发complete。已经领取并开始外发的完成允许结束，不承诺回滚；撤权前已入内存历史的助手文本不被事后改写。

显式wire代理装在全部原包装之后、control/app之前；仅直接WebSocket/pipeline/本地Cosy且双向严格hello及最终发送覆盖齐备才确认v1，旧0015或旧服务器保持legacy。所有TTS JSON/二进制共用最终socket发送门，入门前固定身份，旧在途发送返回后才发interrupt，再开新start。epoch耗尽、覆盖改变、写或等门超时关闭当前连接，有界取消/join自有任务；不把发送返回当物理播放确认。

联合审查发现并补齐EOS后尾音窗口：普通stop仍自然排空；随后ASR交接、明确abort或控制面板stop可以发同epoch interrupt。服务端队列空、speaking=false也不能据此判定物理already_idle。重复停止不重发，正常EOS完整尾帧回归保留，旧EOS/UI不能伤新轮。该补充已经ROOT明确确认，见[合同修订4](AD-tts-interrupt-v1-20261021.md)。

声音HTTP只对精确503 JSON `{"error":"busy"}`重试，首次busy之后共享400ms准入窗口；每次connect/响应头使用剩余时间，过期或永久撤权关闭自有socket。首请求保留原超时，200后的生成体不受该预算截断、不重放。AD原交接失败来自旧生成finally未释放、新请求尚未进入合成的busy，不能归因于wire；AI组合首次又发现socket timeout略早于单调deadline的异常类型差异，已修稳定拒绝。首次失败和修复后报告均保留，不称实际模型400ms内可恢复。

当前连接只读 `voice_interruption` 和 `tts_interrupt` 沿现有受保护HTTP返回。3.12投影严格枚举、整数/布尔、固定计数和零额外字段；已知摘要非法为稳定502，旧响应缺可选摘要仍兼容。断线不复用旧连接摘要；closed保留曾经协商事实，`device_playback_acknowledged=false`始终成立，原16KiB响应上限不变。前端只有可选类型，没有新增显示或自动启用逻辑。

### 实际验证与保留失败

主Python3.12.13、声音Python3.10.20及固定上游 `eb4b28c59ed7ed885258498cf757ce14352d620e`，不安装/下载依赖。下列JUnit位于本树 ignored `data/test-tmp/`，报告间有重叠，不将通过数相加为唯一用例数：

| 报告 | 实际结果与范围 |
|---|---|
| ai-wire-combined-01.xml | 135通过/2既有资源skip/1失败，重试headers超时类型差异；保留原件 |
| ai-wire-combined-02.xml | 修正后136通过/2既有资源skip/26.32s；固定原生ASR/chat三阶段、真实provider、真实随机WS、真实Opus及严格状态 |
| ai-wire-broader-01.xml | 225通过/7 subtests/4.41s；流式PCM、重采样、控制、客户端、文档工具和CI护栏 |
| ai-wire-control-opus-01.xml | 最终控制stop补齐后77通过/12.03s；真实WS的EOS后ASR/abort/control stop、实际HTTP/FIR/Opus链路 |
| ai-wire-resource-03.xml | 25通过/20精确资源skip/0.56s；模拟固定上游及专属3.10缺失，质量audit_report返回(25,20) |

20项新增资源边界逐项登记：12固定SDK、4声音解释器、3明确原生仓库路径、1websockets专属解释器；不按模块通配，纯schema/HTTP/上下文/锁/busy用例保持执行。resource-02只成功模拟固定源码/原生路径缺失，实际30通过/15skip，未将其冒称全部20项缺失；03在收集时精确模拟解释器缺失后补齐。固定资源运行中三阶段均实际执行，2项skip来自旧test_xiaozhi_bridge以本树local路径判断资源，不是新增三阶段未执行。单文件前端类型检查使用已固定Node24.19.0和AH已装编译器工具退出0，未给本树安装/联接node_modules；完整最终web树构建由ROOT安排接力。

此前d286完整后端入口 **3639通过/202skip/1失败/285.99s** 保留：`test_launcher_doubao.py::test_secret_dialog_is_blank_and_saves_only_on_user_action` 的Tk entry.tcl初始化读取失败。冻结副本 `ai-b097-full-backend-01.xml` SHA256 `c184a88bbe967927f7a0a3e432c4028253bc81339357025488b8c0b2f4ee1904`。只读核对同解释器Tcl/Tk8.6，相关文件可读、相关环境变量为空；同一用例独立复现1通过/0.15s（ai-tk-isolated-reproduction-01.xml）。失败时加载现场未采样，原因未定位；不能称全量绿、不能断言永久环境损坏或并行负载就是根因。没有改环境/跳过/超时或重跑全量充绿。

### AH与固件联合审查

独立核对AH e5fcca1e绑定：45文件/1,839,032字节、规范SHA `bcde5ee77a08fa513942c7f13ffe60885e7a3c4acfe237f5dac4975886679af1`，264引用、91既有截图及源输入摘要吻合，两个测试与AI d286逐字一致。`ai-ah-e5fcca-review.json` 保留完整检查。原始组件第一次16通过/3个5s超时，随后空闲19/19与350/350均0失败，原失败保留；没有提高5s或加retry。浏览器140通过/3既有Otto skip是先前已绑定运行，未冒称本轮重跑；原始Vitest的numTotalTestSuites含父级/重复统计，63文件以实际报告记录为准。最终可选类型的完整web构建仍单列接力，不能只因type-only就宣称已实测相同产物。

AH最终[字幕/消费者记录](AH-round-subtitles-20261021.md)和固定JSON已接入。AI实际重跑源审计：10,765文件、8目标改动、10,757非目标一致，原0015保持，两个补丁正向/逆向逐字节通过；审计JSON SHA `7d760a906cf503572407dc3da6007e7234ab3b2bca662bf62e27b462370214b9`。初次因checkout将新patch变CRLF而拒绝，补两份精确LF属性并恢复冻结blob字节后通过；不是改固件凑证据。

AI按实际最终源重新生成消费者v4和字幕夹具，逐字比较AH已编译输入后重新执行AH既有本地测试二进制：消费者与未声明客户端均退出0，消费者日志SHA `b61a7f47aad77e524f3dbfca12fce1360907bd025f9394a2ccaa49fd3b477918`；包括已出队decode/PCM、legacy→v1重连、EOS活动计数、EOS后interrupt、旧已排队EOS/Speaking→新start。AI没有另做MSVC或固件重编译。真实队列/身份/应用方法来自抽取原件，硬件codec/Opus/FreeRTOS为替身；这与服务端WS的合同预言机是两层证据，不是服务器到真机端到端听验。

字幕重新执行真实LVGL/原字体夹具日志SHA `95cda431d26cb63bf7d176265eb3219c6034a077dd37bc3caec98a819f2d866d`：标签(70,252)-(289,305)，五句12行全部可见、首移900ms、末行10220ms，40ms旁路刷新不复位。AI另查看修正后的v4首/末PNG，确为首句和最后一行；早期快照错帧证据保留，未当成最终像素证明。下一条字幕仍按原sentence_start替换，所以不能保证实机语速下每条都滚完；实际GIF/字体覆盖/声画节奏待owner验。

最终应用仅为4,011,456字节的 `2.2.3-otto0016`，SHA `caca8cbf7b8b1df715c9523c1f32321d8b32b309acb63adf2e710d7f9901193c`，静态slot余117,312；不是早期final1。ROOT另报告已独立核对8文件、2patch、4产物和SDK固定commit，并将唯一应用保存到其检查点 `0016-root-review/`，记录root-readonly-verification.json和source-build-manifest.json。该ROOT核对只证明身份/容量，不授权写入，也不替代本次审查或设备体验。AI未打开串口/写设备，未宣称第二次独立固件重建。

最终web树接力随后完成：[AH记录](AH-final-interface-20261021.md) 固定a601e7f7（AI接为ec927d21），实际构建来源ba37f972，双方web tree均为 `2d06c0dd5081eab580618cfbca6978477f5d0d60`。AI再次独立核对新绑定SHA `6c8465822e2c8d701f7d1ded11760ce600419c92028f4d795d6cb51b8503ad8f`、5个构建输入、45文件、264引用、91旧截图及精确接口blob；新产物逐文件仍等于bcde，类型检查/正式构建退出0。`ai-ah-final-interface-review.json`保留结果，前端无须重新部署。350组件及旧浏览器不重跑，来源仍如前段，不能称本轮新跑。

最后复核又将wire.close的closed写入纳入音频短锁，且未绑定首个wire turn的租约也检查protocol.closed；关闭同样不能穿过完成领取。新增真实provider的close前领取/已领取RPC两种屏障验证，连同固定原生ASR三阶段、真实WS、executor及永久撤权共 **26通过/8.46s**，`ai-wire-close-completion-01.xml`；没有改web tree或固件镜像。文档接力最终以共享manifest窄范围strict检查记录为准。

未解决的发布/体验事项：ROOT精确最终候选远程Quality、新0016活动应用写入许可与K专属执行、owner真实字幕/声音/打断/多轮复验。当前没有发现仍阻断隔离候选提交的代码缺陷；上述本地完整后端失败原因、真实模型和设备边界均保留，不按已验收归档。

## 360远程Quality失败后的bootstrap测试接力

ROOT随后报告精确 `360eab8e03b0c38ad6ad73fa104534bd59eef8ab` 的远程Quality `39530302377` **FAILED**：后端3640通过/236资源skip/2失败，均为 `test_launcher_latency.py::test_pipeline_bootstrap_installs_input_timing_before_response_policy[realtime/original]`。失败发生在正式main新增导入helloHandle时，合成core.handle只提供旧模块，未同步wire安装契约。ROOT原始日志保存在主项目检查点 `local/archive/hy-advanced-release/20261021T020149Z-360eab8e-acbb73/quality-backend-failure.log`；以上为ROOT报告，AI没有执行远程下载或改写该日志。浏览器另有1失败/139通过/3既有skip，由ROOT交AH独立处理，本次不改浏览器文件。

AI在干净360隔离树先独立运行这两个参数，实际复现相同ImportError：`data/test-tmp/ai-360-bootstrap-reproduction-01.xml`，2失败，SHA256 `4a7477fb54f987a04a0e54bbaee6d2042701eb7ccb95226069414063a5628eda`。确认测试前提漏接后，只更新该fixture：提供helloHandle、listenMessageHandler和协议安装器替身；断言接收当前Connection类、实际send模块、hello/listen身份及本次上游路径，并将wire调用纳入永久撤权之后、app之前的完整顺序断言。没有在生产增加try/except绕过安装器，没有新增skip、timeout或资源例外。

修后运行完整launcher_latency、voice_proposal_bootstrap、advanced_voice_bootstrap、固定上游真实WebSocket测试以及CI报告护栏：**53通过/0skip，7 subtests通过，9.18s**，JUnit `data/test-tmp/ai-360-bootstrap-repair-01.xml` SHA256 `239c27eee1596b406339ce42744b6479e0d2425d0e190a52b467674550c82193`，audit_report返回(53,0)。固定源码验证仍用已装Python3.10及 `eb4b28c59ed7ed885258498cf757ce14352d620e` 的实际文件指纹、提取函数和真实随机环回WS；配置/其余模块为合成替身，不称启动了完整日用服务或模型。

`backend_resources.py`相对360逐字未变，精确资源报告再次审计返回(25,20)，7项CI护栏通过；没有用新跳过掩盖fixture失败。本轮不重跑全量后端充绿，既有本地entry.tcl失败/单例复现通过及360远程失败全部保留。生产语音源码、整个web tree `2d06c0dd5081eab580618cfbca6978477f5d0d60`、0016补丁/镜像均未变；仍由ROOT处理浏览器交付、精确新候选远程Quality及后续授权，不推送/合main/停服务/碰设备。
