# AD：tts_interrupt_v1服务端候选交付

2026-10-21。基于消费者合同修订3 `2b8242e5`，为主会话/AI联合审查提供独立实现。
本文件不是部署或owner验收记录。AD没有修改启动器、controls/UI、外部固件、日用服务或设备。

## 安装顺序和接口

保留 `b0973bbd` 的进程内撤权helper；本阶段新增 `voice_output_protocol.py`。
启动器应先装direct_ws_v2、输入/ASR、AE（如有）、voice_latency、waiting、永久撤权等既有包装，
再装本协议，然后再装control/app。普通preemptive OFF不跳过该安装。

```python
from core.handle import helloHandle as hello_module
from core.handle.textHandler import listenMessageHandler as listen_module
from voice_output_protocol import install_tts_interrupt_protocol
install_tts_interrupt_protocol(
    ConnectionHandler, sendAudioHandle,
    hello_module=hello_module, listen_module=listen_module,
    upstream_root=root,  # 已装固定SDK的xiaozhi-server Path，不是主项目路径
)
```

安装返回 `{"version":1,"installed":true}`，重复安装幂等；必须已安装永久撤权。
先复用 `verify_control_snapshot(root)` 检查既有固定源码字节，未知源码拒绝安装，不下载或覆写上游。
`send_timeout`默认2.0秒，可显式传0..5秒内正数，仅用于写出/取得发送门的期限，不是播放静音指标。
不使用新依赖；实际WebSocket库沿用已装3.10环境的websockets14.2。

每个ConnectionHandler进入handle_connection前得到自己的SocketProxy；原始socket只保留在该代理内部，
原固定上游接收循环、direct_v2、MCP、heartbeat及已导入别名通过它写出。
原config/xiaozhi和welcome先隔离本连接副本，hello确认不写共享配置。
包字节不重封装；原有v1/v2/MQTT二进制封装逻辑保持原路径，MQTT本协议不协商。

只有客户端严格true、直接WS、pipeline、配置明确本地CustomTTS Cosy URL，并且类钩子和最终packet/
send_tts/hello别名/listen别名仍为本次安装的包装时，才在真实server hello写出中确认true。
后装未知包装破坏覆盖证据时不继续写TTS，关闭本连接；应由AI保持安装顺序，而非放宽成“看起来已安装”。
没有确认的legacy连接不添加output_epoch、不发送interrupt；重复hello不升级/降级合同或重置epoch。

## 线序与撤权行为

每次逻辑start分配连接内1..2147483647轮次，before-await固定归属；无显式start的原生音频路径先补start。
旧输出不可复活，前后输入的长intent await也有代次，迟到旧输入不能再提交chat覆盖新轮。
队列音频、源CosyVoicePacket、等待/答案包及控制消息在最终发送前核对同一输出租约。
旧LAST等待同时核对wire轮次，即使新的start先于新UUID创建，也不能先清新controller再丢旧stop。
唤醒/listen持有的旧函数别名保留原包装并加入同样的租约，不能只替换模块公开名字。

所有实际ws.send都共享异步发送门。native clear_queues/ASR/close先撤权；abort来源的原始普通stop
被转换为带其捕获旧轮次的interrupt。任何后续新发送会先完成待发interrupt，再发送下一轮start。
正在await网络的旧写出允许先完成；原生rate.reset取消其调用者，也要在有界期限内完成/失败关闭，
不能提前释放门让旧帧越过interrupt。等待门的旧请求被取消不泄漏锁。
自动start也是一次await，返回后再核对归属，防止其间撤权后再开始旧音频写出。
无归属binary/fragment iterable在v1下拒绝，不借“当前轮次”猜身份，也不增加原生packet_count。

正常stop保持原生发送队列排空及预缓冲等待，只加同轮output_epoch，既不改成interrupt也不清设备队列。
设备是否按修订3等待active_decode/active_output，是AH消费者实现与联合验收责任；服务端没有据此发播放回执。

写出或等门超时会撤销本连接、在0.5秒关闭窗口后必要时abort自己的transport，并取消/有界收尾自有写任务；
失败保留首次reason（不被随后close覆盖）。计数active_writes如不为0，不能声称已完成清理。
close、epoch耗尽、运行模式或包装覆盖变化都禁止继续写。已交硬件的声音不能从网络撤回。

## 新增只读getter（不改已冻结摘要v1）

`conn._longmemory_tts_interrupt_snapshot()` 或 `protocol_snapshot(conn)`；无连接传None。
本阶段没有直接修改device_control/control_http导出，由AI在明确当前连接后组合此可选摘要。
字段固定、无文本/音频/UUID/身份/路径/事件列表：

```json
{
  "version": 1,
  "state": "negotiated",
  "negotiated": true,
  "reason": "confirmed",
  "counts": {
    "hello_confirmed": 1, "start_sent": 2, "audio_sent": 20,
    "subtitle_sent": 1, "eos_sent": 1, "interrupt_sent": 1,
    "stale_dropped": 1, "unowned_dropped": 0, "send_timeout": 0, "closed": 0
  },
  "active_writes": 0,
  "device_playback_acknowledged": false
}
```

