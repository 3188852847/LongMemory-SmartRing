# AC：有界话轮结束判定候选

2026-10-21。起点 `main=a93258e903954525b88b7af79756aaffe2bd50d6`；工作树 `local/worktrees/ac-smart-turn-20261021`，分支 `codex/ac-smart-turn-20261021`。本记录仅指 AC 隔离候选，不表示日用已接线或启用。

## 交付与文件归属

- [voice_turn_end.py](../../../scripts/development/xiaozhi/voice_turn_end.py)：默认 off、shadow、受校准门控的 enabled；接收边界、单工位预算和事件。
- [voice_turn_end_model.py](../../../scripts/development/xiaozhi/voice_turn_end_model.py)：官方固定 v3.2 CPU 文件核验及特征/ONNX 适配，无下载代码。
- [voice_turn_end_replay.py](../../../scripts/development/xiaozhi/voice_turn_end_replay.py)：合成控制流回放；已本地取得的公开/合成中文 WAV 标签回放入口。
- [专属测试](../../../tests/unit/development/test_voice_turn_end.py)：线程竞争、续说取消、完整原音频提交、与 ASR 预取组合、影子不改端点、模型输入及资源标签核验。
- [ADR 0196](../../adr/0196-bounded-audio-turn-end.md)：主会话预留编号后的架构边界与启用条件。

未修改原 ASR 预取、输入计时、voice_prediction、voice_latency、CosyVoice、launch_with_memory、公共任务书、文档清单或根入口。文档清单/组合接线由主会话转 AI 统一整合。

## 已核实的接入条件

只读核对实际小智固定源码 `eb4b28c59ed7ed885258498cf757ce14352d620e`，以下为本轮 SHA-256：

| 文件（相对小智 main/xiaozhi-server） | SHA-256 |
|---|---|
| core/providers/asr/base.py | `929532c379d18598eff6fbecb991089f25a0c62cd77f74a25a0d1a5b8d13a713` |
| core/providers/vad/silero.py | `aa375cd237c262338b391f8826f35bfe9b3c9e4c77a197bfe75490806d825114` |
| core/handle/receiveAudioHandle.py | `4493dfd77c1bfa7be1a79bb293dbdbf8cad64a6eb2bc53efca3e30efefcb47f1` |
| core/connection.py | `e065c994bf3f926b81c69da045e09fad8c46d6fd1fc3e3a6403295aeab64e0fa` |

Connection 的 Opus 解码器固定 16000 Hz、单声道、960 样本（60 ms）；Silero 先更新发声状态及 `client_voice_stop`，随后调用 ASR `receive_audio`。原方法追加 PCM 并在端点识别/重置。新增包装在追加之前判定，原方法只追加一次；不改原 PCM 或截断正式 ASR 输入。现有预取的正文/完整前缀核验继续保留。

只读查看 `D:/Dev/esp-projects/smart-ring/src/main/` 的 AFE 输出回调、编码发送与监听状态处理。AFE 在可用输出上持续调用输出回调，VAD 状态回调只更新状态，不过滤静音帧；AudioService 输出直接进入编码发送队列。三个文件 SHA-256 分别为 `audio/processors/afe_audio_processor.cc=f17154c7e5147d6d8535f68d9d1a081ef0d4233ad1ae6c4aa9ede74db1a908f4`、`audio/audio_service.cc=278168c5c13ae36912910de646979a6eee7e53cb157aa63c44e6f6591caa601a`、`application.cc=71177e2848a9b6d42ed9473753c3d866172c7a0f6a2058dbc395ffa85487843d`。该 src 无 Git 元数据，未冒称新的固件提交；这些源码事实不证明设备当前到包时序，无串口/固件/设备操作。

## 给 AE/AI 的精确接口

```python
from voice_turn_end import TurnEndConfig, install_voice_turn_end

# AI 先安装原 ASR 预取，再安装本模块；传入实际本地 ASR 子类。
result = install_voice_turn_end(
    ConnectionHandler, fun_local.ASRProvider,
    detector=detector_or_none,
    config=TurnEndConfig(mode="shadow"),
    on_event=on_event,
)
```

