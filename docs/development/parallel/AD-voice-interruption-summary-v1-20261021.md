# AD：进程内撤权与只读摘要 v1

2026-10-21。该接口不触发模型，不读取文件，不发设备命令；只返回当前明确连接的内存状态。
尚需主会话集成启动器，不能把文件存在当成日用已经安装。显式设备interrupt协议另见
[消费者合同候选](AD-tts-interrupt-v1-20261021.md)，本helper尚未实现该协议，也不保证0015设备已收残音消失。

## 安装与出口

在既有输入/ASR、voice_latency、waiting_sender和可选AE包装之后、control/app运行之前无条件调用：

```python
from voice_interruption import install_voice_interruption
from core.providers.tts import base as tts_base
install_voice_interruption(ConnectionHandler, receiveAudioHandle, asr_base, sendAudioHandle,
                           tts_base_module=tts_base)
```

参数是启动器已经加载的真实类/模块，不在helper里导入上游或模型。
重复调用幂等返回 `{"version":1,"installed":true,"requires_preemptive":false,
"device_playback_acknowledged":false}`。保留两个不同startToChat别名及已有包装，不依赖AE。
不修改VAD/AEC路径；clear_queues钩子先使旧输出永久失效，再执行原生清队列。
正式ASR交接只是末道保护，不能取代更早VAD打断。

连接getter为 `conn._longmemory_audio_interruption_snapshot()`；模块函数 `snapshot(conn)` 同义。
`snapshot(None)`返回无选中连接。状态查询不创建OutputState。
`device_control.DeviceControl.status()`新增可选字段 `voice_interruption`；沿用原HTTP只读路由/鉴权。
每次只用 `_connection()`当前唯一、打开、已绑定且工具就绪的连接；无法明确选中时返回no_connection空摘要，
不回放last_voice_latency之类历史计数。它表示无可用选中连接，物理连接数仍看外层connection_count/reason。
无须修改control_http，也不新增路由。3.12严格投影与前端由AI负责。

## 精确schema

所有键固定；无正文、音频、设备标识、sentence UUID、路径、原始错误或事件/帧列表。
counts的键见模块常量 `COUNTERS`，未知键不进入摘要；last_stage只保留一个事件。
单位at_ms为此连接首次运行活动后的perf_counter毫秒偏移，不是绝对时钟或设备播放时间。

```json
{
  "version": 1,
  "enabled": true,
  "connection_present": true,
  "installed": true,
  "status": "observed",
  "epoch": 1,
  "active_output": false,
  "active_tts_calls": 0,
  "closed": false,
  "configuration": {"delivery_mode": "adaptive", "value_kind": "configuration"},
  "observed": {
    "value_kind": "observed_client_branch",
    "producer_path": "adaptive_buffer",
    "request_delivery_mode": "incremental",
    "v2_transport_confirmed": true,
    "server_model_delivery_mode": "unconfirmed",
    "server_reply_cache_hit": "unconfirmed"
  },
  "counts": {},
  "last_stage": {"event": "asr_handoff_revoked", "at_ms": 1000, "epoch": 1},
  "device_playback_acknowledged": false
}
```

示例counts为缩略，实际必须含所有COUNTERS的非负整数值（未发生为0）。
status枚举 `no_connection | not_installed | idle_no_samples | observed`；installed是类钩子实际标记，
enabled表示当前连接属于本地Cosy候选，不表示设备打断能力。
无连接epoch=null，其余epoch是非负进程内撤权代次（**不是**拟议线上output_epoch）。
configuration.delivery_mode枚举 `buffered | incremental | adaptive | unknown | null`；
没有属性unknown，非Cosy或无连接null。不沿用旧连接的配置值。
observed无实际生产分支样本时null；producer_path枚举
`adaptive_buffer | incremental_pcm | buffered_pcm | preset | complete_wav_fallback`，
request_delivery_mode为 `incremental | buffered | full_wav | null`（preset=null）。
传输v2仅说明本次客户端校验通过响应头，不证明服务内部模型stream设置或缓存命中，后二者固定unconfirmed。
last_stage无活动时null；event只来自COUNTERS；读取不能改变计数/阶段。

first_segment_callback_returned指首次编码回调已返回，不是网络发送；
first_answer_send_returned指该轮真实应用发送函数返回且packet_count增长，不是播放器听到；
cue_send_returned单列；撤权时正在await的旧写出返回只算inflight_old_send_returned，不能变成新轮首发。
snapshot中active_output是服务端保守生命周期标志，不是设备声卡状态；active_tts_calls是当前未返回的调用数。
不据此展示“已恢复/可打断/听见声音”。观测有样本也不能替代owner验收。

## 验证边界

纯CPU固定SDK提取、状态竞争测试和随机环回HTTP/真实FIR/Opus测试；无ASR、VAD、LLM、GPU模型计算。
Opus测试在解码PCM有至少5ms样本绝对幅值≥200后调用真实固定startToChat；检查布尔已复位但UUID未变
时旧生产退出、旧发送不再增加、同编码器新轮20帧/1.2秒完整解码。它证明软件交接，不模拟ESP实际队列。
固定SDK缺失时对应提取测试skip；原生Opus需所有者已安装3.10环境，不自动安装依赖。
