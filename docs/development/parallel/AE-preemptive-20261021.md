# AE：受控提前生成（2026-10-21）

范围：从 `a93258e903954525b88b7af79756aaffe2bd50d6` 的独立树实现候选生命周期和隔离测试，不连接日用服务、个人库、真实学校模型或设备。分支 `codex/ae-preemptive-20261021`。公共接线归 AI，本记录与新模块归 AE。

## 第一里程碑：代码事实与接口草案

- `scripts/development/xiaozhi/voice_prediction.py` 是封闭问句影子统计，无模型调用；保留其兼容行为。
- `MemoryRuntime.prepare_round_screen` 会 reserve、prepare_user、写 prepared/feedback；`prepare_user` 可归档来源、挂起派生或执行管理操作，不能用于候选。
- `HyMemoryMethod.recall` 返回 `hy_recall_may_mutate_state`，`HySdkBridge.search` 调用真实 SDK search，不能把普通 search 当成只读证明。
- 因而 AE 新增 `voice_preemptive.py`（只接收冻结文本，不接收 Memory/prepare/search 回调）和 `voice_preemptive_stream.py`（有界模型流解析及关闭）；不改现有跨边界文件。

接口最终采用：AC/AI 用不可变 `TurnStamp(turn_id, transcript_revision, cancel_epoch)`；`turn_id` 按连接递增、`cancel_epoch` 按连接不回退、`transcript_revision` 在轮内递增。AC 的真实输入是 16kHz 单声道 60ms PCM，事件应在原音频清空前发出；AE 不修改音频缓存。

AB 需交付 proposal-only/context-snapshot：不得 reserve/归档来源/pending、提取、整理、管理写或执行工具；需冻结消息及 memory/context/tools/policy 四类版本。版本还须覆盖引擎实例/重启、角色、当前日期提示、模型、设置和并发写。若不能给出这项证明，提前生成保持关闭，走正常正式 prepare。

AF/AI 需提供经免费学校策略审查的异步上下文管理器：负责原网关预算和 unknown 账本、连接身份、请求取消、响应关闭，无自动重试，不将候选送入正式日志/字幕/TTS。AE 额外限制请求数、输入字符、输出 token 预留、并发、超时和候选大小，不修改原费用账本。

主会话已预留 ADR 0198，AE 写入 [无副作用候选决策](../../adr/0198-no-side-effect-preemptive-generation.md)，状态仍是候选模块完成、组合待验；没有抢占其他编号。

