# AC：2026-10-22 播放期漏检定位

基线 `8617911795ede87456b4805a2f32f45356ecdea9`，隔离分支 `codex/ac-vad-trace-20261022`。旧 SmartTurn、融合和数值观测分支及其未合工作保留。本轮只读核对源码及 ROOT 指定的 AD 白名单数值；未操作日用服务/配置、模型/GPU、原音频、日志正文、个人库、串口或固件，未修改算法或诊断 schema。

ROOT 转述所有者在 adaptive 本轮报告“停一下未显示、旧声音继续”，并已停止本轮、正式回 buffered。buffered 历史也有间歇漏检，不能先归因增量。所有者反馈、代码事实、数值事实与待验证解释分别保留。

## 入口与可验证断点

已核对 [启动顺序](../../../scripts/development/xiaozhi/launch_with_memory.py)、[直连 v2](../../../scripts/development/xiaozhi/direct_ws_v2.py)、[输入观测](../../../scripts/development/xiaozhi/voice_input_observation.py)、[VAD 数值](../../../scripts/development/xiaozhi/voice_vad_signal_observation.py)、[诊断投影](../../../scripts/development/xiaozhi/voice_signal_diagnostics.py)、[输出撤权](../../../scripts/development/xiaozhi/voice_interruption.py) 与固定 [上游输入 fixture](../../../tests/fixtures/xiaozhi_input_snapshot_eb4b28c.py)。已安装包装后的实际链路为：

1. Opus 解码；直连 protocol 2 在时间戳非零且 `client_aec` 时调用服务器 AEC。`decode_return` 因而可能已是 AEC 后值，真正的服务器 AEC 前后值分别为 `aec_input/aec_output`，不能按上游 MQTT 路径推断直连不经过 AEC。
2. 入队、ASR 工作线程出队，线程等待每次 `handleAudioMessage` future 完成，再处理下一包。
3. Silero 每512样本原次推理；高/低阈值及五格窗口形成 have_voice。内部异常可能被吞后返回 None，由新观测单独分类。
4. `client_aec`、have_voice、`client_is_speaking` 均为真且非手动模式时，先 await abort，再继续 no_voice/receive_audio。
5. 句尾正式 ASR 在缓存长度严格大于 `1920*15` 字节时启动；非空 ASR 交接另有输出撤权补偿，额外参考输出生命周期，不能把它计作 VAD 即时打断。

因此：上行/出队不增长先查输入与调度；VAD 检查增长而判定全 False 先查声学输入及概率；VAD 阳性却无 abort 才查唤醒跳过、AEC/播放标志/手动模式谓词；abort 进入不返回查控制发送等待；abort/interrupt 已返回而旧声继续才进入 AD/K 的输出与设备缓冲范围。正式 ASR 长度门可以解释部分无字幕，不能单独解释 VAD 阳性本应先触发的即时 abort 缺失。

本机固定外部 `receiveAudioHandle.py`、Silero、ASR base 的 SHA256 与 fixture 已知源一致，分别为 `4493dfd77c1bfa7be1a79bb293dbdbf8cad64a6eb2bc53efca3e30efefcb47f1`、`aa375cd237c262338b391f8826f35bfe9b3c9e4c77a197bfe75490806d825114`、`929532c379d18598eff6fbecb991089f25a0c62cd77f74a25a0d1a5b8d13a713`。这是文件核对，不是生产进程内代码指纹或模型指纹证明。

## AD 原始白名单的独立复核

来源为 ROOT 明确提供的 `ad-adaptive-observe-20261022-01` 中 `samples.jsonl/summary.json/analysis.json/event-timeline.json`，未复制原始数值文件入 Git。原 samples SHA256 `776f7b4137e3dc624249b980e0a1af8853ce37b508306bdb9006ed4fd0398f46`，summary SHA256 `d935271b9f682290f95a879bb07feba912e8f4f974f4acb986f0f2dcf9f0b93e`。

