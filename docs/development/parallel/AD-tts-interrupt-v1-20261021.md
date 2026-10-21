# AD：显式设备打断合同候选 v1（修订3）

2026-10-21；提交给主会话/AI审查，尚未安装或实机验收。AD不编辑外部固件或操作串口。
此文是当前候选，不表示用户已经批准协议或额外固件写入。
修订3在修订2提交`78785348`基础上，明确活动任务的EOS排空、新start同步开门与UI重置隔离、
跨连接本地代次的失效语义和测试；不改变线上JSON字段或能力名v1，尚未有任何一版部署。
修订2补充的双向hello、全部写出路径和非pipeline边界继续有效。此前版本不作为完整实施合同。

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

双向hello确认（严格布尔）：

```json
{"type":"hello","features":{"tts_interrupt_v1":true}}
{"type":"hello","features":{"tts_interrupt_v1":true},"session_id":"existing-session"}
```

第一行为客户端原hello的新增字段，第二行为服务器原hello的新增确认字段，其余既有字段保留。
服务器只有在直接WebSocket、pipeline模式、本地Cosy候选且**所有**实际TTS输出路径都已纳入同一
发送门和门内撤权检查时才能确认true；不能凭设置、HTTP ready或部分包装安装成功就ack。
普通回答（preemptive OFF）、可选AE、等待音、快答/预置音、完整WAV回退、停止提示音、唤醒回复、
绑定/限额/结束提示、公告等只要可能走该连接，都必须已覆盖；遗漏任一路径则不确认。
应在最底层实际WebSocket写出建立共同屏障，不能仅补几个已知函数别名就声称全面覆盖。
hello接收与welcome消息应使用当前连接的副本，不修改上游共享config/welcome对象。

设备只有自己声明且收到服务器确认true才激活v1。0016连接官方/旧服务器没有确认时完整保留legacy播放；
0015不声明时新服务器也保持legacy。v1激活后，缺失/非法epoch的TTS控制不能静默降级或影响当前轮，
只能在通道关闭并重新hello后选择legacy。重复hello不能中途更换合同或重置活跃epoch。
新连接重置协商和**线上**epoch；不能跨连接保留“上次支持”。设备本地channel_generation不能随之重置，
其跨连接失效规则见下文。无双向确认只保证服务端撤权，
不宣称即时清设备队列。MQTT、Doubao realtime及其他非pipeline模式本v1不确认、不扩展；
这些模式沿原路由/既有停止语义，其状态必须明确设备即时flush未支持。

TTS JSON沿用type/session_id；以下新增字段为建议的v1精确合同：

```json
{"type":"tts","state":"start","session_id":"existing-session","output_epoch":1}
{"type":"tts","state":"sentence_start","session_id":"existing-session","output_epoch":1,"text":"existing-subtitle"}
{"type":"tts","state":"interrupt","session_id":"existing-session","output_epoch":1}
{"type":"tts","state":"stop","session_id":"existing-session","output_epoch":1}
```

上面interrupt与stop分别展示打断和正常结束两种互斥路径，不表示打断后再自然结束同一轮。
output_epoch为连接内递增整数1..2147483647，拒绝bool/小数/越界；耗尽则结束该输出通道并重新握手，
不绕回。每个新的逻辑输出start创建新epoch；重发同epoch start不得重新开已打断的门。
epoch不复用sentence UUID、用户身份或正文；不写NVS/配置。断开清除该连接的协商/线上轮次，
但不能清零设备进程的本地代次生成器。

正常stop仍代表EOS（自然播完），不得清队列或转成interrupt。interrupt只匹配当前已开始且未撤销的epoch，
立即关闭该轮音频接收门并使其decode/playback任务失效，然后转回原监听逻辑。
相同interrupt可幂等；旧epoch的stop/interrupt/sentence_start和延迟状态回调均忽略。
只有更大epoch start才能开新轮，所有原有start/状态回调必须在实际执行时重核epoch。
设备本地AbortSpeaking也先关闭当前门/使旧任务失效，再发既有上行abort；不得等待服务器往返才清本地。

### 设备本地身份：跨连接不可复用

