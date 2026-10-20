# ADR 0196：有界音频话轮结束判定与原端点回退

2026-10-21。状态：候选适配已实现；真实模型、中文音频校准与圆屏体验未验收，日用不启用。

## 事实与目标

小智固定源码 `eb4b28c59ed7ed885258498cf757ce14352d620e` 在 Opus 解码后产生 16 kHz 单声道 PCM16、每帧 1920 字节；Silero 在静音达到配置阈值时设置 `client_voice_stop`，ASR 的 `receive_audio` 在此帧追加音频、正式识别并重置缓冲。既有 ASR 预取不决定端点。当前固件参考源码中的 AFE（音频前端）输出回调未按 VAD 状态过滤帧，监听状态持续编码发送，故服务器具有音频判断条件；这只是源码条件，不证明当前设备在网络抖动下持续到包。

## 决定

在语音适配进程内新增可插拔判定器，包裹本地 ASR 子类的 `receive_audio`，在原方法清空音频前作同步、无等待决策。原 ASR 获得完整原字节，仅模型输入截取话轮末尾八秒。Memory Core、数据库、固件、音频播放和学校网关均无依赖变化。

默认 `off` 不安装补丁；`shadow` 运行同一判定逻辑但不改变原端点；`enabled` 还须组合层提供 `calibration_approved=True`。此参数表示外部真实校准决定，不能当作证明本身。以重新启动、恢复 `off` 回退，不支持在线反复包裹或静默更换模型。组合接线由 AI 独立会话拥有。

选定官方 Smart Turn v3.2 CPU ONNX 候选，启动前核验固定大小与 SHA-256，再显式创建 CPUExecutionProvider、单线程 ONNX 会话。适配遵循官方固定源码的左侧补零、末尾截断、16 kHz Whisper 特征与概率输出；官方 inference.py 的默认文件名仍为 v3.1，本适配明确绑定 v3.2 CPU 文件。尚无该真实文件的本机兼容运行证据。模块 import 不访问 Hub、不下载模型、不隐式加载 session。

每个安装实例共享一个真实 CPU 推理工位。结果预算默认 150 ms、每个完整话轮至多四次推理；默认从 300 ms 静音尝试，高分也需等到 420 ms，低分最多等到 1800 ms 静音。续说废弃旧结果、增加音频版本和取消代次，但不重置整轮推理预算。线程超时只能撤销结果权限，真实锁直到同步推理退出才释放；繁忙、缺模型、异常、非数值结果退回原静音端点，不堆积任务。接收端不等待模型，结果在后续帧轮询；无后续帧时不另造定时提交。默认参数是候选值，未作为中文质量最优值。

## 事件契约

`on_event(connection, event)` 是同步、快速、不得阻塞的回调。`event.version=1`；`type` 为 `provisional / continued / confirmed / cancel`，对应 `signal=eou / continued_speech / confirmed_turn / cancel`。附带 `turn_id、audio_revision、cancel_epoch、transcript_revision、mode、authoritative、reason、silence_ms`。标识均仅在连接内有效，不能跨连接比较；正文、音频、摘要、设备标识不进入事件。

`turn_id` 初始 0，重置/重新监听/关闭时递增；`audio_revision` 初始 0，续说时递增；`cancel_epoch` 在活动判定取消时递增，先发旧音频版本的 cancel，再发新版本的 continued。`transcript_revision=null`，由 AE 在获得实际 ASR 候选后赋真实文本版本。音频版本不能替代文本版本。

provisional 永远 `authoritative=false`，只说明模型候选完成。enabled 的 confirmed 才表示本模块允许该帧正式提交；continued/cancel 在 enabled 为 authoritative，撤销旧候选权限。shadow 所有事件均无提交权限，包括其假设的 confirmed。confirmed 只确认端点，绝不表示识别正文已核验、记忆已写、工具可执行或音频可播放；AE/AI 还须通过完整原输入、真实 ASR 文本、上下文与预算门控。

手动、流式 ASR、声纹、助手正在播放、停止连接、无有效发声时间戳、非标准 PCM 不启用判定，保留上游行为。显式 `listen stop` 经另一上游路径重置再调用正式识别，本补丁不拦截该路径；重置事件撤销旧候选，组合层应按正式 ASR 交接处理，不强行复用。

## 验证与启用条件

[AC 记录](../development/parallel/AC-smart-turn-20261021.md)保留文件摘要、事件样例、隔离测试、合成回放、公开 WAV 标签格式与所有者下载命令。合成回放报告误切、超过 1200 ms 仍未判停的漏判及最终端点 P50/P95，注入错误高分/低分，不伪装真实中文模型准确率。公开 WAV 工具使用人工 VAD 标签和补零尾，不等于真实 Silero 或设备播放验收。

启用前必须在同一公开/合成中文标注集上比较 off/shadow/enabled 的误切、漏判与端点延迟，尤其包含思考停顿、列举、短答、续说及慢推理；误切相较原端点不增加，完整句漏判不增加、延迟有改善并覆盖置信区间/样本规模后，才由主会话决定是否进入受控实机。最终以用户说完至首个有效回答声音衡量，并同时核验连续性、续说取消、打断残音和记忆一致性；提示音、推理内容或模型推理耗时不能替代该指标。

## 来源

- [官方固定 Smart Turn 源码](https://github.com/pipecat-ai/smart-turn/tree/4786657e242dfe77dd138699ac564ee074a2a543)
- [官方固定模型目录](https://huggingface.co/pipecat-ai/smart-turn-v3/tree/f766f81d3cfdf7737ac64aad813d91bbfd56bf93)
- [官方 v3.2 CPU 中文基准](https://huggingface.co/pipecat-ai/smart-turn-v3/blob/f766f81d3cfdf7737ac64aad813d91bbfd56bf93/benchmarks/smart-turn-v3.2-cpu.md)
