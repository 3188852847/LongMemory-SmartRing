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

依赖用途：ONNX Runtime 执行 CPU 模型、Transformers 提供 Whisper 特征、numpy 提供 PCM 转换；替代方案是继续原静音端点，不引入 Pipecat 全框架/PortAudio/录音依赖。小智环境缺 Transformers，禁止自动补装日用环境。下面仅创建 AC 独立 Python 3.10 验证环境，固定直接依赖，不安装 torch、不改全局/生产/原锁文件：

```powershell
$acTree = 'D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ac-smart-turn-20261021'
$acCheckEnv = Join-Path $acTree '.venv-smart-turn'
if (Test-Path -LiteralPath $acCheckEnv) { throw '验证环境已存在，先核验，不覆盖' }
& 'D:/03-项目/01-正式项目/智慧圆屏/local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/.venv/Scripts/python.exe' -m venv $acCheckEnv
if ($LASTEXITCODE -ne 0) { throw '创建验证环境失败' }
$acCheckPython = Join-Path $acCheckEnv 'Scripts/python.exe'
& $acCheckPython -m pip install --index-url https://pypi.org/simple 'numpy==1.26.4' 'onnxruntime==1.20.1' 'transformers==4.57.6'
if ($LASTEXITCODE -ne 0) { throw '安装验证候选失败，不换源重试' }
& $acCheckPython -m pip freeze
```

此命令是尚未执行的兼容性候选，传递依赖未锁定，不能作为生产可复现锁定证明；所有者运行后需记录 freeze、包来源与冷/热实测，再由 AI 设计正式进程中的依赖接线。不会向 .venv 或既有锁文件自动增加依赖。真实模型到位后先只跑上述离线中文标签回放；没有本轮调度不发学校请求，也不启动日用。

## 未验证与主会话下一步

1. 主会话转 AE/AI 采用上述事件；AI 独占修改 launch_with_memory 与公共清单，登记本记录/ADR。候选文件提交后可先在缺模型条件下组合验证 shadow/unavailable。
2. 所有者获取固定模型及独立验证依赖；AC 接力核验真实 v3.2 的输入形状、冷/热 CPU 推理、中文公开/合成标注误切/漏判/延迟。当前真实模型准确率和本机兼容性均未知。
3. 默认 off。enabled 不满足真实校准条件，不向日用切换。最终首答声音、连续性、误抢话、续说取消、打断残音及记忆一致性须组合及所有者实机验收；本次合成检查不能代替。
4. 分支仅由 AC 提交，不 merge main、不 push、不操作其他会话；主会话安排审查、合入、组合回归和发布。