设备内每个接收回调、队列项、已出队任务和延迟UI/状态回调都绑定不可变的本地身份：
`(channel_generation, output_epoch, audio_generation)`。output_epoch来自线上；另两项只在设备RAM中，
不进JSON、NVS或用户配置。可用进程生命周期内单调64位整数生成，禁止回绕/复用；耗尽则关闭通道，
不重新置1。设备真正重启后没有旧任务才可从初值开始。

channel_generation在创建新通道和使旧通道失效时更新，不能随断线清理归零。
旧socket注册回调捕获它所属的channel_generation；不可在执行时仅从全局变量读取“现在的连接”来补身份。
断线先关门并使旧代次失效，再清理/join旧任务。旧连接的hello/start/stop/interrupt/二进制及旧清理回调
不能改变新连接的门、协商、状态或队列。新连接线上epoch可重新从1开始，仍与旧连接epoch1区分；
这防止ABA（标识先变走、又变回相同数值而误认同一任务）。

audio_generation在每次有效BeginOutput、interrupt、本地abort或通道失效时生成新值；
即使同一连接里wire epoch未变，旧decode/PCM任务也不能因布尔复位而重新有效。
出队后解码完成重新入队、出队后准备OutputData、任意异步回调实际应用状态时，都再次核对完整本地身份。
旧代次任务的finally只能释放自己活动计数/资源，不能关闭新代次的门或清空新队列。
身份校验与相应队列写入、开始OutputData或音频/状态副作用必须受同一串行屏障保护；
不能检查后解锁、等新start开门，再以旧身份执行ResetDecoder/输出/状态转换。

### start：同步建立音频门，UI不得二次重置

在收到并校验有效更大epoch的start时，接收路径先以串行步骤执行BeginOutput：使旧输出失效、
按音频服务屏障完成旧队列/解码器重置，建立新audio_generation，设置当前epoch并打开新门；
完成后才允许后续二进制按该身份入队，然后才安排UI/设备状态回调。
这里的“同步”指在线序处理后续音频之前完成身份/音频门的提交，不能只Schedule一个未来回调来开门。
v1音频接收依据已协商的新门，不依赖可能尚未切到Speaking的UI/DeviceState，因此start后的首帧不能因UI延迟丢掉。

当前SetDeviceState(Speaking)的异步HandleStateChangedEvent含ResetDecoder；v1必须将本轮重置归于
BeginOutput一次性完成，后来的Speaking/UI回调不得再走会清音频的通用重置路径。
仅在回调入口核对epoch还不够：合法的新轮UI回调到达时新首帧已可能入队，它也不能再ResetDecoder。
同epoch重复start幂等，不重置、不重新开已终止的门；迟到旧Speaking/Listening/EOS回调完整身份不匹配即忽略。
所有可能间接EnableVoiceProcessing(true)→ResetDecoder的旧状态回调同样受该约束。
legacy模式保留原状态行为，不以v1修复改变旧服务器播放流程。

### 正常EOS：队列空与活动任务都满足才算排空

有效stop在同一线上epoch最后一帧之后到达，关闭该轮继续接收音频的门；已接收音频仍保持有效，
不递增其audio_generation、不clear/reset、不截断最后一帧。
自然结束等待的谓词必须针对捕获的完整本地身份，在共同同步范围内同时满足：

- 该代次待解码包及待播放PCM队列均为空；
- 该代次active_decode为0：从包出队**解锁之前**计入，跨解码/重采样/重新入队或丢弃全过程，所有退出路径减回；
- 该代次active_output为0：从PCM出队**解锁之前**计入，直到OutputData返回或该任务失效后退出，所有退出路径减回。

出队与活动计数增加必须为一个原子交接，不能出现“队列刚空、计数尚未增加”的窗口。
活动计数减少、队列变化和代次失效均须唤醒等待者；不能只靠queue_empty通知。
计数按代次归属，不能由旧任务finally误减新轮计数。不可只复用当前WaitForPlaybackQueueEmpty的“两队列空”谓词。
排空等待必须可被interrupt、新start、close或身份失效取消；取消后不再执行旧轮Listening/Idle/UI转换。
EOS等待完成后也要再次核对完整身份，才可做本轮自然结束状态转换。