- 北京时间10:40:22.694–10:42:45.698，共144组，两个请求均返回200，无请求失败。在线64组，最后在线10:41:25.697；10:41:26.684起断线。断线后的无连接值不是零输入的在线观测。
- 连续在线采样首末可见计数差：queue_put、queue_get、vad_check 各 +732，vad_speech +48。它们是device端点背景，不构成跨端点同连接或原子证明。每个采样点 queue_depth=0，各阶段 inflight=0；支持没有采样到持续积压/等待，不能排除采样间短暂等待。
- 播放分组 vad_input/vad_false 各 +653，无新 vad_true；原次 inference_return/probability_le_low 各 +1224。加载合同固定 high=0.5、low=0.3、silence=600ms、window=3；这1224次全部低于/等于0.3，不支持“已越过高阈值，只被三格窗口挡住”的解释。播放累计概率最大0.1326246，已存在于首样本，不能称为本段新增最大值。
- 非播放分组新增79包，vad_true +48、vad_false +31，原次推理 +148、probability_ge_high +86。模型并非全时段不工作；也不能将这些非播放阳性归给所有者那句“停一下”。该分组 AEC 计数由 null 变为2，属于首次可见计数，不能直接按通常整数差分漏掉或把 null 任意算成确定零。
- 播放分组 AEC input/output 各 +615，对应非零时间戳/参考存在均 +615；最新最近参考时差为0。支持实际服务器处理与参考存在，不只能力声明；不能据“最近”推断算法最终选中的参考，也不支持将“缺参考/旧参考”直接当作本次根因。
- 10:40:28.686 首次看到本段唯一新增正式 ASR、非空结果、ASR交接撤权、清队列、abort 开始与返回各 +1；之后至断线无新增。首样本已有一次正式 ASR，采样无零点、无内容、无精确发声标记，不能把这唯一新增 ASR 归给停止口令或算作播放期 VAD 打断成功。
- endpoint_length_rejected、just_woken_skipped、route_no_enqueue、vad_error、observer_error、upstream_abort_revoked、stale_packet_dropped 均无新增；新数值旁路也未记到 None、推理异常、输入合同错误等事件。只覆盖本轮已观测路径，不能推广为所有错误均不可能。
- 10:40:29.696 时输出 active；后续播放期输入持续判 False。约10:41:06后检查停在802，输出 active 到10:41:11.696的采样才转 False；连接仍保持到25.697。此空窗缺少用户/设备操作标记，不能自动认定设备停止上传的原因。
- 在线请求/生效模式均 adaptive，未观察 fallback/failed/cancelled。completed +8为分段结果，不是八轮对话。新回答识别完成→服务器首包2212ms、TTS启动→首包1487ms，不代表设备出声，也不用于不同条件的固定提速比例。

这些数值把断点收敛到“本次播放期输入已到达 VAD，但没有语音阳性”。仍不知具体发声区间，不能声称653包都含所有者人声，更不能据此确认 AEC、设备端处理或模型是根因。现有各阶段 max/last 没有成对调用标识或原子配对合同；不把不同帧或不同阶段时刻的极值当成同帧衰减比。高能量也可能是回声/噪声，端点幅值触顶本身不证明严重削波。

## 下一步最小可执行方案（建议，尚未实施）