官方参考：[LiveKit 提前生成](https://docs.livekit.io/agents/multimodality/audio/#preemptive-speech-generation)（2026-10-21 阅读）：模型准备与确认分开，上下文/工具变化废弃；本项目不引入 LiveKit 依赖，候选期不运行 TTS。

## 第一阶段核心接口与接力

`voice_preemptive.py` 只有标准库依赖。每连接一个 `VoicePreemptive`；AI 在同一事件循环内跨连接共享一个 `RequestBudget`。音频线程须通过事件循环的线程安全投递入口转发，不能从线程直接调用控制器。

| 调用 | 契约 |
|---|---|
| `begin_turn(turn_id=..., cancel_epoch=...)` | 新话轮首个发声即可取消旧候选，无需等 ASR/记忆快照；不消耗新轮唯一候选机会 |
| `provisional(turn=stamp, transcript=text, context=snapshot)` | 同步返回是否调度；只从已冻结文本准备模型流，每轮最多一个请求；重复、续说或修订不重试 |
| `revised(turn=stamp)` | ASR 修订立即撤销，无需取得新上下文；正文变化也必须递增 revision |
| `continued(turn_id=..., cancel_epoch=...)` / `cancel(...)` | 同步撤销、清空正文、唤醒确认等待、请求关闭流；累计预算不返还 |
| `context_changed(version=None)` | 一获知上下文/工具/策略变化就可取消；传版本时相同版本为无操作 |
| `await confirmed(turn=stamp, transcript=final, context=final_snapshot)` | 仅最终端点使用；等待已有准备任务或撤销事件，绝不发第二次请求；匹配返回 `ConfirmedCandidate`，否则 `None` |
| `lease.claim(turn=stamp, context=fresh_snapshot)` | 正式派发前的一次性同步领取；不匹配即永久撤销；不得在领取、原取消门检查和入队之间 await |
| `close()` / `await aclose(timeout_seconds=1)` | 立即撤销并有界等待清理；返回 False 时真实请求还占用并发名额，不伪报已停止 |
| `snapshot()` | 只有有限状态和聚合成本/命中；无正文、身份、内容摘要或供应商异常 |

`ContextSnapshot(version, messages)` 只接受不可变文本二元组，首项为唯一 system；不搬动消息、角色或内容，不允许历史 tool 消息。`SnapshotVersion` 的字段是 `memory_revision/context_revision/tools_revision/policy_revision`。正文变化即使误复用版本也会由内存摘要拒绝，摘要不会输出。

重要组合顺序：最终端点才可运行正式 prepare/管理/归档；AI 必须比较正式结果所需的**当前**上下文和版本，不可把旧快照当新快照传回以制造命中。正式流程产生管理回复、工具需要、记忆变化或不同上下文时丢弃候选；日用 buffered 链路继续正常回答。严格版本比较可能降低命中率，应先修快照/提交契约，不能省略一致性门来换延迟。

`voice_preemptive_stream.GatewayPreparationModel(open_response, model="deepseek-v4-flash", campus_free_verified=True)` 的 `True` 必须来自实际网关策略核验，不是 AE 提供的免费证明。第一阶段普通异步响应接口现已由下文第二阶段的 AF 明确取消/关闭 ACK 句柄替代，不能继续把客户端关闭当成上游关闭证明。AE 不新开真实连接池或绕过调用门。

发出的 JSON 只有原消息+当前 user、所选模型、`max_tokens=256`、`stream=True`、usage、`n=1`、`tool_choice=none`、`thinking=disabled`。无 tools 定义、无自动重试。响应复用既有 `FinalContent`，独立 reasoning 字段丢弃，显式前导 think 按原解析器处理；工具请求、非 stop 结束、不完整事件/DONE、超大流均使候选失败，不能交付部分答案。

默认限制：功能关闭；显式启用后单请求 2 秒、ready 后 3 秒有效；输入 16000 字符、输出 2048 字符/256 token；共享预算默认最多 1 个实际活动请求，累计 20 请求/160000 输入字符/5120 输出 token 最坏预留。启动前取消也不返还累计限额。命中率为已领取数/已准入数；已读输出、已见 usage、未知 usage、废弃预留与耗时分别统计。没有 usage 时不猜测真实费用，旧 unknown/付费冻结账本完全不由 AE 修改。

## 实际验证与边界

- Python 3.12.13、pytest 9.1.1，用项目既有解释器作只读工具；所有源码和临时产物来自 AE 树，导入来源断言通过。相关四文件回归最终 **121 项通过**（包含原影子预测和原答案边界回归），耗时 0.75 秒；无网络/GPU/日用端口请求。
- Python 3.10.20 已运行真实无网络内存 SSE smoke：从本树导入，准备/确认/一次性领取/响应关闭通过，未安装任何依赖。
- 回放覆盖续说/修订、完整输入匹配、四类版本和消息变化、确认与取消竞态、异步传输不服从取消、清理占槽、关闭阶段超时不打断清理、超时/到期、迟到旧结果、关闭/重启、请求/输入/token 预算、无 usage、异常脱敏、工具/截断/缺 DONE/显式推理与 system 顺序。
- 合成 SQLite 正式账本测试：准备、废弃、确认乃至领取本身均不改数据库、不发音频/字幕；只有测试装配器显式模拟正式提交后写一轮。它不是实际 Hy/日用接线验证。
- Windows 10ms TTL 测试前提不足，可能在确认恢复前即到期；测试调整为 200ms 确认窗口再等待过期，实现仍按实际单调时钟检查 TTL，没有放宽到期逻辑。
- 公共清单属于组合维护边界，AE 未编辑。直接 `--only ... --strict` 因两份新文档尚未登记而返回 unknown-selection；AI 需登记本记录为 reference、ADR 为 draft，并关联两个模块和两份专属测试。AE 已以仅追加这两项的内存清单检查两份文档内容和链接，结果 **0 findings**；不是正式清单已合入。

尚未验证：AB 真正无写入快照/版本、AC 真实事件桥、AI 正式提交与派发门、学校真实取消/连接池/usage 账本、用户说完到首个有效声音的收益、续说误抢话/连续性/打断残音和圆屏体验。候选模块默认关闭，不改日用服务、角色/声音或 buffered 默认，不接个人库、不读写设备。

无需所有者下载依赖或模型。真实学校最小验收建议由主会话调度：共享原调用门及未重置账本，仅一个合成候选、最多 256 输出 token、单请求 2 秒、无工具/重试；一次取消用例需另计一个候选，不以此建议自动发请求。GPU/模型加载在本任务没有必要。

## 第二阶段：实际逐连接桥与上游关闭确认

第一阶段提交 `baedad5e5ce1f4da18bb3aefabeaeeecad954c78` 是候选核心交付，不表示用户要求的全部延迟方向或本方向的日用接入完成。主会话继续授权后，AE 新增 `scripts/development/xiaozhi/voice_preemptive_connection.py` 及专属测试，并修复 `voice_prediction` 安装器的跨连接共享实例。原影子返回结构兼容，pending 与统计改为只从 `vars(connection)` 取得实例状态，类级旧值不能继承为候选容器。

### 与 AC 的真实事件契约

AC 精确提交 `67ec9165641f6a9004e13837c7726c5586eea524` 的 `voice_turn_end.py` 字节 SHA-256：`1d26c641c577b9119df720c19e893932e8826a7b62712d4cfd1a33c5787b78f0`。真实 v1 事件是 `on_event(connection, event)`，含 `provisional/eou`、`cancel/cancel`、`continued/continued_speech`、`confirmed/confirmed_turn`；`turn_id` 初始 0、reset/close 递增，`audio_revision` 续说递增，`cancel_epoch` 取消递增，`transcript_revision` 总为 null。AE 的 `AudioStamp` 独立保留这些音频字段，文本版本只按实际 ASR 正文变更产生。

AI 语音侧接线入口：

```python
from voice_preemptive_connection import (
    AudioStamp, PreemptiveConnections, install_preemptive_connection_lifecycle,
)

bridge = PreemptiveConnections(rpc_preparation_model, shared_budget, limits=limits)
# AC on_event 直接传 bridge.on_event；先前安装顺序仍由 AI 保持。
install_preemptive_connection_lifecycle(ConnectionHandler, bridge)

# 只有已经取得实际 ASR content 和可信的无写入快照才绑定；不传 enhanced JSON。
binding = bridge.bind_transcript(
    connection, audio=AudioStamp(turn_id, audio_revision, cancel_epoch),
    text=asr_content, context=frozen_context,
)
# 最终完整 ASR/正式 prepare/fresh 检查后调用，不可凭 AC confirmed 直接派发。
lease = await bridge.confirmed(
    connection, binding=binding, final_text=final_asr_content, context=fresh_context,
)
answer = None if lease is None else lease.claim(
    connection, binding=binding, context=fresh_context,
)
# 领取与原有正式话轮取消门检查/入队之间不能插入 await。
```

这里只展示接口顺序，`rpc_preparation_model`、真实快照与最终派发门由 AI 实现；不是可跳过鉴权/版本检验的生产启动代码。绑定可先于 provisional，provisional 也可先到；两者齐备才调度。enabled provisional 虽然无提交权，仍可准备；shadow 完全不启动模型。enabled confirmed 只记录音频许可；实际文本及快照未匹配前不会调用核心 confirmed。最终 ASR 与候选不同即撤销；不把空文本/音频版本当成完整 ASR。

续说取消的旧版 cancel 和新版 continued 即使同 epoch，也会撤销旧绑定；晚到旧音频/文本/事件被拒绝。reset 在原调用前撤销并记录 AC 当前话轮下界，close 即使原方法异常仍关闭候选；不修改原 PCM、ASR 或 AC 文件。线程事件先标记 quarantine（禁止领取），再投递主循环，避免取消消息尚在队列时旧结果先被领取。两个连接即使拥有相同音频代次，也不能交叉确认、领取或取消对方候选。

### AF 窄句柄与计算占位

第二阶段 `GatewayPreparationModel` 不再接受只有下游客户端关闭语义的普通 response context manager。它要求 `open_response(payload)` 返回带 `request_id`、`await cancel()`、`await aclose()`、`await wait_closed()` 的异步句柄；退出包含响应头建立期间的取消与最终关闭确认。AF 精确提交 `85b1d715a102c82576cea0a56d246e793a7c3d93` 的 `gateway.candidate_response_binding()` 已提供此接口和经原政策/账本核验的标记。AE 保留精确模型名 `DeepSeek-V4-Flash`，并兼容既有小写模型名，不静默改写请求身份。真实回执如下：

```json
{"request_id":"<本句柄ID>","owned_upstream_exited":true,"provider_compute_stopped":false,"ledger_finalized":true,"usage_settled":false}
```

AE 核对 32 位十六进制 ID 和 `owned_upstream_exited`，拒绝别的请求、未退出或缺账本状态的回执。只有完整关闭流程成功、owned 退出且 ledger 完成才可释放额外计算槽；关闭异常或账本未完成均拒绝候选并继续占位。`ModelRequest.close_confirmation` 明确记录是否要求上游证明，证明缺失时工作任务结束也不释放名额；`cleanup_unconfirmed/unconfirmed_closes` 可见，aclose 返回 False，不把任务退出当作真实请求结束。后续可信回执到达可清理占位，但不会重新采用失败回答，也不自行清理原 unknown/付费冻结账本。

本机真实语音和宿主分属 Python 3.10/3.12 两个进程。`GatewayPreparationModel` 是宿主侧 AF 句柄适配；语音侧仅使用标准库逐连接桥与 AI RPC 模型代理。`ModelRequest.scope` 提供 32 位随机 owner/connection ID、准确 TurnStamp 和 audio_revision，供 AI 宿主校验 RPC 的 request/owner/connection/epoch 归属；这些 ID 不进入观测输出，不是鉴权凭据。RPC 必须沿用可信控制入口，不复制供应商凭据到小智、不另开绕审计的学校连接。AF 同对象句柄的注入测试不能冒充这条跨进程链路已经完成。

AB 已转接的候选边界（精确提交 `5a4c1ecb9abf5d2434f8a6eff2e5b3565d8e5d6a`）是 protocol 1 `candidate_snapshot(query_embedding=..., limit=...)` 与 `candidate_validate(...)`；token 最多 30 秒，后台 busy、写入、重启或过期均使候选失效。AI 应在宿主核对 token、memory_digest、实际内容和来源；还须核对完整消息、tools/policy/role/date/model。AE 没有调用 AB 脏树或把普通 search 用作快照，没有以四个字符串版本替代完整内容/来源证明。

### 第二阶段验证与接力

- AE 五文件回归 **148 passed in 0.91s**，覆盖真实事件形状、两种到达顺序、双连接同 ID 交错、跨连接领取拒绝、线程取消先封领取、reset/close、音频与文本版本独立、真实完整文本/fresh 上下文、关闭 ACK 等待/错误 ID/未退出/失联/关闭异常/账本未完成、工具 first_output 不作有效答案。包含原影子统计和原显式推理边界回归。
- 独立从 AC 上述冻结 Git 对象加载实际状态类（未导入其脏树），人工 PCM/固定分数下四场景回放通过：enabled 正常 `provisional→confirmed` 可领取；enabled `provisional→cancel→continued` 不可领取；shadow `provisional→confirmed` 不发模型请求；closed `provisional→cancel` 不可领取。只验证实际代码控制契约，不是中文声学或设备验收。
- AF 精确提交的真实句柄组合：从 Git 对象导出两份公共测试到 AE 自有临时目录，核对 AF src 与该提交无差异，显式使 AF src 和 AE scripts 各从各自来源导入。随机回环供应商/合成账本下正常完成、响应头前取消、流中取消 **3 passed, 31 deselected in 0.49s**；另外“AE 实际逐连接桥→AF 原预算/持久传输→合成供应商→关闭 ACK”且模型名为精确大写的完整用例 **1 passed**。不复制修改 AF 文件，不调用真实学校，不把同进程组合冒充 RPC 已完成。
- 最终语音侧标准库模块由 Python **3.10.20** 实际运行：AC 事件、独立文本版本（audio_revision=7 而文本版本=1）、scope、准备/确认/一次领取/关闭通过；不 import 宿主 src、不联网。
- 新增源码无依赖安装、GPU、个人库、生产端口或真实学校调用。AB 快照/校验与 AI 可信跨进程链路、正式 prepare 后 fresh 验证和最终播放/字幕/归档门仍须继续接力；本阶段不会将“默认关闭/安全降级”写成总目标完成。真实上游取消只证明 owned HTTP/请求任务退出，不证明外部计算停止。

本阶段限制：主会话随后转接真实 SmartTurn 小合成中文误切未改善，enabled 尚不合格。当前 AC 事件路径只有 enabled 可准备候选，不能因此宣称日用候选已接通；AE 接续实现独立 baseline ASR 预取/原端点来源，仍保持 SmartTurn shadow 不发模型请求，AI 负责原预取钩子与宿主 RPC 的实际接线。

## 第三阶段：原 ASR 预取与原端点的独立候选来源

第二阶段提交 `07773e8ebec434bd4eecc15e7bcbf077b7272fbc` 已交主会话。为避免候选只能依赖尚未合格的 SmartTurn enabled，新增显式 `candidate_source="baseline_asr"`；原 `smart_turn` 来源保留，两个来源不能混用代次或确认权。Limits.enabled 仍是候选独立开关，默认关闭；SmartTurn shadow 本身继续不发模型请求。来源字段在 bridge.snapshot 中可见。

AI 的原 ASR 预取钩子契约如下（不用改 AC 的 shadow 事件语义）：

```python
from voice_preemptive_connection import ASRPrefetchProof, AudioStamp

bridge = PreemptiveConnections(
    rpc_preparation_model, shared_budget, limits=limits, candidate_source="baseline_asr",
)
# 原预取的ticket仍valid、status=ready且lang_tag_filter返回非空content后才调用。
proof = ASRPrefetchProof(
    ticket.generation, ticket.voice_stamp, ticket.size, ticket.prefix_digest, ticket.language,
)
binding = bridge.baseline_asr_provisional(
    connection,
    audio=AudioStamp(ticket.generation, baseline_audio_revision, baseline_cancel_epoch),
    text=ticket.result["content"], context=host_frozen_context, proof=proof,
)
# 原端点之后、完整正式ASR/正式prepare/fresh门之后调用；不是预取完成回调。
lease = await bridge.baseline_confirmed(
    connection, binding=binding, final_text=full_asr_content, context=host_fresh_context,
    final_pcm=artifacts.pcm_bytes, generation=current_prefetch_generation,
    voice_stamp=current_vad_voice_stamp, language=provider.language,
)
```

`AudioStamp.turn_id` 在此来源取原预取 generation，audio_revision/cancel_epoch 由 AI 逐连接失效钩子维护；不能拿 AC shadow 的代次替代。`ASRPrefetchProof` 只保留前缀大小与摘要，不保存 PCM。确认允许正式 PCM 追加静音尾，但前缀字节、generation、voice_stamp、language、最终全文和 fresh 上下文必须一致。核验完在等待模型/RPC之前释放额外音频引用。文本/证明修订立即作废旧候选，一代次仍最多一次请求。

续说必须在原预取 invalidate 入口同步通知 `bridge.baseline_continued(connection, audio=new_stamp)`；任何其他预取失效可用 `bridge.context_changed(connection)`，reset/close 走已交付生命周期钩子。来源为 baseline 时 reset 不读取 AC 的异名 turn_id；原端点复位后旧 generation 不能再绑定，新 generation 的首帧发声不会消耗该轮准备机会。领取前续说仍撤销凭据，最终播放/字幕/归档继续使用 AI 正式取消门。

语音侧 RPC 模型代理也必须在实际开始请求前设置 `request.close_confirmation.required=True`，由宿主内部匹配 AF request_id/账本并通过本连接 scope 的可信关闭 DTO 转告后才设 confirmed=True；不能只在客户端 finally 中无条件确认。异常或缺回执仍保持 False，由核心保留额外计算槽；ACK 本身不授权领取、提交或清理 unknown。后续冻结协议没有外部 owner/request_id 字段，既有 Runtime 鉴权负责 owner 归属，不擅增 header 或 JSON 键。

本阶段实际检查：

- 专属测试验证无 SmartTurn enabled、非空合成记忆/来源上下文可命中；原端点前无领取权；SmartTurn shadow 的任意不同 turn/audio/epoch 不会驱动 baseline 或污染其命名空间；generation/voice/language/前缀/正文/上下文变化、跨连接和确认后续说均不可领取。
- 与 AF 精确提交 `85b1d715...` 的真实 Gateway/预算/持久传输/关闭 ACK 组合：独立 baseline 来源＋非空合成记忆证据＋精确 `DeepSeek-V4-Flash` 模型，一请求一次命中，账本 attempt_count=1、unknown_or_inflight=0、锁释放；不发任何 SmartTurn enabled 事件。使用随机回环合成供应商，不是学校真实请求，也不是 AB 实际库或跨进程已验。
- AI 仍需把原预取结果、全部失效、原端点完整 ASR、AB token/内容/来源校验与宿主 RPC 接入这些方法，再验非空合成 Hy 库整链真实命中、记忆一致性及设备首声。AE 不把仅上下文的模拟命中或稳定 fallback 当作总目标完成。
- 本阶段相关五文件回归最终 **160 passed in 0.89s**；下述接口交付不修改 `launch_with_memory.py`、原 `voice_asr_prefetch.py` 或其他会话文件。

## 第四阶段：Python 3.10 真实语音RPC客户端

第三阶段提交 `44c3538acf9b3bbde8967f5af8627a66900104c6` 已交主会话。AE 随后获配 `scripts/development/xiaozhi/voice_proposal_rpc.py`，AI 独占 Runtime/internalHTTP/launch，AF 独占 `application/voice_proposals.py` 宿主。实现未导入或共享宿主 ModelGateway，也没有读取、复制学校 key。

最终协议沿主会话/AI 冻结版本：仅 POST `/api/internal/memory/proposals/{snapshot,start,confirm,cancel,close}`。从 `LONGMEMORY_RUNTIME_URL=http://127.0.0.1:<port>/api/internal/memory/prepare` 派生相同主机/端口，原 `LONGMEMORY_RUNTIME_TOKEN` Bearer 鉴权；没有外部 URL/path 参数，没有新增 key/owner header。固定表不可修改，没有正式 prepare、complete、工具或文件入口。测试仅使用随机回环端口，不触碰日用端口。

```python
from voice_preemptive import TurnStamp
from voice_proposal_rpc import VoiceProposalRPC

client = VoiceProposalRPC.from_environment(connection_id=connection_id)
scope = TurnStamp(turn_id, transcript_revision, cancel_epoch)
snapshot = await client.snapshot(scope=scope, query=full_or_prefetch_content, session_id=session_id)
started = await client.start(
    scope=scope, snapshot_id=snapshot["snapshot_id"], messages=frozen_messages,
    tools_required=False, close_confirmation=request.close_confirmation,
)
# 最终原端点、完整ASR与唯一一次正式prepare取得真实fresh messages/formalturn后：
result = await client.confirm(
    scope=scope, snapshot_id=snapshot["snapshot_id"], query=full_asr_content,
    messages=actual_fresh_messages, tools_required=False,
    formal_turn_id=formal_turn_id, client_round_id=client_round_id, session_id=session_id,
)
# result.state=adopted才有非空text；同步核对本地epoch/原派发门后才能使用。
# 每轮再用cancel确认该候选关闭；结束整个连接才close/aclose。
ack = await client.cancel(scope=scope)
```

上述是客户端入口，未把它当作 AI 预取/正式派发已经接好的生产代码。`messages` 为最多 128 项 `[role,text]`，唯一首 system，后续 user/assistant、总长 32000，**不含本轮 user**，由宿主追加冻结 query。snapshot/session/connection ID 均 32 位小写 hex，client_round_id 沿原 24–32 位 hex，formal_turn_id 必须规范 UUID；公共整数真 int、0≤x<2^63。query≤16000 字。请求≤192 KiB；确认字段使用 snapshot_id/query/messages/tools_required，未使用 transcript/final_text 别名。

响应只接受最终精确 DTO：snapshot ready/unavailable、start preparing/miss 无正文、confirm adopted/miss 的 text、cancel/close 的 cancelled/closed/closing 与 owned/provider 标记；无别名兼容或未知字段透传。start 即使响应丢失仍保留占位且不再请求，同轮最多一次；显式取消可提高 epoch，旧轮取消在本地拒绝。confirm 返回迟到时逐项核对当前 scope，陈旧文本清空为 miss，取消会中止对应本地读取任务。工具需要为 true 交宿主 miss，不执行工具。

`CloseConfirmation.required=True` 在实际 start 前设置；只有本次固定鉴权 scope 的 cancelled/closed + owned_upstream_exited=true + provider_compute_stopped=false 才置 confirmed=True。closing/false、断流、错误/缺失 DTO 不确认，aclose 返回 False。adopted 文本本身不是关闭 ACK，普通本地 socket 关闭也不是；内部精确 AF request_id/账本确认由宿主核对，未向外部协议擅增字段或清理原 unknown。当前客户端的 cancel/close 只操作候选，不触碰已正式归档的用户/助手话轮。

传输只有 asyncio/标准库：不使用环境代理、不跟随 3xx、不自动重试，错误只有固定代码。逐请求关闭 socket，Content-Length/JSON/头和正文大小有界，重复 JSON 键、异常响应、提前正文或 miss 带文本均拒绝。日志与状态只输出计数，不含 token、正文、身份、内容摘要或上游异常。

实际验证：

- 六文件回归 **190 passed in 4.38s**；RPC 专属 30 项，其中 **15 项真实双子进程**：Python 3.10.20 客户端 + Python 3.12.13 HTTP 宿主替身，均从 AE 源码/夹具执行。正式随机端口保护、两端子进程退出和本地 socket 释放均有断言。
- 双进程覆盖非空合成记忆上下文完整往返、30000 字记忆 JSON 不受 8 KiB 头缓冲误限、start 超时/断流/提前正文不重试、confirm 中取消/迟到epoch/拒绝miss正文、closing/错误ACK不退名额、重定向/重复JSON键/chunked响应拒绝、需要工具不准备模型、错误鉴权不开始候选。普通 prepare 路由调用次数为 0。stdout/stderr 另断言无 synthetic token、记忆/回答正文。
- 复跑需要显式提供本机已有 Python3.10 路径，不安装环境：设置当前测试进程 `LONGMEMORY_TEST_PY310`，运行 `tests/unit/development/test_voice_proposal_rpc.py`；未提供则跨解释器用例 skip，不能把 skip 当通过。
- 这是真实跨进程 HTTP 与协议替身检查，未声称 AF `VoiceProposalHost`、AB 真正快照、AI Runtime 路由或日用已组合验收。AI 可先合入客户端，随后用精确宿主提交验普通非空 Hy 库真实命中、取消/记忆一致性与最终派发。没有真实学校调用、个人数据、GPU、设备或服务操作，无依赖下载需求。

## 第五阶段：冻结宿主核对、strict null 与真实宿主进程装配

第四阶段提交 `d4cee7009b3e5006b03f38d98e325fbfa954b624` 已交主会话。AF 交付冻结宿主 `bf317915f6df2ba96e77be65288acc113e710906` 后，AE 只读核对五操作请求/DTO/同 loop 生命周期，与已实现客户端字段相符；未编辑 AF 或 AI 文件。

主会话进一步冻结 `unavailable.memory_context=null`、`miss.text=null`。客户端改为严格 null，拒绝空字符串、列表、对象别名；本地 no_candidate/stale 也返回 null。没有在 HTTP 薄封装中为旧宿主转换字段。核查还修复 aclose 的精确边界：同连接推进 revision/epoch 或新 turn 后，用最新 scope 结束整个连接，释放其早先待清理候选；不再拿旧 scope 向宿主发回退关闭。单轮 cancel 仍只作用于原轮，跨新轮取消在本地拒绝。

新增 `tests/fixtures/voice_proposal_rpc_real_host.py` 是测试 HTTP 薄封装，**不是 AI 正式路由**。父测试从指定本地 Git 对象 archive 公共 AF src/测试夹具到 AE 的唯一临时目录，逐目标核对路径在临时目录以内；AE 控制器取本树 HEAD 原字节并核对一致。Python3.12 宿主子进程运行真实 VoiceProposalHost、真实 Gateway/预算/持久传输及合成 Runtime；Python3.10 语音客户端仍只导入 AE 标准库模块。没有导入脏树、供应商真实地址或个人库。

合成 Runtime 最少固定画像1＋normal fact4＋proactive intent1共六项，内容、source_event_ids、顺序与候选回执一并比较；网关实际请求的 system 内容需包含全部六项，不能因总数5限制截断或只用一项小库。预备四场景：实际采用一次、响应头前取消、流中取消、formal fresh 不符时 miss；取消需保留真实原账本 unknown，owned 句柄和两进程正常关闭。

已实际复现冻结 bf317915 的已知阻塞：六项请求在 snapshot 被总限5拒绝，旧 unavailable.memory_context 为空字符串；严格客户端报告 `proposal_rpc_snapshot_invalid`。独立子进程证据为 snapshot 1 次、上游 attempt_count=0、unknown=0、正常清理，没有发出 start 或偷偷截断。该用例本轮 **1 failed**（按已知缺陷取证，不是通过）；AF 的 null/分通道修复由主会话转接，尚未将其脏树当修复提交使用。

真实宿主用例显式设置 `LONGMEMORY_TEST_VOICE_HOST_REF=<40位冻结提交>` 后执行；没有该值四例 skip，不把 skip 当集成通过。仅 native client/协议替身和本地清理回归目前 **35 passed / 4 skipped**；实际修复宿主与真实 Hy/正式 Runtime 最终整链仍须继续接力。
