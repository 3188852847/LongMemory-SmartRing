# AD：口令未显示后的发送侧核查与隔离全双工复现

日期：2026-10-21。基线 `58ca0f3282e4b3e54c38e821eafb60d09e46e82e`，
分支 `codex/ad-barge-in-starvation-20261021`，原成果与证据均保留。
OWNER报告adaptive中部分“停一下”未识别、旧声继续，因此当前adaptive实机体验失败，不能沿用此前合成窗口的技术放行当作真机通过。
ROOT已报告保全新检查点、恢复buffered日用；AD未访问日用、真实日志/对话/音频、个人库、配置或设备。

## 结论与窄范围交接

本次合成供给下，未复现adaptive长期占用事件循环/GIL/音频锁而饿死收音。
发现两个可反驳的**接口事实**，均不能独立定为此次实机根因：

1. 固定SDK `ASRProviderBase.receive_audio` 在非流式端点处要求PCM长度严格 `>1920*15`。
   7帧13440字节、15帧28800字节的合成输入即使已收且speech=true，也跳过正式ASR并重置状态；
   16帧30720字节进入ASR、文本交接和interrupt。该分支不是模型识别失败。
2. 固定SDK `handleAudioMessage` 在client_aec=true且speech/speaking成立时先await abort，再调用ASR.receive_audio。
   合成350ms下行背压可使首个speech已判定，但首次ASR接收延后约350～359ms；WS仍及时收全18包。
   这是ASR串行工作线程等待输出屏障的耦合，不等于整个WebSocket/事件循环停止收音。

没有据此修改阈值、AEC、listen模式、固件、上游源码或生产音频文件。
ROOT→AC接力点为上述输入分支及端点证据；若实机计数未命中，不能为“修复”而直接翻门槛。
AC仍唯一负责生产输入只读计数，AI负责getter/launcher；本提交仅测试夹具和本记录，不增加另一套生产probe。

## 源码定位

固定上游来源为 `eb4b28c59ed7ed885258498cf757ce14352d620e`，本探针从Git对象提取方法，不改共享外部源：

| 边界 | 所审代码事实 |
|---|---|
| WS收音 | ConnectionHandler.handle_connection逐条await路由；二进制_route_message解Opus后入asr_audio_queue |
| ASR队列工作 | ASRProviderBase.asr_text_priority_thread独立线程，每帧run_coroutine_threadsafe(handleAudioMessage).result |
| speech到ASR | receiveAudioHandle.handleAudioMessage先VAD，just_woken_up可提前返回；AEC speech分支await abort后才ASR.receive_audio |
| 正式端点长度 | ASRProviderBase.receive_audio要求非STREAM、client_voice_stop，并在len(pcm)>28800时才handle_voice_stop，随后reset_audio_states |
| TTS生产 | TTSProviderBase.tts_text_priority_thread同步调用to_tts_stream，模型HTTP/FIR/Opus与encoder_lock均在该生产线程 |
| TTS播放 | _audio_play_priority_thread独立线程提交sendAudioMessage到连接loop，再在自身线程等future.result |
| AD缓冲 | AdaptivePCMBuffer独立读流线程，Condition.wait释放等待锁；队列按60ms切片有界，非loop内同步等模型 |
| 下行流控 | AudioRateController后台task用asyncio.sleep等待播放位置；AD OutputProtocol写入与门锁用asyncio.wait让出loop |
| AD撤权锁 | 所审audio/state锁不跨socket write的await；有序wire屏障可延后abort写出，但不把WS迭代器锁住 |
| listen/reset | 固定Listen处理器start/detect会重置输入缓存，detect可设置just_woken_up；不能从输出client_is_speaking清除推断输入缓存有效 |

精确输入接力顺序：WS bytes → PCM入队 → handleAudioMessage/VAD →（可能await abort）→
ASR.receive_audio → 端点与长度门槛 → handle_voice_stop/speech_to_text → 非空文本 → startToChat → 撤权 → wire interrupt。
已有正式ASR阶段观测不能代替此链前半段的“已收到音频”证据。
ROOT给出的最新轮长TTS期间无新asr_entered/chat_entered，仅限定了现有观测缺失；
既不能证明设备没发/服务器没收，也不能证明内部ASR从未被调用。此前成功中断记录与本次部分失败可并存。

## 可复跑探针、替身边界与实际结果