1. 保持正式 buffered 及现有阈值/AEC；本轮不再要求所有者反复测试，也不继续扩大 SmartTurn。由 ROOT 保存此失败检查点、确认实际服务状态；AC 不连接日用。
2. 若后续本来就安排一次实机验收，由 ROOT 统一记录独立于 ASR 的发声起止标记、同一采样时钟及标记不确定范围；短时窗口覆盖输出开始、一次停止口令和结束。仅采用自然复现也应记录所有者当时是否确实发声，避免继续收集无标记全 False 摘要。此处不是再次请求本轮测试。
3. 最小无音频补充只需同次 AEC 的成对统计：合法输入/输出对数，按固定输入能量门统计 RMS 比值的少量固定区间、零输入对数；以锁内一次提交避免不同调用的 input/output 混配。只保存总计和现有约三秒合并窗，不保存逐帧历史/PCM，不重跑 AEC/VAD，不改原输出。精确标记后的上行活跃性、概率、VAD/abort 差分继续使用已有观测。现有 v1 严格 schema 不能直接加未知键，必须先由 AI 协调投影/预算/兼容并合成回归；本分支未擅自修改。
4. 有标记数值可判断“确认说话期间是否没有上行”“上行经处理是否一直低概率”“强衰减是否同时出现”，仍不能凭 RMS 证明被抑制的是人声。若这一轮仍无法区分正常去回声与误伤人声，应停止同类数值反复试验，由 ROOT 另向所有者申请一次短时、明确脚本和范围的受控录音；不自动录制。可限定服务器 AEC 前/后各一份同源 PCM（已在设备端处理之后），仅诊断文件、私有忽略目录、不写个人库；离线对齐同一分帧/状态/阈值比较后再决定算法。它也无法独立证明设备端 AEC 前原始麦克风质量，需要设备前端证据时再明确设备范围。

条件成立后才选最小行为修复：若确认输入缺失，修对应采集/传输状态；若确认服务器 AEC 误伤人声，再评审局部保护条件而非默认绕过；若同一受控语音在处理前后均低概率，才评审输入规范/增益或 VAD 适配；若已有 VAD 阳性且输出生命周期活跃却播放布尔为假，才评审即时 abort 谓词。以上均非本轮已证根因，不据此改默认阈值、静音计时或固件。

## 交付边界

定位记录提交26547006时只新增此记录，未写业务代码，因此该阶段不新增镜像实现的测试、不重复模型回放。已完成源指纹、白名单逐项差分、采样点队列/处理中状态及事件时间线的只读核对；后续新增授权与候选见下。共享清单归 AI，登记后由整合会话执行严格文档检查；AC 不编辑其清单或主文档。本次不 merge、不 push、不向其他会话发消息。

## 后续已授权候选：同次 AEC 成对统计

ROOT 随后授权实现，仍仅诊断、不改任何声音/阈值/分块/控制行为。核心接口在 [voice_vad_signal_observation.py](../../../scripts/development/xiaozhi/voice_vad_signal_observation.py)：安装接口不变；`voice_vad_signal_snapshot(connection)` 默认仍为完整原 v1；显式 `include_aec_pairs=True` 为内部完整 v2取值字典。AI 负责同一路径默认严格 v1、显式 `?version=2` 独立补充响应的投影、协商和预算回归，AC不修改其模块。

内部 v2保留所有旧字段，新增：

- `observation_id`：连接首次业务观测时生成的16位随机小写十六进制代次；只在该连接生命周期内稳定，不含设备身份，不提交/记录设备标识。未观测/无连接/整体不可用为 null；GET不创建状态或代次。
- `clock_ms`：查询时同机单调时钟毫秒，范围0至 `2**63-1`，时钟读取失败为 null。标记端也取单调时钟，不能用聊天回执当发声时间。
- `aec_pairs`：尚未调用/新旁路内部不可用为 null，否则恰含 `rms_floor_pcm16=500`、`ratio_edges=[0.1,0.25,0.5,0.9,1.1]`、`total`、`recent`。两份统计均恰含 `valid/invalid/zero_input/below_floor/original_error/observer_error/ratio_bins`，六个计数和六格计数各饱和于 `2**31-1`。所有AEC调用汇总，不能与speaking分组逐帧交叉归因。

