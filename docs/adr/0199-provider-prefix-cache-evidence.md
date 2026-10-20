# ADR-0199：前缀缓存以供应商计数取证，网关不重排请求

- 日期：2026-10-21。
- 状态：AF 候选实现与隔离验证完成；学校缓存支持仍未确认，尚未部署日用。
- 范围：自有模型网关的内存诊断与独立六次合成实验。补充 [ADR-0191](0191-hy-short-input-and-owned-provider-session.md)、[ADR-0192](0192-owned-answer-content-boundary.md) 和 [ADR-0193](0193-owned-voice-system-instruction-placement.md)。真实结果见 [AF 记录](../development/parallel/AF-prefix-cache-20261021.md)。

## 决定

网关不移动、合并、删除或缓存输入消息，不缓存回答，也不发送保活或预热模型请求。保留首部 system、原角色、记忆证据与 user 问题的边界、原历史及工具配对；提取通道的中文约束照旧。精确时间或记忆变化造成的前缀不稳定，不通过冻结时间、复用旧记忆或省略规则来消除。

在原 `responses` 内存诊断中增加 `cache`、`model_ttft_ms`、`provider_elapsed_ms` 和流式 `finish_reason`。不新增数据库表或持久日志，不改变 HTTP 响应、费用结算、unknown 保留和运行时所有权。`cache` 只含固定状态、计数来源、命中/未命中 token 数和完成标记，不含提示词摘要、正文、用户标识或凭据。

