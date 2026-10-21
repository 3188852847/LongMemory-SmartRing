# ADR-0201：组合接线的 Runtime 写门与只读观测

日期：2026-10-21。状态：隔离实现，正式部署与真实模型/设备验收另行记录。范围为平台公共 Runtime、Hy 专属 HTTP 和语音子进程启动接线；不改变记忆核心协议或生产默认设置。

## 问题与依据

AB 的 L6/L7 使用持久后台任务，原 Runtime `write_enabled` 只控制同步入口。若未同步后台队列，网页暂停记忆写入后仍可能认领新任务。管理 proof（证明回执）依赖后台关闭的旧条件，不能用新开关替代真实一致性验证。另有 AC/AD/AE/AF/AG/AH 分支需要组合，但它们的软件接口、真实模型能力和设备体验属于不同证据边界。

## 决定

1. Runtime 在初始化时，以及 `write_enabled` 实际变化时调用方法的 `configure_background_writes(write_enabled=...)`。旧方法没有该能力则保持原行为。后台同步失败时前台写门保持暂停并返回稳定失败码，不谎报已暂停所有线程或回滚已认领任务；其他配置不先行生效。
2. `semantic_enqueue` 在 Runtime 同一串行锁及前台写门内执行。cancel 只尝试阻止尚未认领任务，暂停时仍允许；AB 的实际结果决定 prevented_start / already_claimed_no_rollback，不扩大到 SDK 原生回滚。
3. `semantic_status/task` 仅窥视已有 Runtime，非阻塞取锁；没有实例或忙就返回明确不可用。读操作不调用 Runtime.status 的圆屏过期处理，不懒创建引擎，不运行普通 search 或模型。pause 只供可信内部同步，HTTP 不暴露。
4. HTTP 只开放固定状态、单任务、enqueue 与 cancel。沿现有会话/CSRF（跨站请求伪造防护）与启动管理权限；参数不接受用户/来源/库路径/执行未来意图等字段。读响应为 AB DTO（数据传输对象）顶层，追加 UTC 读取时间，status 追加当前 Runtime 写/用门；附加字段冲突时拒绝，不覆盖原字段。`observed_at` 不是任务完成时间。
5. 语音安装顺序为输入计时 → ASR 预取 → 话轮层 → 已有响应/音频/归档层。话轮 off 不加载推理依赖；缺少固定模型或依赖明确 unavailable，已请求 enabled 但缺校准证明时不激活。声音默认 buffered，incremental/adaptive 只在显式进程参数下选择，不回写声音档案。候选提前生成仍须真实快照/网关/取消/正式提交门齐备，不安装空实现宣称完成。
6. 候选只通过既有内部鉴权的五种固定RPC与3.12宿主通信。实际模型、政策、CPU向量器与供应商凭据留宿主；小智3.10不导入宿主对象。平台包装器显式委托后台门和专用候选读取/校验，不增加任意属性或SDK方法穿透。候选不能调用正式prepare、归档、完成、普通recall或工具执行。
7. 正式prepare仅在内存保留最多64条、有效30秒的本轮身份/查询/上下文/完整证据摘要，无新持久表；完成/取消/关闭撤销。采用时在Runtime锁内复核本轮ID、session、查询、正文/来源全序、Runtime及引擎新鲜版本，再同步单次领取；不能自行伪造正式上下文。管理纠错/删除尝试在来源归档前撤销旧候选，即使失败留下uncertain且SDK正文未变也不复用。角色、实际模型当前消息、历史、时间与工具策略由语音到宿主的完整载荷另绑定；实际ASR JSON消息与记忆查询不同的问题尚待接线验证，不把标准文本合成测试当其已解决。
8. 主会话冻结兼容输入演进：外层version仍1，snapshot仅保存记忆查询query；start/confirm新语音链路必须同时带`input_protocol:2`及不改写的`model_user_message`。messages仍不含本次user，宿主追加真实当前消息；query仅用于记忆与正式回执校验。旧无附加字段请求仅保留query等于模型当前纯文本的兼容，实际语音桥不得退为旧格式绕过元数据比较。新字段必须成对、协议值为真整数2；实际模型当前消息与历史合计上限32000字符，原192KiB请求体上限不变。响应与鉴权不变，AF宿主/AE客户端的真实接线仍须分别验证。

