# AD：显式设备打断合同候选 v1

2026-10-21；提交给主会话/AI审查，尚未安装或实机验收。AD不编辑外部固件或操作串口。
此文是当前候选，不表示用户已经批准协议或额外固件写入。

## 当前消费者事实

只读 `D:/Dev/esp-projects/smart-ring/otto0015`：

- `main/application.cc:531` 的 `tts.stop` 只安排状态切换。自动监听在914附近等待队列播完；
  realtime输入处理器已运行时不重新EnableVoiceProcessing，因此不会顺带ResetDecoder。
- `AbortSpeaking`（974）只设aborted_并发上行abort；当前aborted_没有音频接收/播放门作用。
- `main/audio/audio_service.cc:668` 的ResetDecoder会清decode/playback/testing队列；
  但341取出旧包后解码与381重新入播放队列之间存在解锁窗口，不能只加一次clear就声称无旧帧。
- 已从播放队列取出并交给 `codec_->OutputData` 的PCM也不在clear覆盖范围；不得承诺零毫秒静音。
- 项目 `device_control.stop_speech` 只调用response_aborter，返回device_acknowledgement=unavailable。
  固定服务端abortHandle只发普通tts.stop。没有现成远程MCP清音频捷径。
- `audio_service.h` decode队列限40×60ms、playback任务限2；不是本次真实积压测量。
  固定服务器先直发5包，调度队列首包又可在0ms发出；因此“清服务端队列”不等于设备没有残音。

这证明合同缺口，不能证明它是owner实际失败的唯一原因。
application.cc SHA256 `d7fd88fa50803a98611388bbafed829bc074b5dd43851443bea8129d5aecf366`；
audio_service.cc `278168c5c13ae36912910de646979a6eee7e53cb157aa63c44e6f6591caa601a`；
protocol.cc `e8e4a43a95182e1b6f63d1d52fa57e350d8a803223e2223e5589d35ba8b88bc8`。
目录不是Git工作树，这些摘要只固定本次读取来源，不冒充运行镜像来源证明。

## 建议冻结的线协议

hello客户端声明：`features.tts_interrupt_v1: true`（严格布尔）。无此能力走旧协议，
只保证服务端撤权；不宣称即时清设备队列。限现有直接WebSocket；MQTT不自动扩展。

TTS JSON沿用type/session_id；以下新增字段为建议的v1精确合同：

```json
{"type":"tts","state":"start","session_id":"existing-session","output_epoch":1}
{"type":"tts","state":"sentence_start","session_id":"existing-session","output_epoch":1,"text":"existing-subtitle"}
{"type":"tts","state":"interrupt","session_id":"existing-session","output_epoch":1}
{"type":"tts","state":"stop","session_id":"existing-session","output_epoch":2}
```

output_epoch为连接内递增整数1..2147483647，拒绝bool/小数/越界；耗尽则结束该输出通道并重新握手，
不绕回。每个新的逻辑输出start创建新epoch；重发同epoch start不得重新开已打断的门。
epoch不复用sentence UUID、用户身份或正文；不写NVS/配置。断开清除内存状态。

正常stop仍代表EOS（自然播完），不得清队列或转成interrupt。interrupt只匹配当前已开始且未撤销的epoch，
立即关闭该轮音频接收门并使其decode/playback任务失效，然后转回原监听逻辑。
相同interrupt可幂等；旧epoch的stop/interrupt/sentence_start和延迟状态回调均忽略。
只有更大epoch start才能开新轮，所有原有start/状态回调必须在实际执行时重核epoch。
设备本地AbortSpeaking也先关闭当前门/使旧任务失效，再发既有上行abort；不得等待服务器往返才清本地。

二进制格式保持现状，无epoch头：这要求**服务端的所有TTS最终二进制写出和TTS控制消息共享同一个
连接级异步发送门**。输出生产/消息租约在入门前固定epoch；进入门后再次核对撤权，然后才await真实发送。
interrupt先撤权，等已入门写出返回，再在同一门内发带旧epoch的interrupt。
后续旧写出必须丢弃，下一轮start排在interrupt之后。不得在锁外await发送后再补计数冒充顺序保证。
只有这个线序前提通过后，设备才可把无标识的二进制归于最近有效start；否则必须升级二进制包头，
不能只依赖JSON epoch。现有普通tts.stop不能充当这个屏障。

本v1不增加播放已停回执；主机状态仍 `device_playback_acknowledged=false`。
如需回执，须另定“队列失效/输出任务屏障/物理扬声器静音”的区别，不能沿用stop发送返回。

## 消费者最小范围与验收

建议AH评审后仅触及：`main/application.cc/.h`（能力模式/轮次门、本地abort与延迟回调），
`main/protocols/websocket_protocol.cc`（hello能力声明/连接重置），
`main/audio/audio_service.cc/.h`（队列generation和解码/输出屏障），
必要时`main/protocols/protocol.h`给AudioStreamPacket加**本地**generation，不改变线上二进制格式。
不动字幕切段、素材、配置、其他应用槽或分区。主会话统一安排最终目标/审查/编译，AD不改这些文件。

必须覆盖：正常EOS最后一帧完整；有声播放中interrupt清旧decode/playback；取出旧包后才interrupt的解码
不得重新入队；取出旧PCM后才interrupt不得在屏障完成后开始旧输出；已交硬件的残留边界如实记录；
interrupt后迟到旧帧被服务端发送门拒绝；新start后旧stop/interrupt/回调不伤新轮；重复start不能复活旧轮；
普通preemptive OFF也有效；0015无能力安全回退；断线/新连接无旧状态；恶意/缺失epoch拒绝而不清新轮。
编译和CPU合同测试只证明软件控制，owner真机声音/打断仍须另验收。
