# AI：adaptive实机打断失败与buffered恢复接力

日期：2026-10-21。源码基线58ca0f3282e4b3e54c38e821eafb60d09e46e82e。
本轮仅记录ROOT转达的所有者反馈、脱敏阶段事实及只读源码边界，不修改产品或操作日用。

## 当前结论

**adaptive实机验收FAILED，停止持久化推广。** 所有者先反馈“感觉这次还可以”，随后明确报告
打断有时成功、有时不成功，澄清失败现象为“没有识别出停一下，旧声音继续”。早先改善反馈不能覆盖后续拒收，
也不能将它写成完整连续播放、字幕及两次打断验收通过。

窗口01的隔离技术验证仍是真实结果：83.078秒、16调用、12测量及取消/复用完整，直接协作取消成功，
见[AD结果](AD-three-mode-results-20261021.md)及[AI复核](AI-current-voice-window-20261021.md)。
该窗口从完整TTS文本就绪起测，没有设备收音、VAD、ASR和同连接全双工输入，不能证明口令一定被识别，
更不能据34.55ms客户端取消返回宣称圆屏已经即时静音。历史技术放行只支持当时进入受控试用，不是本次实机通过。

## ROOT报告的实际事件与恢复

以下保留ROOT给出的原时刻标记，未另行换算时区；AI没有读取真实对话、音频或私人日志。

| ROOT提供的观测 | 可支持的事实与限制 |
|---|---|
| adaptive试用共6个chat观测 | 不是6次打断测试，也不代表失败口令总数 |
| 12:16:45长答first_audio_sent约2553ms | 软件答案首包，不是物理首字；与此前不同问题不计算严格提速百分比 |
| 12:20:33模型requested到output约4497ms、首包约6309ms | 该轮模型阶段本身较长，不能将全部等待归到TTS或adaptive |
| 12:21:08、12:21:15、12:21:27首包约2026/1769/2424ms | 少量不同问题的观测，不组成受控基线或P95 |
| 12:21:08那轮tts_cancelled于12:21:15.053，新ASR于12:21:15.668进入 | 存在成功取消及新轮输入路径，不能声称所有打断均失败 |
| 最新轮12:21:27.924 asr_entered到handoff约2ms，12:21:30.353首包；持续TTS至12:22:16.206 cancelled、16.391 tts_cancelled | 期间没有新的asr_entered或chat_entered观测；仍不能据此推断没有上行音频或ASR内部从未调用 |

ROOT进一步核对、AI按voice_input_latency.py独立确认：现有asr_entered在handle_voice_stop入口建立，
不等于模型speech_to_text已经调用，也不覆盖WebSocket收包、音频解码、ASR队列和VAD判定。
此前将其称作speech_to_text端点不准确，以本段源码位置为准。因此所有者的“没识别出来”是体验事实，尚未区分没有触发识别、内部调用后空结果、
输入排队或没有新音频等具体阶段；不能补写成每次ASR调用失败。

natural_interruption_diagnostics现已提供AEC/listen/timestamp能力，但ROOT此前连接瞬间保存的投影遗漏了
natural_interruption；断线后不能还原当时字段，不能用当前离线false推断当时client_aec或能力为false。

ROOT已保全失败后的当前95文件新备份，共15,904,574字节，退出launcher42544所属22个实例；
**没有恢复旧个人库**。随后从正式入口恢复buffered，新launcher60820已ready，选中声线warm，active_requests=0，
63份配置/dist/provider与保护摘要逐字相同，Docker及COM3未操作。以上为ROOT实际操作报告，AI未执行停止/恢复。
当前维持buffered，不沿用已关闭窗口补跑模型，不把服务ready当作此次实机反馈已经解决。

## 只读组合审查与修复所有权

AI核对固定上游与项目适配代码，尚未取得adaptive锁住收音的确定证据：

- ConnectionHandler收包/解码后把PCM放入ASR队列；ASR工作线程将handleAudioMessage提交到同一连接事件循环。
  VAD同步调用及后续ASR处理也在该循环中，需核对输入积压和循环调度，不凭线程名称断言完全隔离。
- adaptive读流/缓冲及Opus编码位于TTS生产路径，encoder_lock和Condition是TTS局部锁；
  发送节流为异步等待，播放线程future.result等待的是连接循环任务，没有发现新增直接持锁跨收音的确定路径。
  不据静态阅读排除CPU/GIL、资源争用或未观测运行状态，也不将其认定为根因。
- 通用输出撤权发生在非空ASR文本交接；原生更早的VAD打断还依赖client_aec与have_voice等条件。
  未到交接时旧输出可能继续，但目前不能确定失败落在哪一前置条件。

ROOT路由：AC核查收包→解码→队列消费→VAD→ASR调用→空/非空结果，并核对实际listen mode、client_aec与唤醒忽略状态；
AD核查增量合成/发送与同连接输入调度的并发、清理和资源边界。AC独占新增只读输入计数helper及voice_input_latency.py窄改，
AD拥有audio/voice_latency.py，AI独占公共launch及device_control.py getter接线，等AC明确接口后再接入，不重复实现。
若合成不能复现现场根因，先准备最小前半链观测，再由ROOT安排一次带诊断实机，不盲猜阈值。
AI做独立组合审查，等待其精确交付，
不直接修改AD/AC文件、不自开模型或重复实机试验。后续修复仍需所有者实机复验，不能只重跑离线取消。

## 持久化草稿保全

可选本地cosy_delivery_mode偏好草稿未提交、未推送或部署，未写私有偏好；保留在独立分支
`codex/ai-cosy-mode-preference-20261021`的专属Git stash对象
`42872c691702eebaafff5b1fa123f4c87a9f7d6e`（7个源码/测试文件），未删除草稿或清理分支。
恢复草稿须按对象ID，不依赖全仓共享的stash序号；该草稿不进入本次失败事实提交。

草稿测试原报告保留：首次独立收集缺voice_ports测试路径；修正测试引导后组合140通过/3失败，
两项是小智观察器直接导入路径缺失，一项鉴权HTTP超时伴Tk跨线程析构告警；不把告警当作已证实唯一原因。
补足本次子进程源码路径后3项单独通过；相关偏好契约29通过、独立完整HTTP31通过。
这些不是整轮组合全绿，也不构成adaptive实机通过或继续推广的许可；当前不继续测试/发布该草稿。