缓存证据优先接收 DeepSeek 的 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`；兼容接收 `prompt_tokens_details.cached_tokens`。计数必须是非负整数，拒绝布尔值；若提供总输入数或两种格式，必须一致。四种状态为 `unknown`（字段缺失）、`invalid`（计数不可信）、`reported_miss`（明确报告零命中）和 `reported_hit`（明确报告正命中）。未完成响应另保留 `completed=false`。零命中和缺字段都不能解释为“不支持”；耗时改善不能替代命中证据。供应商计数证明的是其报告，不是对后台实现的独立审计。

TTFT（模型首个有效文本时间）起点位于预算预留后、调用传输前；包含连接/传输初始化和服务端等待，不包含网关锁队列、ASR、记忆和播放。终点在既有 `FinalStream` 推理过滤后首次出现非空白 content；role、工具参数、独立 reasoning 字段、开头显式 think 块和空白均不计。非流式请求只有完整响应耗时，TTFT 保持空值。这里不测“用户说完到首个有效声音”，也不把任何模型文字自动判定为正确答案。

## 有界实验

默认命令仅显示计划，不读凭据、不联网。真实模式要求主会话调度标识、所有者根路径和本工作树内新的实验目录；再次核对当前 web/voice 都选中 campus、精确模型 `DeepSeek-V4-Flash`、免费策略绑定的端点与凭据。不允许回环/日用端口或官方付费端点，不向日用网关发请求。复用现有免费策略的验证入口只读校验原账本身份；reserve/finish 仅作用于专属实验账本。策略缺失则停止，不回退到无账本直连。

固定两组三次：前端随机合成标识的新前缀/新会话、原样重复/同会话、原样重复/新会话。每组消息与参数字节等价；两组更换合成标识。每次输出最多32 tokens，禁用思考、无工具、无历史和记忆，串行、无重试。两次重复前各等两秒，但不假定学校缓存落盘时序与官方相同。第一条称 `cold_candidate`，不能宣称已清除服务端缓存；“hot”只表示重复条件，也不预判命中。

至多六次，首次 HTTP/流式/usage 失败即停，不补样。响应只在内存中有界比较是否为预期合成短答，落盘仅保留布尔结果、token 白名单计数、耗时、结束状态、合成 payload 摘要、代码摘要及账本审计。不保存原始回答或提示词。学校免费按所有者确认记录个人成本零，不套用官方缓存价格推算学校费用。

## 代价、结果与回退

网关每次增加常数级计数校验和计时，不新增依赖、线程或后台请求。新增字段仅供内部审查；暂无前端/日志落盘接线。可以随候选提交撤回，既有库、来源与预算无需迁移。

本轮获批六次均完成，常规 usage 存在，缓存字段均缺失。重复请求更快，但样本量、客户端冷启动、排队与未知服务端实现均不能排除，故缓存仍未确认，不报告 P95 或缓存因果收益。日用可保留已有连接复用；候选观测可由整合方审查后接入，不存在需要 AF 擅自打开的缓存开关。

## 一手依据

[DeepSeek 官方上下文缓存说明](https://api-docs.deepseek.com/zh-cn/guides/kv_cache/)于2026-10-21核对：官方自动缓存前缀，返回命中/未命中计数，落盘为秒级且尽力而为；当前说明按完整前缀单元匹配。该能力与具体规则只归属于官方服务，不能直接归属于学校接口。这里保留字段缺失的证据边界，不据此猜测学校引擎、路由或缓存实现。

## 第二阶段补充：宿主候选响应句柄

主会话新增授权要求将 AE 的候选消费接口接入原网关。候选只能从宿主现有 `ModelGateway` 对象取得绑定，不能在语音进程复制供应商凭据或另建直连。`candidate_response_binding()` 重新核对当前 `FreeCampusCalls` 政策完整字段、端点/凭据摘要、精确模型、所有者免费确认和同一账本身份；有原构造布尔值但无绑定证据仍拒绝。付费网关不导出此接口，不修改旧 unknown 或付费账本。

导出的 `open_response(payload)` 创建异步上下文句柄，提供整数 `status`、逐行异步 `content`、随机 `request_id`、`cancel/aclose/wait_closed`。创建本身不联网/预留；进入时复用网关同一 `_paid_lock`、`reserve('answer')`、持久传输会话、活动登记和审计。请求只允许冻结的首 system、user/assistant 历史及末尾当前 user，最多32000字符、输出256 tokens、n=1、stream/usage、禁用思考、tool_choice=none，无 tools 或额外参数。上游计时10秒到期显式取消；退出清理没有伪确认超时，调用方可以有界等待但并发名额继续保留。

候选严格检查单一choice、assistant delta、无工具/函数调用、正常stop、完整DONE及有效完整usage；开头显式think与reasoning字段不输出。只有完整消费、正常退出并取得本地上游关闭确认才按原免费规则结算；取消、非stop、断流、错误或不完整usage仍记unknown。元数据追加在原 `responses` 与 `gateway_results`，`candidate=true` 只在内存标识，`forwarded=false` 明示没有正式输出；不添加库表、正式对话、检索、归档或播放操作。

`cancel_candidate(request_id)` 只查候选句柄表，与正式调用ID隔离。取消在首响应头前也直接取消自有传输pump，不依赖下游HTTP断开通知。`wait_closed()` 的ack含 `owned_upstream_exited=true`、`provider_compute_stopped=false`、`ledger_finalized` 和 `usage_settled`。它在pump任务实际done、响应释放和账本审计之后返回；重复取消不会中断关闭或提前退锁。ack只证明自有请求任务退出，不能证明供应商GPU停止或释放外部未知费用。生命周期方法限定同一宿主asyncio循环。

该接口当前只证明Python3.12宿主内部闭环。真实小智Python3.10是另一个进程，跨进程能力、调用者/connection/epoch作用域和取消ack的可信传递由主会话/AI协调；本阶段没有新增HTTP/RPC端点，也未宣称语音实际已接线。AE基线只接受小写别名，AF返回实际学校精确大写模型名；协调AE兼容，不静默替换模型。隔离组合与未验证项见AF记录。

## 第三阶段补充：宿主受限候选编排

主会话进一步分配 `application/voice_proposals.py` 给AF，实现 `VoiceProposalHost(runtime_provider, enabled=False)`。宿主取得的是现有Runtime的同步非阻塞getter，不执行bootstrap或懒创建；默认关闭时连Runtime、AE和工作线程都不初始化。鉴权、HTTP大小/来源守卫与关闭钩子归AI；语音进程只能访问该内部RPC，不能取得供应商密钥或引擎快照令牌。对外DTO由AI冻结，详见AF第三阶段记录。

只读快照经Runtime现有CPU嵌入和Hy无写候选路径，随机snapshot ID绑定本host实例、连接、轮次、ASR修订、取消代次、问题、session与Runtime实例，令牌仅留宿主。AE控制器使用实际已核验的原gateway绑定，复用一个全宿主预算：并发1、累计20次、160000输入字符、5120输出tokens；单候选沿AE默认2秒生成、3秒ready、256输出tokens。宿主另限16连接、200个非清理操作、每连接1份10秒快照和2个Runtime物理线程。线程超时后名额保持到实际退出，不堆积新的隐形任务。

start传入唯一首system的 `[role,text]` 冻结上下文，服务追加已冻结query，不重复本轮user，不调用prepare、归档、工具或TTS。confirm要求完整实际消息、问题及同一session；先取得AE候选凭据，再在worker中调用Runtime的 `claim_candidate_memory`。该方法在同一Runtime临界区内比对真实正式prepare的正文/来源，fresh校验令牌，并经同步回调领取。回调通过有撤销门的有界线程→loop桥，在原loop同步调用AE领取，绝不从worker直接操作控制器，也不先放Runtime锁再await领取。

同步等待超时与外层取消先撤销同一原子门；已进入loop领取时worker须等它结束才放锁，尚未进入时迟到回调不得领取。取消、新轮、修订、Runtime替换或host关闭同样撤销门；结果回到loop后再检查代次才返回text。每轮只调度一次模型，prepare与confirm不自动重试。关闭确认沿AF句柄和AE实际request ID核验，未确认返回closing并保留计算槽；ACK不等于远端GPU停算。此阶段无持久模型/库迁移，只在内存保留有界候选与临时来源证明。

隔离测试已组合实际AF gateway/transport/SQLite、AE `44c3538` 控制器以及AI候选Runtime方法的只读源码快照，包含一次成功与正文/来源/token/fresh负例。它证明宿主接口能执行；AI的真实跨进程HTTP及AE语音桥仍须在其组合树连接验证，不以同进程测试或本地替身冒充日用上线/实机通过。第三阶段学校真实调用为0。