输入RMS取调用前局部标量，输出RMS取该次原调用实际返回结果；复用原能量测量，不再遍历PCM。只在原调用返回/抛出后，锁内一次提交到完成时的秒桶，不暂存输入波形/输出波形/逐帧列表。有效对要求两端均是非空、偶数字节、等长度 PCM16。未饱和时 `valid = zero_input + below_floor + sum(ratio_bins)`；零输入独立计数不做除法，`0<RMS<500` 属below_floor，RMS等于500进分箱。输出为0则比值0，输出大于输入不截断。比值从既有三位小数RMS标量计算；500只是统计门，不是语音判据或新业务门。

invalid为正常返回但输入/输出不成合法对；original_error为原调用抛出（含BaseException），异常对象/类型原样抛出；observer_error为正常返回但能量测量抛异常，不与valid分母混合。新统计记账故障仅使新字段未知，不破坏旧观测或原调用。近期仍只含完成时单调秒及前两秒，最多3个合并桶；重叠近期不能相减，标记分析只用同代次累计差分。观察代次变化、计数下降、任何相关计数饱和或时钟未知都应拒绝有效差分。VAD reset不重置连接累计，断线后的新连接使用新代次。

预算保留失败回执：初始生产者三位小数最大值中原v1=5237B，早期无代次内部v2=5825B；后按旧投影允许的长浮点表示加强最大值测试，完整原v1=5815B，含代次/时钟的完整内部v2=6481B，即使仅删尚未发布的新近期成对统计仍6224B。ROOT明确否决把完整内部v2当HTTP响应，不收紧原v1浮点合法范围、不提6000B、不删旧字段；改为独立成对小响应，建议仅取 `version/state/observation_id/clock_ms/aec_pairs`，最大值测试小于1000B。对应否决事实保留在回归测试，不将失败方案改写为已通过。

主Python与小智Python独立标准库进程的单调时钟读数已验证落在同机调用前后78ms括号内；不接服务，不导入模型/Torch/GPU。此证明用于本机时间关联，不把按键标记当准确音频边界。标记工具和CPU微基准另笔交付；当前核心模块合成回归包括交错并发、零/无效对、原异常身份、观察失败、旧getter、复位/断线方法透明及最大预算。

核心提交 `5d92e43b8c03fdbcba1118962dd93e365c19891c`，定向69项通过；ROOT/AI随后冻结公开小响应六字段：`version=2/kind='aec_pairs_supplement'/state/clock_ms/observation_generation/aec_pairs`。公开代次由内部observation_id映射，公开aec_pairs只取门值/边界/total，不输出新recent；默认请求和显式v1完整保留。HTTP接线及共享文档清单由AI交付，不宣称本分支已部署。

## 单轮按键标记工具与计数对齐

[voice_signal_markers.py](../../../scripts/development/xiaozhi/voice_signal_markers.py) 只使用标准库，不连任何API/服务、不监听全局键盘、不打开音频设备。`record`只接本进程的回车/q/中断，不保存任何输入正文，只写固定ready/speech_start/speech_end/cancelled枚举和单调/Unix毫秒。只做一轮；起键后再说、说完后按止键是手动外侧括号，包含人为反应时间，绝不是准确音频起止。输出父目录必须已存在，使用独占新建，拒绝覆盖。

由ROOT在将来已安排的唯一一次受控流程中执行，**本轮没有运行真实提示/要求所有者再试**：

1. ROOT按AI接线结果启动短时数值采样，包住整组device、v1、v2查询记录`monotonic_before_ms/monotonic_after_ms`；保存原始计数与公开v2对象。采样行约定为`device.ready`、`device.voice_input_observation.counts`、`signal_v2`（公开六字段）及这两个单调锚点；读取signal.clock_ms必须落在整组请求括号内，否则拒绝对齐。可在只采v2的行名signal下放同一公开对象，但不接受缺kind的内部完整v2或默认v1冒充。
2. 以主项目现有Python运行`voice_signal_markers.py record --output <私有证据目录的新markers.jsonl>`。看到起提示后按回车再说一次，讲完立即按结束回车；q或Ctrl-C取消。语句不经本工具ASR，不写个人库；ROOT统一安排实际对话，不因本脚本改日用。
3. 数值采样至少覆盖结束标记后的完整一组请求，再正常停止。以同一Python运行`voice_signal_markers.py align --markers <markers.jsonl> --samples <数值samples.jsonl> --output <新的alignment.json>`。
4. 工具从起标记之前已经完成的最后一组请求，到止标记之后才开始的第一组请求取外括号。严格差分仅用于同代次v2 paired累计计数，不相减重叠recent；不输出input_delta，device的queue_put/vad_check/vad_speech/formal_begin/speech_begin/abort_begin/abort_return只保留前后两份时间邻近背景。整组HTTP时间括号不证明device与v2是同连接或跨端点原子。按键只圈定所有者计划发声的外侧时段，数值本身不验证人声或AEC误伤。

