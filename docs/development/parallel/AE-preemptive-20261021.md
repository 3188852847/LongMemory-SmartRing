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

## 已实现接口与接力

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

`voice_preemptive_stream.GatewayPreparationModel(open_response, model="deepseek-v4-flash", campus_free_verified=True)` 的 `True` 必须来自实际网关策略核验，不是 AE 提供的免费证明。模型也支持现有 `deepseek-flash` 别名。注入 `open_response(payload)` 为异步上下文管理器，返回具有整数 `status` 和按行异步迭代的 `content` 的响应；退出必须关闭响应，取消发生在建立响应途中也须清理。该窄接口交 AI/AF 适配现有已授权网关/连接池，不在 AE 新开真实连接池或绕过调用门。

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