state枚举 `no_connection | not_installed | hello_pending | legacy | negotiated | closed`。
reason枚举 `no_connection | not_installed | hello_pending | legacy_not_confirmed | confirmed |
epoch_exhausted | connection_closed | send_timeout | gate_timeout | cancelled_write_unsettled |
send_failed | mode_changed`。counts键固定为模块COUNTERS；未发生为0，整数非负。
negotiated只说明本连接双向确认，不证明设备队列已清或物理声音停止；closed后它保留握手事实，
UI必须先看state/当前连接，不从上个连接沿用getter。读状态不创建任务/状态，不发模型或设备命令。
count_*_sent计应用写出返回，不是设备收到/播放回执。

## 本次实际CPU验证与限制

随机127.0.0.1端口，真实websockets客户端/服务端，固定SDK的handle_connection、hello、ASR交接、
abort、sendAudioHandle、AudioRateController和清队列方法经AST提取；其他配置、路由和执行器为合成替身，
不启动ASR/VAD/LLM/GPU或读取个人库。入/出网络确为真实WebSocket，不只调用fake sender。

覆盖双向确认/旧客户端/字符串true/非pipeline/MQTT回退、旧新消费者CPU合同预言机、
在真实底层ws.send前暂停旧帧后插入abort、新start/旧排队帧、已进网络的调用者被取消、
等待门被取消、普通EOS尾帧保留、原生已导入别名晚stop、等待/答案及停止提示音、迟到旧intent、
重复hello不变合同、epoch耗尽、显式close、网络写/等门超时、安装覆盖被改变、补start期间撤权。

真实Opus先解码旧轮首帧，至少80个样本（16kHz下5ms）abs≥200后执行正式startToChat。
interrupt后旧音频帧0；同编码器reset后新轮20帧完整且逐帧解码能量门通过；新帧接收跨度一次测得
834.335ms，符合原生前5帧预发加队列首帧后60ms调度，不把20帧一次突发当连续播放。
此数是环回客户端接收跨度，受调度影响，不是模型性能/设备播放时长或固定延迟保证。
该案例的旧/新音频为合成波形，补充之前HTTP/FIR/Opus四组合验证，不冒充真人ASR或设备听验。

消费者预言机只验证期望线协议：legacy stop保留已收队列，v1 interrupt关闭门并撤销旧队列，正常EOS不截尾。
它不是AH固件代码执行结果；跨连接本地generation、异步UI与active任务排空仍须AH/AI对其实际代码验收。
尚未运行组合启动器、日用服务、设备声音/打断，也未恢复adaptive日用。

扩大CPU回归160 passed；文档维护工具自身14 passed。收尾期间发现一个既有合成HTTP交接竞争：
本地reader已退出但服务端生成锁finally尚未释放，新请求返回精确503 busy并未进入合成，
服务端阶段证据为旧请求client_disconnected、新请求busy。该问题不能归因于新WS线协议。
消费端现在只对JSON精确`{"error":"busy"}`的503做最多400ms等待重试，20ms内持续检查永久撤权；
其他503/重启需求/错误码/额外字段及已经成功进入的200流不重放。
专项验证忙后成功、其他故障只请求一次、等待取消和耗尽边界；旧有有声后交接四组合保持原断言。
这不证明实际Cosy模型能够在400ms内释放；超限仍走原失败/回退，不能声称日用可复用已经验收。

文档严格检查未通过：当前AD独立文档未登记共享manifest，--only报unknown-selection，
没有实际选中文档做正文检查。按文件归属未改共享清单；由主会话整合登记，本交付不冒称文档全验通过。

## AI接力修正与隔离装配

以上为AD冻结 `ff6ef6e6` 的原交付记录。AI在 `0970e5bf` 接入正式启动顺序的隔离源码：永久撤权及完成交接之后、control/app之前安装wire代理，candidate OFF同样适用；没有操作生产。状态字段为可选 `tts_interrupt`，沿当前连接getter、控制HTTP及3.12严格投影返回，保留16KiB响应上限，前端只加类型。closed保留曾协商事实，断线后不沿用旧getter；物理ack始终false。

修订4补齐服务端EOS后的尾音窗口：普通stop照常发送并保留尾音；随后正式ASR交接、显式abort和控制面板stop仍可撤销同epoch并发interrupt。控制面板不再仅凭服务端队列空/speaking=false返回already_idle。重复abort不重发，旧轮不复活，下一轮start仍在线序屏障之后。

400ms精确含义为**首次收到严格503 busy之后的重试准入预算**，包含后续退避、connect及响应头；每次请求前复核剩余预算，各阻塞步骤使用剩余时间，watcher同时取消过期自有socket。首请求保留原超时；后续收到200即结束准入预算，生成体使用原读取超时，任何200之后错误都不重放。400ms不是包含首请求、清理和操作系统调度的硬墙钟保证，也不证明真实模型能在该预算内释放。AI组合首次暴露socket超时可能略早于单调deadline而泄漏TimeoutError，修正为稳定失败准入；失败JUnit与后续验证分别保留。具体结果、消费者边界及文档接力见[AI记录](AI-hy-advanced-low-latency-20261021.md)。