## 兼容、回退与验证

旧 Hy 图关闭/后台关闭的 proof 继续只适用于原模式。L6/L7 的协议 2 proof、最终源码摘要及真实管理/派生一致性由 AB 与组合验收提供；本 ADR 不授权重签生产回执。新增任务/Kuzu 状态的备份必须遵循 AB 的完整资源边界，不迁移或批量改写个人库。

融合`f5906827`已通过固定真实SDK/正式HTTP/Python3.10等219项、零skip；既有离线回执工具在前后源码/解释器身份一致后实际生成协议2候选，路径及摘要见AI任务书。输入协议2的完整消息保真与正确miss已验证，生产ASR预取→RPC→最终模型采用桥仍未安装，由AE独立接续；当前配置有搜索工具，候选必须关闭。生成候选不等于已部署、真实模型质量或设备体验通过。

2026-10-21完整CI入口追加发现并修正公共边界：平台round反馈返回字典或None，资格判定不访问对象属性；任何识别到的反馈（含跨session未记录）都不得采用已有候选，候选宿主关闭时原反馈路径同样须正常。Runtime以中立`MemoryReadBusyError`报告未取得只读快照，具体Hy异常留方法/入口；HTTP继续返回原busy/503。候选宿主自行等待其清理任务完成再传播取消，不反向导入Hy传输模块。此修复不放宽架构测试，不改变SDK管理原语或持久模型；受影响真实SDK/HTTP/RPC回归单独记录，旧219回执不冒充新增代码的完整证明。

HTTP 的 400 表示请求不合规；401/403 沿既有会话、CSRF、启动权限与写门；404 任务不存在；409 冲突/操作拒绝；501 后端不支持；503 忙、不可用或结果不确定。只读状态不自动授权执行未来意图或主动联系。没有设备回执时发送完成不表示已播放。

退回原行为可在下次启动选择话轮 off、声音 buffered；不在已安装包装器的运行进程中切换。正式发布由主会话安排，本文不包含停机、下载、GPU 或设备操作授权。独立验证及未完成项见 [AI 任务书](../development/parallel/AI-hy-advanced-low-latency-20261021.md)；不能把合成回放通过替代实际 SDK、中文模型、GPU 连续播放或圆屏体验。

## 2026-10-21：AE正式启动融合（默认关闭）

AE四个精确提交已接入AI分支，公开启动器新增 `--enable-voice-preemptive` / `LONGMEMORY_VOICE_PREEMPTIVE_ENABLED=1`；仅pipeline/realtime允许，错误组合在加载厂商或私有配置前拒绝。语音默认不安装候选适配器，宿主原 `LONGMEMORY_PREEMPTIVE_ENABLED` 默认关闭，两个开关分别控制两侧；本文不授权生产启用。

安装顺序补齐为输入计时 → ASR预取 → SmartTurn → 快捷回复/计时/完成捕获 → adapter生命周期 → 创建连接。adapter必须包住会提前返回的快捷回复，才能收尾未采用候选；连接初始化时 `_ObservedLLM` 根据所属Connection类仅绑定私有provider代理，不修改共享provider。完成捕获器安装后调用可选 `guard_history`，在记录助手文本前重套撤权门；无需进入provider的固定回复也不能先记下撤销文本。

正式能力回调沿实际intent和provider方法判断：function_call存在合法handler时，即使工具描述列表为空，上游仍会追加direct_answer，必须按有工具处理；不调用会写缓存的get_functions。配置搜索且provider支持functions时，在任何候选RPC前跳过；intent_llm/未知路径和无法证明可复用的精确时间路径保守跳过。保留正式搜索能力、工具编排及实时时间，不把预览时间写回正式消息。

确认仍只有原0.3秒预算，超时走一次原正式回答并关闭候选，不重复prepare；增加仅计数的confirmation_deadline/confirmation_failed，避免将有界回退与输入miss混为一类。合成屏障另验证确认永不返回时的资源收尾。真实SDK/3.10/正式RPC组合使用提交冻结源码和真正公开启动回调/自动绑定，结果与首次失败证据见AI任务书；旧219项及协议2管理proof不改写为新桥的验收。

## 2026-10-21：ROOT发布报告与实机失败边界