这里的排空完成仅表示音频服务没有该代次排队或执行中的工作、OutputData已经返回；
硬件/DMA或扬声器残留不据此宣称归零。interrupt仍使用失效/清理屏障，不能改成等自然EOS播完。

二进制格式保持现状，无epoch头：这要求**服务端的所有TTS最终二进制写出和TTS控制消息共享同一个
连接级异步发送门**。输出生产/消息租约在入门前固定epoch；进入门后再次核对撤权，然后才await真实发送。
interrupt先撤权，等已入门写出返回，再在同一门内发带旧epoch的interrupt。
后续旧写出必须丢弃，下一轮start排在interrupt之后。不得在锁外await发送后再补计数冒充顺序保证。
只有这个线序前提通过后，设备才可把无标识的二进制归于最近有效start；否则必须升级二进制包头，
不能只依赖JSON epoch。现有普通tts.stop不能充当这个屏障。
close/断线也必须先撤权并关闭发送门，然后取消/join本连接自有发送工作，不能关闭后仍发迟到音频。
等待/快答和原生函数的已导入别名不得绕过门；处于未确认或不适用模式时不得发送新interrupt控制。

本v1不增加播放已停回执；主机状态仍 `device_playback_acknowledged=false`。
如需回执，须另定“队列失效/输出任务屏障/物理扬声器静音”的区别，不能沿用stop发送返回。

## 消费者最小范围与验收

建议AH评审后仅触及：`main/application.cc/.h`（能力模式/轮次门、本地abort与延迟回调），
`main/protocols/websocket_protocol.cc`（hello能力声明/确认转交/连接重置），
`main/audio/audio_service.cc/.h`（队列generation和解码/输出屏障），
必要时`main/protocols/protocol.h`给AudioStreamPacket加**本地**generation，不改变线上二进制格式。
不动字幕切段、素材、配置、其他应用槽或分区。主会话统一安排最终目标/审查/编译，AD不改这些文件。

必须覆盖：正常EOS最后一帧完整；有声播放中interrupt清旧decode/playback；取出旧包后才interrupt的解码
不得重新入队；取出旧PCM后才interrupt不得在屏障完成后开始旧输出；已交硬件的残留边界如实记录；
interrupt后迟到旧帧被服务端发送门拒绝；新start后旧stop/interrupt/回调不伤新轮；重复start不能复活旧轮；
普通preemptive OFF也有效；0015无能力安全回退；断线/新连接无旧状态；恶意/缺失epoch拒绝而不清新轮。
还须覆盖0016连旧/官方服务器legacy正常、client声明但server不ack、只有server ack而client没声明、
false/字符串true不激活、确认后缺epoch不降级、非pipeline/MQTT不确认、晚来的旧hello不能重置新输出；
等待/快答/公告/唤醒/停止提示音/完整WAV等所有路径，暂停在真实socket await时插入interrupt或close，
按写入线序逐条确认旧音只能在interrupt前、后续新轮完整。没有全面安装证据不宣称协商能力。
修订3必须新增可控调度测试：

- stop到达时包已出队且阻塞在decode、队列均空，EOS不得完成；解码结果入队并最终输出后才完成。
- stop到达时PCM已出队且阻塞在OutputData、队列均空，EOS不得完成；OutputData返回后才完成。
- 在出队/活动计数交接边界插入stop，验证没有假空窗；错误、取消、丢弃路径均归还各自计数并唤醒等待。
- 暂停所有UI回调：有效start后立刻送首帧，须成功入新门；再执行合法Speaking/UI回调，首帧仍在且不二次reset。
- 重复start、迟到旧Speaking/Listening/EOS回调不能重新开门、清新首帧或改变新状态；新轮正常EOS尾帧完整。
- 旧连接epoch1回调/音频/解码任务/EOS等待滞留，断线后新连接重新协商并start epoch1：
  释放旧工作不得通过身份核对，不得改变新门/计数/首帧/状态；旧连接close清理同样不得关闭新通道。
- EOS等待中interrupt、新start或close能唤醒并终止旧等待；不能在新轮已开始后再应用旧EOS状态转换。

编译和CPU合同测试只证明软件控制，owner真机声音/打断仍须另验收。