[探针夹具](../../../tests/fixtures/ad_duplex_probe.py) 经
[专属测试](../../../tests/unit/development/test_ad_barge_in_duplex.py) 启动现装小智Python3.10，
只开自有随机127.0.0.1 HTTP与WS端口，不连接18770/8767/8003等日用端口。
合成配置中的18770字符串仅用于启用既有协议合同，不是网络目标。

使用真实Opus编码/解码、FIR、AD buffered/incremental/adaptive消费、固定SDK音频队列工作线程与流控、
双向真实WS及tts_interrupt_v1。下行解码确认收到非静音合成波形后才注入上行。
VAD为预置speech/端点替身，正式ASR为固定文本/空文本异步替身；音频是合成正弦，不是人声录音。
不执行Silero/ASR/TTS模型，不验证AEC回声抑制/声学阈值、设备麦克风或真实口令识别。
上行每帧960个16kHz样本，以4ms间隔加速注入；时间值仅用于调度反驳，不代表真人语速或实机端点时延。

实际10项通过，18.68秒：

| 场景 | WS收到/PCM入队 | speech/ASR与输出结果 |
|---|---|---|
| buffered/incremental/adaptive，输出16kHz | 各18/18 | 各18帧进入VAD和ASR接收；1次正式ASR替身、文本交接及wire interrupt |
| adaptive，输出24kHz | 18/18 | 同上；输入始终16kHz，与固定SDK解码边界一致 |
| speech全部false | 18/18 | ASR接收18，正式ASR0、文本0、interrupt0 |
| 正式ASR返回空 | 18/18 | 正式ASR1、返回空1、文本交接0、interrupt0 |
| AEC分支+350ms输出背压 | 18/18 | 首speech约0.66ms，首ASR接收359.44ms；最终1次ASR/文本/interrupt，最大队列17 |
| 短端点7帧 | 7/7 | speech6帧，正式ASR0、文本0、interrupt0 |
| 长度边界15帧 | 15/15 | speech14帧，28800字节不满足严格大于，正式ASR0 |
| 长度边界16帧 | 16/16 | 30720字节，正式ASR1、文本1、interrupt1 |

四个正常播放场景首输入至VAD/ASR接收约0.48～0.76ms；逐帧最大WS到达延迟≤0.63ms，
最大输入至VAD判定≤10.12ms。本次正常场景没有出现秒级调度阻塞。
背压场景后续VAD处理也因串行ASR工作线程等待而积压，但WS接收入队仍进行；不能只看首speech就说整段处理无阻塞。
两个无字幕对照进一步证明“无字幕”不能直接等价为“没收音”或“ASR没有运行”。
wire interrupt收到仅为合成WS端观测，**device_interruption_acknowledged=false**，不宣称设备已静音。
所有探针断言未导入torch，音频仅在内存，线程/自有网络服务在每例退出时回收。

```powershell
Set-Location -LiteralPath 'D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ad-cosy-continuity-20261021'
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -B -X utf8 -m pytest tests/unit/development/test_ad_barge_in_duplex.py -q -s
```

测试代码仅依赖固定SDK方法与明确替身，不自动安装、重试换源、访问日用配置/模型或启动任何共享服务。
初次夹具缺少report_on_last/logger命名空间时被本地测试识别并修正，未据夹具错误修改生产实现。

## 最小下一步与变更边界

将本测试提交交ROOT→AI审查。实机下一次最小观测由AC/AI既定输入计数提供：
是否收到/解码/入队，speech判定、just_woken_up与listen/reset分支、端点总PCM长度/是否跳过，
ASR调用/空返回、撤权与interrupt阶段；不采集正文/音频，不新增AD生产探针。
若实机命中长度门槛，再由AC提出保留噪声过滤意图的最小受测修复；当前不代选新阈值。
若命中abort输出等待，再协同评审输入调度与有序输出屏障的解耦，不能通过绕过interrupt顺序伪称修好。
若没有上行包或speech始终false，按对应边界取证，不为方便关闭AEC或扩大固件写入。

此提交未修改生产行为，不能称真机故障已修复；旧合成完整性证据保留，adaptive仍不视为实机通过。
不重跑ROOT已通过的广泛CI；只交本10项有界复现及源码事实。
两处链接目标存在；严格文档检查退出1，新增记录未登记，unknown-selection，实际检查0份，
另有unlisted-document警告；未宣称通过。文档清单归属仍留主会话，未改共享manifest。