ROOT主会话报告：候选Quality39518824436在冻结944b83ba全success后，main已快进/普通推送并完成owned检查点与新bcde前端部署，control/runtime及TTS warm ready；执行路径、摘要与会话追溯见[AI任务书发布收尾](../development/parallel/AI-hy-advanced-low-latency-20261021.md)。AI仅维护该报告，没有操作生产或独立测量发布状态。ROOT补充main自动Quality39520018676的frontend failure为MemoryApp日常纠正、RoundDisplay皮肤等待回读两项组件用例5s超时，根因仍待AH查明；该次main已completed failure、backend success，同提交候选已绿不能改写为main也绿，不rerun充绿或放宽5s。

本次启动请求保持host/voice候选均关闭、话轮结束识别off，仅通过子进程环境请求CosyVoice adaptive，持久配置字节不变。接口未暴露实际声音模式，故不能据启动参数/ready声称已证明真实adaptive播放；此后所有者反馈字幕大量遮挡、无法打断，本次adaptive实机验收FAILED，不能按通过收尾。ROOT随后报告buffered已通过owned重启恢复并ready，launcher9680；私有配置字节保持，不回滚已有真实会话的个人库或944代码，恢复ready不等于修复字幕/打断；adaptive未被接受为持久默认。首次SDK失败原因未定位、跨标签同时冷启动不覆盖、SmartTurn off与TRT无真实engine等边界保持；原219项proof仍属f590固定实现，不重签为944证明，不将发布ready当全部技术启用或设备验收。


ROOT已保存失败时序元数据和所有者拒绝记录，将音频/自然打断修复交AD、字幕适配交AH；AI仅维护记录并保留后续整合审查角色，不直接消息AD/AH，不操作服务、个人数据或固件。暂停新增特性/AG试验，保留944业务与候选CI真实通过历史；buffered已报告恢复，缺陷修复和重新实机验收完成前不按已验收归档。详细证据文件名及任务追溯见AI任务书。


ROOT另报告AH正在准备字幕bottom复位/圆形安全区的隔离审计补丁与离线计划，尚无固件写入许可；AD复现client_abort可复位而旧轮缺永久撤权的上游代码缺口，尚不能据此认定实机根因。AI等待补丁交付后审查，需要helper装配时再独立整合，当前不改944冻结业务；所有者“圆边裁字幕、stop识别后旧声继续”的FAILED结论保持。

## 2026-10-21：打断修复的隔离决策

普通回答的音频/助手历史/完成回执使用永久输出租约，不依赖可复位abort布尔或AE开关。实际executor.submit捕获代次，阻止旧排队工作重新prepare；助手put与撤权共屏障。MemoryProvider的pending领取是完成线性化点：先Memory锁，再短音频锁和wire状态锁，在有效身份下检查并pop；不得持音频/wire锁等Memory锁、RPC或磁盘。领取前撤权走cancel；已经领取且外发的完成不承诺回滚。固定原生ASR/chat、真实provider及合成回执覆盖候选关闭与外层检查后撤权竞争。

显式设备撤尾采用[合同修订4](../development/parallel/AD-tts-interrupt-v1-20261021.md)，双向严格hello、当前连接单调epoch、所有实际ws.send同门。普通EOS只关接收且保留已收音频；后续明确打断仍可撤同epoch的尾音，不能因server stop返回假定设备已播完。设备以不可复用本地通道/输出代次隔离解码、PCM和UI，正常排空计入已出队活动任务；不增加物理播放回执。

声音HTTP仅对尚未生成的精确503 busy开放一次400ms重试准入窗口，首请求与200后的生成读取保留原超时，避免重放已开始的合成。固定源不兼容或wire覆盖改变时拒绝协商/关闭本连接，不悄悄声称即时flush。`tts_interrupt`与`voice_interruption`均为有限只读摘要，缺旧可选字段仍兼容，已知字段非法返回稳定502；计数、配置、客户端路径与物理播放保持独立。

字幕/消费者候选与联合审查结果见[AH记录](../development/parallel/AH-round-subtitles-20261021.md)和[AI记录](../development/parallel/AI-hy-advanced-low-latency-20261021.md)。本地合成/源码抽取验证和容量只支持下一阶段审查；生产部署、精确候选远程Quality、新0016应用写入授权及owner体验仍另验，当前实机FAILED不改写为通过。
