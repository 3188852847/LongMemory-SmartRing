# AC：输入打断阶段观测

2026-10-21，基线 `58ca0f3282e4b3e54c38e821eafb60d09e46e82e`，分支 `codex/ac-input-interruption-20261021`。原融合分支和实验原样保留。本段不启用 Smart Turn/预生成，不改行为、端点、AEC、固件、ASR预取、AD音频或AI启动器/控制端；无真实音频、模型、网络端口、GPU/COM3或日用进程操作。ROOT 后续告知 7fcddd49 仅故障文档，不据此重复实验。

## AI 可立即接入的生产 helper

[voice_input_observation.py](../../../scripts/development/xiaozhi/voice_input_observation.py) 与合成 [voice_input_interruption_probe.py](../../../scripts/development/xiaozhi/voice_input_interruption_probe.py) 分开。AI 在既有包装全部完成后、连接创建之前安装：

```python
from voice_input_observation import (
    install_voice_input_observation, voice_input_observation_snapshot,
)
install_voice_input_observation(ConnectionHandler, asr_base, receive_audio_handle,
                               asr_provider_classes=(fun_local.ASRProvider,))
# 对实际连接只读领取；也提供类上静态getter _longmemory_voice_input_observation_snapshot。
value = voice_input_observation_snapshot(connection)
```

必须传实际本地 ASR 子类，覆盖已有预取包装捕获的别名；helper 同时包装 ASR base 与 receive 模块的 handleAudioMessage 别名，并按连接/阶段防止重入重复计数。队列代理在 open_audio_channels 启动工作线程之前附着，保留原 Queue 及其 FIFO/异常/返回对象；VAD 代理只委托原模型调用，不加载模型或改参数。不得热装至正在处理数据的旧连接后声称历史计数完整。安装报告的 `specific_asr_classes/queue_before_worker` 可核对覆盖范围。

固定 snapshot 顶层：`version/state/counts/inflight/queue_depth/current_flags/last_handle_flags/endpoint_packet_count/endpoint_pcm_bytes/buffer_frames_before_receive/formal_audio_frames/formal_pcm_bytes/counter_saturated/value_kind`。

- counts：queue_put/get、vad_check/speech/error、route_no_enqueue、just_woken_skipped、stop_flag_receive、stop_without_formal、endpoint_length_rejected、result_empty/nonempty/unknown、observer_error；另有 route/handle/receive/formal/speech/abort 各自 begin/return/error/timeout/cancel。固定键、饱和至 2^31-1；inflight 为六阶段的当前在途数。
- flags：client_aec、client_is_speaking、just_woken_up、client_have_voice、client_voice_stop、listen_mode（auto/realtime/manual/unknown）。last_handle_flags 是最近处理帧时的状态，不是失败口令的历史回补。
- buffer_frames_before_receive 是 stop flag 为真时、原接收调用前的缓存长度；formal_audio_frames/formal_pcm_bytes 是正式 handle_voice_stop 的实际任务列表长度/总字节数。上游可能将16个PCM帧合并成一个列表元素，因此 formal_audio_frames=1 不表示只收一帧。
- endpoint_packet_count/endpoint_pcm_bytes 仅在已核验 LOCAL 分支由实际 formal 实参长度匹配或长度门拒绝且实际重置后给值，其他分支为 null。不是网络包数；缓存包含预留和静音。原函数虽先追加当前包，纯噪声分支随后会截取缓存，不能把所有 len+1 都叫实际端点包数。
- stop_without_formal 仅表示接收调用没进入 formal，不等于长度门。endpoint_length_rejected 另外要求：LOCAL auto/realtime、有VAD发声上下文、实际字节数不超过 1920*15、无 formal 调用并观测到 stop flag 清除/缓冲重置。manual、stream、纯噪声缓存、异常不混入该计数。
- 计数自附着起累计，端点字段为最近一次 stop 接收/正式调用边界；ROOT 应对复测前后取差值，不能把上轮端点字段当作失败口令的帧数。speech 返回只判结果类别，不存/打印文本；被上游内部吞掉的错误不冒称向外抛错，empty 也不说明具体原因。
- state=no_connection（无连接对象）、not_observed（未附着）、unavailable（观测失效）时缺测字段为 null，不填零。observed 为有效计数；closed 表示持有的连接对象 stop_event 已置位，保留当前累计值，不代表设备静音证明。连接对象释放后不能追溯旧 AEC/计数。