供AD采样接力的最小单行JSONL示例（纯合成；其他既有采样字段可保留，工具只提取白名单）：

```json
{"sample_index":0,"monotonic_before_ms":100,"monotonic_after_ms":110,"device":{"ready":true,"voice_input_observation":{"counts":{"queue_put":100,"vad_check":100,"vad_speech":0,"formal_begin":0,"speech_begin":0,"abort_begin":0,"abort_return":0}}},"signal_v2":{"version":2,"kind":"aec_pairs_supplement","state":"observed","clock_ms":105,"observation_generation":"aaaaaaaaaaaaaaaa","aec_pairs":{"rms_floor_pcm16":500,"ratio_edges":[0.1,0.25,0.5,0.9,1.1],"total":{"valid":1,"invalid":0,"zero_input":0,"below_floor":0,"original_error":0,"observer_error":0,"ratio_bins":[0,0,0,0,1,0]}}}}
```

两个请求外侧单调锚点必须实际采集，不能事后由Unix时间或样本序号推算；clock_ms为服务端GET查询锚点，必须处于它们之间。marker JSONL每行恰有`version=1/event/monotonic_ms/unix_ms/timing_kind='manual_outer_bracket_not_exact_voice_boundary'`；event仅四个固定枚举，不包含任何口令文字。

相邻请求之间也可能有未采样的断开/重连；随机观察代次检测重连、计数和时钟检查防止明显错误，但不声称按键或低频API是无误差的设备级时间追踪。本轮原144行没有新增v2/单调括号，不能事后伪造这些字段使其成为带标记证据。align输出仅固定白名单数值，不复制样本中的任意其他键/正文。

[标记工具测试](../../../tests/unit/development/test_voice_signal_markers.py) 在f30b7e21交付时13项通过：单轮标记、不保存输入文字、取消/中断、拒绝覆盖、时间外括号、累计对齐、代次/未知/饱和/下降拒绝、默认v1不能冒充v2，以及纯合成CLI往返。后续合同小修见下；未接服务或实际邀请所有者讲话。

纯CPU有界微基准：主Python3.12，基线86179117原数值包装对照成对候选；960样本（16kHz下60ms）纯合成PCM16、假AEC原样返回，双方预热40次，各测2000次，10批每批200次并交替AB/BA次序。批次每调用中位数旧262.807µs、新267.394µs，差4.587µs；旧批次范围255.806–288.979µs、新261.673–280.944µs。两侧返回对象身份均保留；新逻辑复用原两处能量测量，不重复解码/RMS遍历，仅保留局部标量。未导入Torch，不加载模型/GPU、无服务调用或大型基准；没有设置墙钟CI断言。该单机微小差值受调度噪声影响，不等于端到端或实机延迟改善。

f30b7e21收尾定向回归85项通过（另补输出0/比值大于1/等于边界的三例），CLI help可独立以`-I`运行；10个本地文档链接目标存在。严格文档检查因本新增记录未登记共享manifest而退出，错误为unlisted-document/unknown-selection，留AI登记与整合验证；未据此修改其共享文件。未merge、push或部署。

## ROOT复核后的对齐合同小修