`detector.predict(pcm16le_bytes) -> float[0,1]` 是同步可插拔接口，异常/非有限值按失败回退。创建 `SmartTurnCPU(local_path)` 是显式启动阶段操作，缺文件/依赖/不符哈希应由 AI 捕获为 unavailable，再传 `None`；不能在音频接收帧中加载模型或安装依赖。默认配置不建模型，`off` 不包裹任何方法。进程内重复安装抛出需重启错误；回退须重启恢复 off。日志不得输出原异常中的私人路径或载荷。

`on_event(connection, event)` 必须同步且快速，异常被计数并吞掉，不能阻断原识别。事件 v1 示例：

```json
{"version":1,"type":"provisional","signal":"eou","turn_id":0,"audio_revision":0,"transcript_revision":null,"cancel_epoch":0,"mode":"shadow","authoritative":false,"reason":"model_complete","silence_ms":360}
```

| type | signal | 含义 |
|---|---|---|
| provisional | eou | 本版音频模型分数达到阈值，仍无正式提交权限 |
| cancel | cancel | 旧音频候选被续说、重置、关闭或不支持状态撤销 |
| continued | continued_speech | 续说已增加 audio_revision；整轮推理预算继续累计 |
| confirmed | confirmed_turn | enabled 允许原方法在这一帧提交；shadow 仅假设判停 |

标识的作用域是传入的 connection：`turn_id` 初始 0，每次 reset/close 钩子递增（允许跳号）；`audio_revision` 初始 0，续说时递增；`cancel_epoch` 在活动判定取消时递增，旧版 cancel 和新版 continued 共享新 epoch。**transcript_revision 始终 null**，音频层没有权威文本；AE 绑定实际预识别文本时填自己的版本，不能把 audio_revision 当文本版本。重置新 turn 后 audio_revision 归零，cancel_epoch 保持。关闭后状态不会被嵌套 reset 重新打开。

provisional 总是无权限；shadow 所有事件均 `authoritative=false`。enabled 的 confirmed/continued/cancel 有端点或取消权限，但不授权记忆/工具/播放。confirmed 出现在原 ASR 方法之前，AE 必须再核对正式完整文本、上下文版本及预算，不能凭事件直接播放。文本变更仍由 AE 自己管理 transcript_revision/cancel_epoch 的组合一致性。

每个安装实例最多一个真实推理线程任务、每完整话轮至多四次尝试；默认 300 ms 静音起算、420 ms 最早判停、150 ms 结果预算、300 ms 复查间隔、0.7 分阈值、1800 ms 静音上限。超时线程仍持锁，繁忙直接回退；不宣称杀掉了推理。仅标准 LOCAL auto/realtime 可改变端点；声纹、手动、流式、正在播放、停止状态、无发声时间戳、非标准 PCM 保留上游。无后续帧时不另造计时器提交。显式 listen stop 旁路原方法并先 reset，本模块只取消旧候选，正式 ASR 交接由组合层处理。

## 固定官方候选与中文证据

