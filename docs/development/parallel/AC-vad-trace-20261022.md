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
- 同一在线连接首末差分：queue_put、queue_get、vad_check 各 +732，vad_speech +48。每个采样点 queue_depth=0，各阶段 inflight=0；支持没有采样到持续积压/等待，不能排除采样间短暂等待。
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

本分支只新增此记录，未写业务代码，因此不新增镜像实现的测试，不重复模型回放。已完成源指纹、白名单逐项差分、采样点队列/处理中状态及事件时间线的只读核对。共享清单归 AI，登记后由整合会话执行严格文档检查；AC 不编辑其清单或主文档。本次不 merge、不 push、不向其他会话发消息。
