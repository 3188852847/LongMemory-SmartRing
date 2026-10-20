# ADR-0198：从无副作用快照准备可取消的回答候选

2026-10-21。状态：候选模块已实现，待 AB/AC/AF/AI 组合审查；未切换日用。编号由主会话预留。

## 事实与决定

正式 `MemoryRuntime.prepare_round_screen` 不只是检索：它预留圆屏账本、调用 `prepare_user` 归档来源、保存 prepared/feedback，还可能进入管理或延后提取路径。现有 Hy `recall` 也明确报告 `hy_recall_may_mutate_state`。在最终话轮结束前调用这些入口，即使最终丢弃回答，也已经留下来源或 pending 副作用。

提前生成只接收已冻结的消息与版本；模块不接收 Memory、prepare/search、管理操作、工具执行、字幕、TTS（语音合成）、播放或归档接口。不把正式入口包一层后称为 proposal-only（只提案）。AB 必须另行证明快照获取本身不归档来源、不创建 pending、不提取/整理或修改管理状态；证明或版本契约不具备时保持关闭。

AC v1 提供逐连接 `turn_id/audio_revision/cancel_epoch`，其 `transcript_revision` 始终为 null；AE 用实际 ASR 文本独立产生文本版本，不能用音频版本代替。AB/AI 提供 `memory_revision/context_revision/tools_revision/policy_revision`，覆盖引擎重启、并发记忆写、消息、日期、角色和模型策略。每轮最多一个候选请求。继续说话、转写修订、新轮次、上下文/工具/策略变化、超时或关闭，先同步清空并撤销候选，再取消模型流。不能因传输吞掉取消而让最终端点一直等待，也不能在流实际退出前释放并发名额。

确认必须与转写全文、三项话轮标识、四项版本及冻结消息完全一致。确认只产生一次性凭据；正式派发前再核对并领取。凭据不是播放授权，AI 仍须在同一事件循环中使用正式话轮取消门，领取与检查/入队之间不能插入 await。正式 prepare/归档只能在确认后由原链路执行；其结果改变上下文、工具或管理状态时必须废弃候选，再走正式回答。预测不写磁盘，重启不扫描恢复或重放。

模型准备仅支持经过核验的学校免费路线，不启用付费回退或自动重试；不改旧付费冻结额度和 unknown（用量未知）账本。AE 的跨连接并发、累计请求/输入字符/输出 token 预留是额外计算限制，取消不返还累计额度；它不是费用结算凭据。AF/AI 的响应上下文管理器保留原网关账本，负责真实取消/关闭和连接池生命周期。准备期只消费最终文本，复用既有显式 think 解析器，拒绝工具调用、截断和不完整流，不做 TTS。

## 第二阶段连接与进程边界

候选容器与影子统计都只挂在连接实例，不读类级候选。AC provisional 没有提交权；shadow 不启动候选模型。enabled confirmed 只记录音频端点，实际完整 ASR 文本和正式 prepare 后的 fresh 快照仍须由 AI 核对。工作线程到达的取消先设置线程安全领取隔离标记，再投递到事件循环；音频/转写/上下文的晚到旧对象不能重新激活候选。

小智 Python 3.10 与宿主 Python 3.12 分进程。语音侧 `PreemptiveConnections` 通过 AI 可信 RPC（远程过程调用）模型代理调用宿主；宿主 `GatewayPreparationModel` 进入 AF 同一个预算/连接池。不得以同进程测试中的注入对象冒充跨进程已接通，也不把供应商密钥交给语音进程。`ModelRequest.scope` 含临时 owner/connection 随机标识及准确的音频、文本、取消代次；它们不是鉴权凭据，宿主仍须验证真实调用权限与归属。

AF 句柄须提供 request_id、cancel/aclose/wait_closed。AE 严格核对请求 ID、owned_upstream_exited 与账本状态；客户端关闭不等于自有上游退出。关闭回执失败时即使任务已结束也保留计算占位，aclose 返回 False；后续可信回执才能释放。这个确认只覆盖自有上游 HTTP/任务，不能证明外部供应商 GPU 已停止；unknown 仍由原账本保留。

SmartTurn enabled 尚未达到真实中文误切标准，不能把它作为候选准备的唯一入口。独立来源 `candidate_source="baseline_asr"` 使用原 SenseVoice 预取正文与其 generation/voice_stamp/language/PCM 前缀证明准备候选，仅原端点后的完整 ASR 与 fresh 上下文可确认。SmartTurn shadow 事件不驱动此来源，也不改变原端点。AI 拥有预取结果/失效/reset/close 钩子与进程间接线；不能只打开开关而漏接取消。来源的音频标识来自原 ASR 代次，不与 SmartTurn 的 turn_id 混用；文本版本仍独立产生。

## 语音RPC客户端

`voice_proposal_rpc.py` 使用 Python 3.10 标准库，只从现有 runtime prepare URL/TOKEN 派生同一 127.0.0.1 authority 的固定 `/api/internal/memory/proposals/{snapshot,start,confirm,cancel,close}`，没有普通 prepare/complete/工具路由、学校凭据或宿主对象。五项请求精确字段与 state/text DTO 由 AI 冻结；预处理 messages 不含本轮 user，宿主追加冻结 query。调用不重试、不跟随重定向、不读取代理；响应/请求有界，取消关闭本地 socket，但不冒充上游已退出。

客户端逐连接固定 connection_id，维护不可回退的话轮/文本/取消版本；start 至多一次，旧轮取消不能影响新轮，取消允许提高同轮 cancel_epoch。迟到或取消中的确认文本不交付，start 响应不允许带正文。返回 adopted 文本也不自动释放计算槽，仍需 scoped cancel/close 的明确关闭确认；closing/false、断流或鉴权错误均不能假释。外部 DTO 不扩展 AF request_id/账本字段：宿主负责核对完整内部 ACK，客户端把可信固定路由的一次响应绑定到对应 scope。

后续协议收紧为 unavailable.memory_context=null、miss.text=null，客户端不接受空字符串别名。整个客户端关闭使用最新 scope，允许封闭同连接更早的待清理候选；单轮 cancel 仍不能跨到新轮，以免把清理旧请求变成取消新请求。跨进程实际宿主测试至少提供画像1/fact4/intent1六项，逐项核对内容/来源并断言全部进入真实网关消息；小库通过不能替代分通道上限及真实 Hy/正式 Runtime 验收。

真实 Python 3.10 客户端与独立 Python 3.12 HTTP 宿主替身验证的是跨进程协议、取消和资源边界，不是 AF/AB 实际宿主或设备链路已接通。实际 Runtime 路由、预取钩子和统一派发门仍由 AI 接入与验证。

## 验证与回退

合成测试覆盖确认/领取、续说与 ASR（语音识别）修订、版本变化、迟到/乱序事件、取消不服从及关闭等待、超时、重启、预算、工具/推理边界和正式合成 SQLite 账本。测试证明模块的候选边界，不证明实际 SDK 快照无写入，也不证明学校连接池、真实费用、端到端声音延迟或设备体验。

默认 `Limits.enabled=False`。未接候选或关闭开关即可回退原 buffered（日用缓冲）链路，不迁移数据库、不更换角色/声音、不动固件。接口及本轮实际结果见 [AE 记录](../development/parallel/AE-preemptive-20261021.md)。设计参考 [LiveKit 官方提前生成说明](https://docs.livekit.io/agents/multimodality/audio/#preemptive-speech-generation)，未引入 LiveKit 依赖。