官方 GitHub [源码提交](https://github.com/pipecat-ai/smart-turn/tree/4786657e242dfe77dd138699ac564ee074a2a543)：`4786657e242dfe77dd138699ac564ee074a2a543`。模型仓库为 **pipecat-ai/smart-turn-v3**（不是另造 v3.2 仓库），[revision](https://huggingface.co/pipecat-ai/smart-turn-v3/tree/f766f81d3cfdf7737ac64aad813d91bbfd56bf93) 为 `f766f81d3cfdf7737ac64aad813d91bbfd56bf93`。

- 文件 `smart-turn-v3.2-cpu.onnx`，8,679,182 字节。
- 官方 LFS SHA-256 `2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f`。
- [固定下载 URL](https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/f766f81d3cfdf7737ac64aad813d91bbfd56bf93/smart-turn-v3.2-cpu.onnx)。只读取官方元数据与源码，**未下载权重**。
- BSD-2-Clause 来源；适配器独立实现调用步骤，没有复制官方文件，也不 import 会在顶层隐式加载 session 的示例。

[官方 CPU 报告](https://huggingface.co/pipecat-ai/smart-turn-v3/blob/f766f81d3cfdf7737ac64aad813d91bbfd56bf93/benchmarks/smart-turn-v3.2-cpu.md)中文 929 样本，accuracy 85.79%、precision 0.894、recall 0.818；报告写作 FPR=4.95%、FNR=9.26%。[固定 benchmark.py](https://github.com/pipecat-ai/smart-turn/blob/4786657e242dfe77dd138699ac564ee074a2a543/benchmark.py#L144)明确用 FP/总样本数、FN/总样本数作分母，不能把前者当 FP/全部未说完，或把后者当 FN/全部已说完。官方阈值 0.5，与本候选默认 0.7 不同；该静态片段分类报告没有用户停嘴到判停/首答声音时延，不是本机中文话轮验收。

## 实际验证

使用主项目已装 Python 3.12.13 解释器，只从 AC 工作树导入源码。专属测试显式断言本模块及 longmemory 的 `__file__` 在分配树内；没有依赖安装、服务请求、个人库、真实录音或 GPU 模型加载。

```powershell
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -X utf8 -B -m pytest tests/unit/development/test_voice_turn_end.py tests/unit/development/test_voice_asr_prefetch.py tests/unit/development/test_voice_input_latency.py -q
```

实际语音相关 **68 passed**；加 `test_doc_maintenance.py` 为 **82 passed**。其中 AC 专属覆盖启用门、影子不改原字节、与预取组合、思考停顿/续说完整字节、迟到分数取消、全连接共享工位繁忙、超时、错误分数、重置/关闭、八秒截断/左侧补零、WAV 与标签边界、脚本误切/漏判统计。新增反例还验证：缺模型不能把较长原端点缩至 1800 ms，没有有效分数不能延后已到的原端点。不是外部完整服务运行测试。

另用小智实际 Python 3.10.20 `-B` 导入 AC 三个模块并运行合成回放，无新依赖、无服务和模型加载，证明控制模块及工具语法/标准库可运行；**未证明真实 ONNX 模型在此环境可用**。本轮元数据核查：小智 numpy 1.26.4、onnxruntime 1.20.1、torch 2.2.2，缺 transformers；主 Python 有 numpy 2.5.2、transformers 4.57.6，缺 onnxruntime。没有跨环境拼接包目录。

主 Python 的真实 `WhisperFeatureExtractor(chunk_length=8)` 对人工 PCM 的八秒左补零输入已完成 CPU 特征计算，输出 `(1,80,800)` 且全有限；未加载 ONNX 模型，不将该检查当模型或生产 3.10 环境验收。文档 strict 检查因两份新增文档尚未纳入 AI 拥有的公共清单，报告 `unlisted-document/unknown-selection`，没有冒称 strict 通过；两份正文另直接调用检查器的链接检查。公共登记交 AI 接力。

合成控制流回放：

```powershell
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -X utf8 -B scripts/development/xiaozhi/voice_turn_end_replay.py
```

固定场景摘要 `9ed8d0e8c8398f908db6cb6a11793e48809ef5b70e539facea9619715fe51e96`。八话轮/五次中途停顿，PCM 是常数人工帧，分数为脚本注入，名称指中文交互场景，不含真实中文声学内容：

| 指标 | off | shadow（实际上游提交） | enabled（候选） |
|---|---:|---:|---:|
| 中途误切/停顿机会 | 3/5 | 3/5 | 1/5 |
| 最后发声后超过 1200 ms 未判停 | 0/8 | 0/8 | 1/8 |
| 最终判停 P50 | 600 ms | 600 ms | 420 ms |
| 最终判停 P95 | 600 ms | 600 ms | 1800 ms |
| 首个有效回答声音 | unknown | unknown | unknown |

原端点 600 ms 仅为该回放统一对照，不声称读取了日用私有阈值。场景含完整陈述、思考续说、列举、短答、240 ms 短停顿、错误高分/低分及慢推理。错误高分在 540 ms 续说前误抢话，错误低分拖至 1800 ms，说明默认候选尚不满足启用标准；不得把该数字当真实中文准确率或上线收益。列举场景耗尽整轮四次尝试后回到原端点，属于有界预算行为。

## 公开/合成 WAV 回放接力

工具不采集麦克风、不访问设备，拒绝未声明 public/synthetic 或非 zh 的清单。每个文件必须在清单目录以内、16 kHz 单声道 PCM16 WAV、资源 SHA-256 匹配；最多 50 例、每例 60 秒标签且标签为 60 ms 整帧。清单示例（所有者或主会话在非私有数据集目录准备真实资源后填入真实摘要）：

```json
{"provenance":"synthetic","language":"zh","cases":[{"audio":"zh-think-001.wav","audio_sha256":"<完整WAV的真实SHA256>","speech_ms":[1200,900],"pause_ms":[780]}]}
```

speech_ms/pause_ms 从音频起点交替覆盖连续时间，最后 speech 后工具补 2400 ms 零静音，只用于观察最终兜底；实际文件至少覆盖全部标签。人工标签代替 VAD 结果，工具按实测特征+模型耗时将结果放回音频时轴，报告 off/shadow/enabled 的逐例误切、超过 1200 ms 的漏判、判停与模型耗时、错误计数。没有音频正文或个人路径输出。真实 Silero、声学噪声、网络到包和设备首答播放仍需组合验收。

```powershell
& '<独立验证环境>/Scripts/python.exe' -X utf8 -B scripts/development/xiaozhi/voice_turn_end_replay.py --manifest '<公开合成数据目录>/manifest.json' --model '<本地固定模型>/smart-turn-v3.2-cpu.onnx'
```

## 所有者执行的精确获取命令（本轮未执行）

下载只写 AC 自己的忽略目录，不覆盖已有文件；固定模型核验失败保留下载文件供排查。以下整段从任意 PowerShell 执行，变量仅限当前会话：

```powershell
$acTree = 'D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ac-smart-turn-20261021'
$acModelDir = Join-Path $acTree 'local/runtime/models/smart-turn-v3.2'
$acModelFile = Join-Path $acModelDir 'smart-turn-v3.2-cpu.onnx'
$acDownloadFile = $acModelFile + '.download'
if ((Test-Path -LiteralPath $acModelFile) -or (Test-Path -LiteralPath $acDownloadFile)) { throw '目标已存在，先只读核验，不覆盖' }
New-Item -ItemType Directory -Path $acModelDir -Force | Out-Null
Invoke-WebRequest -Uri 'https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/f766f81d3cfdf7737ac64aad813d91bbfd56bf93/smart-turn-v3.2-cpu.onnx' -OutFile $acDownloadFile
if ((Get-Item -LiteralPath $acDownloadFile).Length -ne 8679182) { throw '模型大小不符' }
if ((Get-FileHash -LiteralPath $acDownloadFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne '2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f') { throw '模型摘要不符' }
Move-Item -LiteralPath $acDownloadFile -Destination $acModelFile
```

依赖用途：ONNX Runtime 执行 CPU 模型、Transformers 提供 Whisper 特征、numpy 提供 PCM 转换；替代方案是继续原静音端点，不引入 Pipecat 全框架/PortAudio/录音依赖。**原先未执行的独立环境安装候选已撤回，不让所有者安装传递依赖未锁住的大环境。** 主会话随后要求优先复用现有 CosyVoice 解释器，实测结果见下一节。没有创建新环境、补装包或修改任何锁文件。

主会话已给所有者固定模型获取命令，并在收到完成反馈后独立核验大小/摘要，正式交 AC 做真实 CPU 验证。该后续证据另追加；本节第一版下载段只保留来源可追溯，不要求所有者重复下载。所有者反馈长命令不便使用；未来下载/安装须交付已审阅脚本及一条入口，脚本内固定来源、断点续传、禁止覆盖、大小/摘要校验和稳定错误，助手不执行联网获取。

## 免安装 CPU 常驻侧车（第二阶段交付）

新增 [voice_turn_end_sidecar.py](../../../scripts/development/xiaozhi/voice_turn_end_sidecar.py)；只读使用现有 `local/runtime/CosyVoice/.venv/Scripts/python.exe`，实际 Python 3.10.20、numpy 1.26.4、onnxruntime 1.18.0、transformers 4.51.3。该环境同时有 torch 2.3.1+cu121，但侧车子进程在 import 前设置 `USE_TORCH=0/USE_TF=0/USE_FLAX=0`、`CUDA_VISIBLE_DEVICES=-1` 和离线变量，清除 PYTHONPATH/PYTHONHOME；未导入 torch，不加载 CosyVoice 模型或 GPU，不从其他环境拼包。CPU 特征器单次初查约 9.207 ms，不含 import/启动或 ONNX 推理。

沿用官方特征器，没有自行用 numpy 重写算法。对照 [v4.51.3 官方实现](https://github.com/huggingface/transformers/blob/v4.51.3/src/transformers/models/whisper/feature_extraction_whisper.py)与 [v4.57.6 官方实现](https://github.com/huggingface/transformers/blob/v4.57.6/src/transformers/models/whisper/feature_extraction_whisper.py)，固定工具实际比较两环境 NumPy 结果，及主环境 `torch==2.8.0+cpu` 的官方 Torch 路径；参考命令如下，均为 CPU、合成非语音波形：

```powershell
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -X utf8 -B scripts/development/xiaozhi/voice_turn_end_sidecar.py --compare-python 'D:/03-项目/01-正式项目/智慧圆屏/local/runtime/CosyVoice/.venv/Scripts/python.exe'
```

| 合成 PCM | 特征元素 | Cosy NumPy 对主 NumPy 最大绝对差 | 对主 CPU Torch 最大绝对差 |
|---|---:|---:|---:|
| 静音（左补零） | 64000 | 0 | 0 |
| 正负极值 | 64000 | 0 | 7.3313713e-6 |
| 440Hz 正弦 | 64000 | 0 | 6.3180923e-6 |
| 固定种子八秒噪声 | 64000 | 2.9802322e-7 | 8.3446503e-7 |
| 十秒截取末八秒 | 64000 | 3.5762787e-7 | 2.2649765e-6 |

所有形状 `(1,80,800)`，`rtol=atol=1e-5` 全通过。两 NumPy 进程未 import torch；参考 Torch 进程必须确认包版本 `+cpu` 才允许执行。共享 `extract_features` 函数已应用于真实适配器和探针，避免测试另一套处理。上述结果不代替真实 ONNX 加载/输出或中文语音质量验证。

给 AI 的最小生命周期接线：

```python
from voice_turn_end_sidecar import SidecarDetector

# 在服务启动阶段创建一次；不要在 receive_audio 或每个静音帧中创建。
detector = await SidecarDetector.create(cosy_python, fixed_model_path,
                                      startup_timeout=30, request_timeout_ms=120)
# 把 detector 交给现有 install_voice_turn_end，仍保持 off/shadow 和原校准门。
# 已有 InferenceSlot 在线程内调用 detector.predict，事件循环从不读写管道。
# 服务关闭时：
await detector.aclose()
```

进程间通信使用私有 stdin/stdout 匿名管道，不监听端口。请求为固定头+至多 256000 字节 PCM，响应为至多 4096 字节的版本/序号/概率/耗时 JSON；只保留一个请求，无排队预生成或音频日志。专用 I/O 线程处理管道阻塞，预测总预算默认 120 ms，外层原 150 ms 结果权限门仍有效；超时/序号错误/模型错误停用并仅终止自身创建的进程，晚结果不复用，不自动重启。启动最长 30 秒，可异步取消，取消与就绪竞争也回收；服务关闭须执行 aclose。快照只含计数和处理毫秒。

真实 Cosy Python 3.10 子进程、合成检测器、每次 256000 字节的 30 次管道回环：同一 PID，IPC+合成返回 P50=0.084 ms、P95=0.182 ms、max=0.257 ms；全部成功、进程退出回收。**这不是模型推理或用户判停延迟。** 缺模型 probe 返回净化的 unavailable，未泄露文件路径或加载 GPU。

新增真实合成子进程测试后，与原相关回归共 **84 passed**：含常驻复用、CPU 环境隔离、事件循环仍响应、单请求拒绝、超时停用、错序/异常净化、启动失败/取消及关闭回收。首次测试里大字节参数自动生成超长 ID 导致夹具报错，改为命名 ID 后恢复；没有改变输入上限断言。真实 ONNX 与声学验收仍由后续证据说明。

## 真实模型与 CPU 中文合成初筛（第三阶段）

主会话收到所有者下载完成反馈后授权本阶段。AC 独立读取模型并确认 8,679,182 字节、SHA-256 `2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f`，只读使用现有 CosyVoice 解释器，无下载、安装或 GPU 模型加载。

`--probe-model` 已实际创建 ORT 1.18.0 会话，真实输入名沿用 input_features、类型 `tensor(float)`、形状 `["s6",80,800]`（动态批次），提交实际 float32 特征 `(1,80,800)` 成功。provider 仅 `CPUExecutionProvider`，`torch_imported=false`。人工静音输入输出概率 0.9870367050170898，证明输入/输出兼容，**不代表有中文语音或话轮质量**；必须保留上游真实发声/VAD 门，不能把静音概率当识别结果。

固定工具真实模型基准：

```powershell
python -B scripts/development/xiaozhi/voice_turn_end_sidecar.py --benchmark-python '<已有CosyVoice解释器>' --model '<已核验模型>'
python -B scripts/development/xiaozhi/voice_turn_end_sidecar.py --verify-lifecycle-python '<已有CosyVoice解释器>' --model '<已核验模型>'
```

| 检查 | 实际结果 |
|---|---|
| 三次新进程启动，包含 import/模型核验/session | P50 1025.851 ms，P95/max 1055.018 ms |
| 三次首个模型请求 | P50 41.079 ms，max 41.469 ms |
| 60 次热请求（人工八秒静音，含 IPC） | P50 39.279 ms，P95 40.762 ms，max 40.917 ms |
| 工作者特征+模型处理，63 次 | P50 39.054 ms，P95 40.631 ms，max 41.251 ms |
| 默认请求预算 120 ms | 无超时，三个专属进程全部回收 |
| 真实模型进行中立即续说 | 只产生 cancel/continued，audio_revision=1、cancel_epoch=1；迟到分数未复用，事件循环仍运行（3 次 heartbeat） |
| 强制 10 ms 请求预算 | 22.532 ms 返回超时（包含调度/终止开销），随后停用，专属进程回收，不重试 |

这些是 CPU 兼容/资源数据，不是用户停嘴到回答声音。10 ms 是结果等待预算，不是硬实时墙钟承诺；外层 150 ms 结果权限门仍保留。

为避免等待 GPU，新增 [voice_turn_end_synthetic.py](../../../scripts/development/xiaozhi/voice_turn_end_synthetic.py)，使用已装 Windows System.Speech 的 `Microsoft Huihui Desktop` 离线 CPU 合成，不播放、不触碰日用声线/角色。PowerShell 7 查询能列出 Kangkang，但实际选用的 Windows PowerShell 5 合成宿主不支持该声线；初次生成在第二声线处稳定失败，诊断已定位，残留原样保留。当前固定为已实测成功的 Huihui Desktop，rate=0、volume=100、16000 Hz/mono/PCM16，无环境或注册表修改。

六个场景为完整陈述、思考续说、三段列举、短答、短停顿续说、更正；分别合成分句，按 60 ms 能量帧裁首尾，再插入固定静音。语料含 5 次中途停顿，标签是合成结构/能量边界，**不是人工听审的自然中文 VAD 标签**。片段内部停顿仍视为说话段，这限制了结果外推。生成与回放入口分别只需运行现有脚本，输出目录唯一且拒绝覆盖：

```powershell
python -B scripts/development/xiaozhi/voice_turn_end_synthetic.py
python -B scripts/development/xiaozhi/voice_turn_end_replay.py --manifest '<生成的manifest.json>' --model '<固定模型>' --sidecar-python '<已有CosyVoice解释器>' --output '<不存在的报告路径>'
```

语料/音频/完整逐例报告保存在 AC 忽略目录 `experiments/runs/ac-smart-turn-synthetic-828174acab71/`，没有提交 Git：

- 固定文本/停顿规格摘要 `24ab0a14b473b2466c74b4c0c9878ceba586df6f5326f0180242a9715533037c`。
- manifest.json SHA-256 `adb42e113996d7bd90c3a2dcb68e73bbfee87f6a1446d61952378ac10e229ddc`，每 WAV 都有全文件摘要。
- smart-turn-v3.2-results.json SHA-256 `f634f97a9b5ca33f1e0a0a0f8bcb01faae3bccf194a6f5c85a643b80f600c2d4`。
- Sidecar 20 次真实请求成功，failed/timeout/busy 均 0；未调用 ASR、学校模型、记忆或播放。

| 同一六个合成中文场景 | off | shadow（实际上游提交） | enabled 候选 |
|---|---:|---:|---:|
| 中途误切/五次停顿机会 | 4/5 | 4/5 | 4/5 |
| 最后发声后超过 1200 ms 未判停 | 0/6 | 0/6 | 0/6 |
| 最终端点 P50 | 600 ms | 600 ms | 420 ms |
| 最终端点 P95 | 600 ms | 600 ms | 600 ms |
| 首个有效回答声音 | unknown | unknown | unknown |

在这些真实合成语音上，默认 0.7 分/420 ms 候选**没有减少误切**；思考、更正分别误切一次，列举误切两次。样本仅单声线六例、人工拼接停顿，不报告总体中文准确率，不据判停中位改善宣称上线收益。当前仍不满足启用条件，保持 off/shadow；下一步应补自然或公开中文长停顿/续说标注，按说话人和场景分开校准/留出验证。可先用本工具扩大合成模板与说话速率做开发回归，无需 GPU；自然中文与设备体验的证据不能由该扩展替代。

本次真实 WAV 首次回放暴露摘要契约错误：旧 loader 校验 PCM 摘要，文档/生成器定义为完整 WAV。已修正为有界读取完整 WAV 后校验全文件摘要，并增加反例；旧测试夹具也从 PCM 摘要改为真正文件摘要，未放松校验。CLI 现在在模型启动前拒绝覆盖已有报告。

第三阶段相关回归与文档维护测试 **106 passed**（其中语音/生成器相关 92 项）；新增测试不在 pytest 中调用系统 TTS，实际合成和真实模型验证由上述单独工具完成。原始音频/模型/实验 JSON 均验证命中 Git 忽略规则，不提交。

## 未验证与主会话下一步

1. 主会话转 AE/AI 采用上述事件；AI 独占修改 launch_with_memory 与公共清单，登记本记录/ADR。候选文件提交后可先在缺模型条件下组合验证 shadow/unavailable。
2. 模型取得、现有解释器 CPU 兼容/冷热/生命周期以及最小合成中文初筛已完成，无需依赖安装或 GPU 窗口。AI 可接线常驻侧车并保持 shadow；自然中文标注、声学质量与实机仍未验收。
3. 默认 off。enabled 不满足真实校准条件，不向日用切换。最终首答声音、连续性、误抢话、续说取消、打断残音及记忆一致性须组合及所有者实机验收；本次合成检查不能代替。
4. 分支仅由 AC 提交，不 merge main、不 push、不操作其他会话；主会话安排审查、合入、组合回归和发布。