原业务返回对象、异常及取消原样传播，不新增超时；观测失败不重试业务、getter 返回 unavailable/null。只计数和状态，不保存音频、正文、身份、摘要、逐帧历史或日志，不更改日志白名单。value_kind 明确这些不是 CPU 耗时。AI 自行接公共 launch/device_control 投影，AC 未改两文件，也未改 voice_input_latency.py。

## 已完成的源代码与合成定位

只读核对原小智提交 `eb4b28c59ed7ed885258498cf757ce14352d620e`；固定方法快照 [xiaozhi_input_snapshot_eb4b28c.py](../../../tests/fixtures/xiaozhi_input_snapshot_eb4b28c.py) 保留 MIT 许可和五文件 SHA-256，仅 AST 规范化排版，无外部模型导入。实际方法控制流保持，VAD/解码/识别结果注入，不能当声学准确率。

1. 播放中、AEC=false 的二进制消息仍解码入队、检查 VAD 并进入 ASR receive。播放布尔只禁止预取调度，正式识别仍能发生。
2. just_woken_up 分支在 VAD 后、ASR receive 前返回，源码恢复任务等待2秒；合成证明该分支不等于 ASR 空结果。
3. AEC=true 且播放中 VAD 阳性，先 await abort/stop 发送，再 ASR receive。合成阻塞 socket 时出现 queue_put=2、handle/VAD=1、ASR receive=0、队列剩1，证明前后顺序。AD 已提供相同背压边界，本段不扩充重复场景；当前生产 socket 外层另有发送超时保护，裸阻塞例不证明现场会静默等待四十多秒。
4. 上游 ASR 单工作线程对每个 handleAudioMessage future.result() 串行等待；合成识别等待时，已有入队2帧而只处理第一帧的 VAD。该路径并未内置识别超时，计数不能凭等待时间伪造 timeout。
5. 原长度门严格大于15帧。7/15总帧在 VAD 上下文已成立时可完成接收/重置但不进入正式识别；16总帧进入正式方法。没有修改阈值。

上述是条件性候选分支，**没有重现现场根因**。ROOT 转交的 12:21:27 后缺新 asr_entered 只代表未观测到新的 ASRProviderBase.handle_voice_stop 入口，不能证明未收到上行、VAD未运行或所有识别内部路径均未调用。前一轮存在成功中断/后继 ASR，也不证明失败口令的 AEC/采音状态。先用本 helper 的队列/VAD/长度门/在途计数，结合现有 natural_interruption_diagnostics，准备一次带观测的复测。

## 验证与交接

[test_voice_input_observation.py](../../../tests/unit/development/test_voice_input_observation.py) 加原 ASR 预取/输入计时回归 **43 passed**，覆盖getter缺测、播放转发、刚唤醒、7/15/16帧、实际预取包装下正式ASR、abort等待、识别在途、空结果、固定计数饱和、重复安装、观测失效、原异常/取消。无真实模型运行。

另用实际小智 Python **3.10.20** 运行标准库 asyncio.wait_for 的真实超时反例，确认 asyncio.TimeoutError 与内置 TimeoutError 在该环境不同；helper 同时分类二者，speech_timeout=1、speech_error=0、inflight=0，异常原对象向外传播。不是只用3.12证明3.10兼容。

ROOT/AI 可先整合 helper 与 getter，使用 buffered 保守配置，不混入融合/AG/AB业务。现场复测、原因确认及后续行为修复尚未完成；不得将合成边界写成每次真实“停一下”失败原因。