ROOT指出f30b7e21未严格验证marker合同、缺少内部采样空洞描述、以及中间pair未知仍可能恢复首末差分。先加入合成反例，旧实现18失败/14通过，确认并非仅文档表述问题；修正不触碰record提示流程、生产观察器或任何语音行为。

- 完成标记只接受恰三行ready→speech_start→speech_end，每行固定五字段、整数version=1、固定timing_kind、非负整数Unix/单调毫秒且单调有序；取消、未知/缺失/额外字段、乱序或错误类型均拒绝。结构校验不证明真实发声或文件不可伪造。
- signal_v2严格六字段与固定version/kind；aec_pairs若存在须严格门值500、五个边界、total固定七字段、六格及未饱和有效对守恒。只有显式aec_pairs=null表示该次配对未知，缺字段/total=null/错门值/错边界不当作合法未知跳过。
- pair_state=observed时才有pair_delta。首基线未知给baseline_unknown和null；首基线已知而窗口中任何配对未知给unknown_within_window和null，不借首末已知掩盖中间未知。代次变化、相关计数饱和/下降等仍拒绝；device只是邻近背景，其下降保守拒绝，不推导其与v2同连接。
- 在挑选首末之前校验整份JSONL的单调请求括号全序，拒绝重叠、重复、逆序及每组开始晚于结束，防止乱序行被挑选过程排除。每个可用v2 clock仍须落在自己的整组请求括号内。
- 输出sampling固定标注kind=between_request_groups_not_audio_loss，含sample_count/gap_count/max_gap_ms/total_gap_ms及至多三项largest_gaps（after_ms/before_ms/gap_ms）。按实际相邻请求组的间隔计算，不假定1Hz、不设任意固定阈值，也不把观测间隙说成音频丢失。首末不确定时间另保留。
- 移除input_delta；device_background含before/after各自整组括号及固定INPUT_KEYS原值，kind明确为time_nearby_snapshots_not_atomic_or_same_connection_proof。此处两份背景不能与同代次AEC分箱逐帧交叉归因。

上述改动仅用于本地离线对齐；不增加采样请求，不扩大API或引入新标记控制面。最新单模块33项通过，整组定向回归结果以本笔交付为准。

## 20:05单次标记实测的离线复核（未通过）

ROOT指定来源`marked-adaptive-trial-20261022T120211Z-ff3450`的markers、owner-outcome及sample-evidence。未改动原文件、重写标记或将后续子段冒作原标记窗口；未读音频/日志正文/个人库，未操作服务/模型/串口。原markers SHA256 `e5343937eaa64b33eccc42e0c4317dc2158ebcc624857e55f7341bf5f4f76563`，samples SHA256 `5cd92c53101e496ec1cb8fcd08078b98c4d397672469e7c38ce38c5494190b9f`，owner-outcome SHA256 `653a44ced1605ad7da8f8669e5ffa759feb16a6cdbe0ed6369bdb30540a28f38`。

- 64组，63047ms，request_state均ok；v2状态42组no_connection、1组not_observed、21组observed，已观察代次仅`d6a7643b3253acaf`。请求组最大47ms、相邻组最大间隔1016ms，均为请求时间背景，不代表麦克风是否有声或跨端点原子状态。
- ready标记20:05:19.137、起键20:05:45.010（676976546ms）时均无有效连接观测。首个observed是20:05:50.076（676981625ms），比起键晚5079ms；首个非空paired在20:05:59.083（676990625ms），晚14079ms。止键为20:06:09.825（677001375ms）。最新helper原样离线重算仍为missing_outer_sample_brackets，不移动起点、不用后续已连接数据补成有效口令窗口。
- device邻近背景：20:05:55采样有一次正式识别处理中、队列深度9，下一组已返回且队列归零；之后至末组正式识别累计保持1、非空结果1、abort保持0。播放期v1背景累计259包全False，485次推理中484次不高于0.3、另一次位于0.3至0.5之间；最大0.3858163，没有达到0.5。不能把这些包或唯一识别归属到某句口令。
- 20:05:58.079已有active_output=true、producer_adaptive_buffer=1，但答案包返回仍0。20:06:00.075的采样才看到first_answer_send_returned=1、answer_send_returned=14；其后持续增长至180。preset保持0。active_output或生产器开始本身不证明实质答案已返回，更不证明设备实际出声。
- 末组同代次v2累计194个valid、28个below_floor、0个zero_input，六格为[76,78,7,4,1,0]，invalid/original_error/observer_error均0。166个可分箱对中154个比值小于0.25。这是同次调用能量衰减的真实统计，不再是不同帧极值比；仍不知其中哪些有人声，不能区分正常消回声与误伤近端人声，也不能与v1播放分组逐帧关联。
- 最后仍为adaptive、active_output=true，2个分段completed、无fallback/failed/cancelled，另一分段active。分段完成不等于轮次完成或成功打断。所有者反馈“没有停，提示窗口回车按早了”；owner-outcome明确实机未通过、标记无效、未授权录音且不要求重复。本次结果不证明新增观察修复了语音，也不能单凭无效标记推出必须录音。

ROOT选择先修测试门禁而非改算法或立刻再要求所有者试。最小门禁建议：只消费现有采样JSONL，不增加API或数值字段；至少两组新鲜、同代次、合法且未饱和的paired基线，结合device.ready/active_output及实质answer发送计数增长，不能将background_ready、cue/稍等或生产器开始当放行。软件条件满足后由所有者在同一窗口确认已听到设备实答，再允许一次新的Enter起键；门禁前Enter仅提示等待，不能缓冲后补记。ready事件推迟到条件满足及听到确认之后。绑定代次后断线、代次变化、数据过期或明确总等待超时即取消，不自动重试；起键后输出停止可能是成功打断，不以该变化撤销已发生标记。90秒总等待仅为建议的可配置流程界限，不是性能实测。

## 可选、需另授权的最小音频方案（未实施）

当前数字不能区分人声、AEC与VAD，但本次无效标记本身不构成必须录音的理由。先由ROOT决定是否实现/审查门禁；不安排新的盲目轮次。若后续需要更直接判断处理前后的人声，ROOT可另向所有者提出下列精确范围，获得授权并完成实现审查前不录制：

- 仅一次、最多8秒的受控测试；固定公开回放语句与所有者说一次“停一下”，不夹带私人对话，不查询/写入个人记忆。门禁就绪并获得听到确认后才开始；取消或超时立即停止，不自动补录/重试。
- 仅保存同源服务器AEC输入/输出两轨（已是设备端处理后的16kHz单声道PCM16），可放一份左右对应的立体声WAV：8秒约512044字节。它不是设备AEC之前的原始麦克风。输入/输出长度异常则将样本标为不完整，不填造对应音频。
- 起始约2秒保持静默以观察回放回声，随后只说一次固定口令，其余时间静默；用现有单调按键/采样锚点保存时间外括号，不把人工时间当精确声学起止。真实语音边界可在离线音频中确认，不再靠ASR能否识别来当标记。
- 录制实现只在批准窗口内使用定长小缓冲，原调用不等待磁盘；停止后仅落入ROOT新建的私有忽略证据目录，不上传录音、不提交Git、不进入个人库，不扩大为持续录音。录音含设备回放声音和所有者声音，保留/删除由所有者另定。
- 首先离线听辨两轨，判断处理前是否实际有可辨口令、处理后是否消失/受损；若需模型复放，再由ROOT安排同一CPU模型、相同分块/阈值与相同初始条件的对照，不假称能恢复未采集的生产RNN历史。前后都没有可辨近端语音时，仍不能独立证明设备AEC或麦克风的具体问题；需要设备前端证据须另界定授权范围。

以上是主会话判断所需的候选范围，不是对所有者的新录音请求、实现授权或已完成实验。
