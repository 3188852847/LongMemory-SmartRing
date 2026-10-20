# AD：CosyVoice 连续播放、可取消缓冲与后端能力接口

日期：2026-10-21。来源 `a93258e903954525b88b7af79756aaffe2bd50d6`，
工作树 `local/worktrees/ad-cosy-continuity-20261021`，分支 `codex/ad-cosy-continuity-20261021`。
任务由主会话分配；本会话仅提交自己的分支，不合入 main、不推送、不向其他会话发消息。

## 第一里程碑：核查、归属与接口

启动已核对分支和干净状态，读取项目 AGENTS、机器通用/Python/Node/GPU 规则、
X 的流式记录和 ADR-0190。主 Python 为现装 3.12.13；测试进程显式从本树导入
`src/longmemory` 与项目适配模块。真实 Opus 仅借用现装小智 3.10 环境做 CPU 编解码，
不加载 torch/模型、不写其源码或环境。未打开端口 18770 或其他日用端口。

文件归属与接线：

| 文件 | AD 范围 |
|---|---|
| `scripts/development/xiaozhi/cosyvoice_streaming.py` | 自有读流线程、连续 PCM、Opus 串行交付、自适应缓冲、取消和供给时间线 |
| `scripts/development/xiaozhi/cosyvoice_segments.py` | 保留现行自然分段与立即排空策略；不以字数猜测模型流式安全 |
| `scripts/development/xiaozhi/voice_latency.py` | 独立脱敏连续性摘要，既有 v6 格式不变 |
| `scripts/development/cosyvoice/service.py` | 后端能力合同与当前实例状态，既有模型/清理/声线链路保持 |
| AD 专属测试、本记录和 ADR-0197 | CPU 隔离验证与交接 |

AG 仅新增引擎适配/基准，不编辑上述服务/播放文件。AI 拥有统一启动接线，
AD 不编辑 `launch_with_memory.py`。主会话已分配 ADR-0197，设计见
[缓冲候选 ADR](../../adr/0197-cosyvoice-adaptive-playback-buffer.md)。

后端接口（供主会话转交 AG）：

```json
{
  "contract_version": 2,
  "audio_stream": {
    "protocol": {
      "supported": true,
      "version": 2,
      "path": "/v1/audio/stream",
      "framing": "uint32be-length-wav-zero-eos",
      "mime_type": "application/vnd.longmemory.wav-chunks",
      "sample_rate_hz": 24000,
      "channels": 1,
      "sample_format": "pcm_s16le"
    },
    "instance_usable": true,
    "incremental_usable": true,
    "default_delivery_mode": "buffered",
    "request_delivery_modes": ["buffered", "incremental"],
    "force_buffered": false,
    "cancellation": "token-boundary-and-join",
    "profile_identity": {
      "state": "valid",
      "config_digest": "<config-sha256>",
      "context_digest": "<model-context-sha256>",
      "selected_voice_warm": true
    }
  }
}
```

上述为字段示例，不是当前日用状态回执。`incremental_usable` 仅当固定运行时适配
明确 applied=True、未 force-buffered、实例可复用、档案未失效时为真。无适配器的
取消语义为 `drain-before-reuse`。profile 摘要缺失为 unavailable，格式错误为 invalid。
`/v1/capabilities` 和 `/health.capabilities` 同源；查询不合成、不暖机。
另一引擎必须实际实现同样的 v2/PCM 合同才能复用客户端，不能只更改 provider 名称。

## 实现边界

显式 `_longmemory_cosy_delivery_mode="adaptive"` 启用候选；缺省仍 buffered。
初始目标 360 ms，欠载后以 180 ms 步长恢复、最高 900 ms；本地 PCM 与预测下游
分别限制为 3000 ms。后续自然段共享当前轮库存；不创建固定的段间等待。
正常短尾在 EOS 放行；出错前积压直接丢弃。旧轮和新轮串行使用编码器，旧清理完成
前新轮不进入编码。未改声线/参考音/语速、原等待缓存、推理/标记过滤或模型选择。

连续性摘要为 `VoiceLatencyTracker.continuity_snapshot()`：每轮最多 32 段、无正文或
音频。包括客户端首有效 Opus、预测可播放/结束时长、最大/累计欠载、缓冲目标/峰值、
重缓冲次数、本地丢弃量、reader join 和客户端接收 RTF。摘要不进入原 v6 严格格式。
同轮后续段的供给时间线是整轮累计，时间原点为首次adaptive合成；缓冲/接收数字
属于当前段。客户端接收 RTF 包含 HTTP/CPU 重采样/背压，不能用于宣称纯模型推理加速。

## 验证记录

首批原有定向回归 86 项通过（9.64 s）。新增 CPU/真实 HTTP/Opus 检查 23 项通过
（5.62 s）。其中四个随机端口真实 Opus 用例各一次，两种输出率×正常/第三帧取消：

| 用例 | 首有效 Opus ms | 原生接收音频 ms | 最终 Opus 帧 | 最大/累计估算欠载 ms | 客户端接收 RTF |
|---|---:|---:|---:|---:|---:|
| 16 kHz 正常 | 664.8 | 750.0 | 13 | 0/0 | 0.8851 |
| 24 kHz 正常 | 233.9 | 749.958 | 13 | 0/0 | 0.4538 |
| 16 kHz 取消后新轮 | 213.3 | 750.0 | 13 | 0/0 | 0.4300 |
| 24 kHz 取消后新轮 | 232.8 | 749.958 | 13 | 0/0 | 0.4554 |

这些是固定正弦波+人工到达间隔的 CPU/HTTP 单次回放，包含 Python 首次导入成本，
不作统计分位、模型 RTF 或真实用户端到端结论。每次完整音频 13×60=780 ms，
仅正常尾部一次填充，原生样本不截尾。取消两例都只交付三帧旧音频、触发后新增旧帧
为零；随后 13 帧新轮完整交付。已交付给下游的 180 ms 不能视为设备立即静音。

背压测试发现旧的“ahead小于上限”判断可以多放一帧，已把下一帧计入准入条件。
随后扩大验证包含旧 finally/新轮并发、截断前 buffered 回退及下面的帧归属竞态。

最终定向组合 **202 项通过（28.98 s）**，包括上述新测试、既有服务/流式协议、
自然分段、真实 FIR/Opus、未适配模型清理与不可复用保护、固定控制流兼容、v6计时。
等待提示/答案交接、提示缓存与表达策略 **46 项通过（0.89 s）**。
最后补充 HTTP 阻塞读与初始 PCM 已缓冲时取消，两项均证实自有socket关闭、
读线程退出、服务生成器finally执行及 generation_gate 释放；该文件含原四个
真实Opus用例，共 **6 项通过（5.82 s）**。该阶段不同用例合计250项通过。

收尾审查发现帧在取消检查与回调之间可能切换全局句子编号。新增 `CosyVoicePacket`
捕获不可重新归属的轮次，计时回调不把旧帧标成新答案，队列入口逐项丢旧保新，
`install_audio_send_observer()` 同时包裹固定小智 `_do_send_audio`，在流控出队时
再检查，保留其他引擎和空 FIRST/LAST 控制消息。没有编辑第三方源码或等待缓存。
加入两项身份/混合批次检查后完整上述组合 **252 项通过（28.22 s）**；再加入
最终出队与重复安装两项检查，相关AD/计时/等待/表达回归 **84 项通过（0.99 s）**。
最后不同测试合计 **254 项通过**，并非252+84重复相加。此软件保护仍不能收回
设备已经接收并缓存的声音，真机残音必须另测。

主环境使用 `-B -X utf8 -m pytest`；全部在 AD 树执行，没有安装依赖。
202项命令的文件集合为：

```text
tests/unit/development/test_ad_cosy_continuity.py
tests/unit/development/test_ad_cosy_http_opus.py
tests/unit/development/test_cosyvoice_streaming.py
tests/unit/development/test_cosyvoice_service.py
tests/unit/development/test_cosyvoice_segments.py
tests/unit/development/test_cosyvoice_continuous_pcm.py
tests/unit/development/test_cosyvoice_unadapted_cleanup.py
tests/unit/development/test_cosyvoice_stream_runtime.py
tests/unit/development/test_cosyvoice_stream_benchmark.py
tests/unit/development/test_cosyvoice_stream_inventory.py
tests/unit/development/test_voice_latency.py
```

46项集合为 `test_voice_waiting_handoff.py`、`test_voice_waiting_cache.py` 和
`test_voice_response_policy.py`。最早一次命令误写不存在的 `test_voice_waiting.py`，
未执行测试；核对实际文件后运行上述46项，没有把不存在的文件视为通过。
`git diff --check` 通过。文档严格检查如实失败：两个新增文档未在公共
`docs/documentation-manifest.json` 登记，报 unlisted-document/unknown-selection；
未跨文件归属编辑清单，交 AI 整合时登记并再执行严格检查。

## 交付状态

代码与 CPU 验证已完成；分支提交由本会话收尾生成，提交号随最终交付给主会话。
没有 merge main、push、部署、下载、GPU加载、真实学校调用或个人库写入。
AG可按上述能力接口核对适配；AI需要按分配范围组合接线并更新公共清单。
GPU与实机矩阵仍为待验收，当前候选不能使日用默认自动变为adaptive。

## 待主会话调度的真实模型验收

目前没有 GPU 授权，未读取或修改共享声音配置，也未启动/停止日用服务。
无需下载新增资源；依赖沿用现装，缺资源时不自动安装。

最小窗口建议两类现行自然段（多句/长句）×buffered/adaptive×三轮，共12调用，
同一当前声线/参考音/语速/精度/种子序列，关闭精确回复缓存；另测初始读流、缓冲中、
已交付后三种取消，每次跟一轮正常回答。预计先申请8分钟硬限，实际时间由主会话
结合日用恢复预算决定；不与 AG 或日用抢 GPU，不由 AD 自行停服。

须记录说完→首个有效回答声音（等待提示不计）、TTS首 Opus、总音频/墙钟时长、模型
RTF、最大/累计欠载、误抢话/续说取消、打断后最后旧声及新轮首声。当前CPU结果
不能替代该矩阵或所有者设备体验，未通过仍 buffered。组合观测接线归 AI。

公共文档清单/主题索引归整合会话同步，AD 不越界编辑；历史 ADR-0190 与 X 结果保留。

## 第二阶段：无需下载的真实GPU评测衔接

主会话后续要求继续取消/缓冲评测衔接，尚未批准任何GPU加载。本阶段只新增
`scripts/development/cosyvoice/benchmark_ad_continuity.py`、
`scripts/development/cosyvoice/benchmark_ad_client.py` 和
`tests/unit/development/test_ad_cosy_benchmark.py`，并追加本记录；不编辑 X 的两个
历史 benchmark、AG 加速模块、AI 接线或第一阶段服务/播放实现。

只读核对 AG 提交 `e6e8db5c82775360b920c3888a104fc0d0242938` 的记录和能力接口。
`probe(..., include_gpu=False)` 仅报告 blocked/needs_isolated_validation，不表示实例
加速就绪。当前最小矩阵使用既有 torch fp16＋hidden-only 原模型，不安装 TensorRT、
vLLM、ORT-GPU，不运行编译/导出，也不把 AG 的候选适配当日用热开关。

### 可执行入口和矩阵

从实际分配、已提交且干净的候选工作树执行；AI组合后将下面 `$benchRoot` 改为
AI已审查的组合树。计划入口无GPU、无需收据、不访问声音档案或联网：

```powershell
$benchRoot = 'D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ad-cosy-continuity-20261021'
$productionRoot = 'D:/03-项目/01-正式项目/智慧圆屏'
& "$productionRoot/.venv/Scripts/python.exe" -B -X utf8 "$benchRoot/scripts/development/cosyvoice/benchmark_ad_continuity.py" --plan
```

真实执行前，主会话独立协调日用停稳、AG等GPU使用者退出、当前声音身份和恢复检查点，
再创建真实JSON收据。AD不创建收据或自行停服。收据字段：

| 字段 | 约束 |
|---|---|
| `schema_version` / `scope` | 整数2 / `ad-cosy-project-model-window`；取代旧v1物理独占含义，见下方WDDM修复 |
| `window_id` | 主会话实际窗口标识，非空；不能用CPU fixture当授权 |
| `checkout` / `candidate_commit` | 实际组合树绝对路径和当前完整HEAD，要求Git干净 |
| `production_root` | 获准只读模型/声音资源所在主项目绝对路径 |
| `project_model_window` / `production_stopped` / `other_gpu_model_workers_stopped` | 均须主会话核实后设为true |
| `physical_gpu_exclusive` | 必须false，Windows桌面仍共享 |
| `shared_desktop_baseline` | 主会话逐项审查的精确身份，不是程序名白名单；字段见下文 |
| `expires_at_utc` | 主会话填写有时区的真实UTC截止；启动时至少覆盖max_seconds＋10秒 |
| `max_seconds` | 60–480；程序不延长或自动取得窗口 |

只有收到该真实收据后，主会话可在相同工作树运行：

```powershell
$receiptPath = '<主会话真实窗口收据的绝对路径>'
$runOutput = "$benchRoot/data/test-tmp/ad-gpu-<真实窗口唯一标识>"
& "$productionRoot/.venv/Scripts/python.exe" -B -X utf8 "$benchRoot/scripts/development/cosyvoice/benchmark_ad_continuity.py" --run --receipt $receiptPath --production-root $productionRoot --cosy-python "$productionRoot/local/runtime/CosyVoice/.venv/Scripts/python.exe" --output $runOutput --max-seconds 480
```

该命令是交接方案，**本阶段没有执行**。输出目录必须全新且位于候选树
`data/test-tmp/` 下，拒绝覆盖。模型worker限现装独立Cosy Python3.10，Opus客户端
限现装小智Python3.10；主Python仅管窗口和自有Job，不混装依赖。

矩阵为两类现行自然段×buffered/adaptive×三个重复，共12个正常调用，按重复交替
模式顺序，每个配对同种子、同声线、同参考音、同精度，关闭回复缓存。另有三种
取消，每种随后在同一编码器执行一个正常新轮，共3对、6轮。模型构造、默认参考
暖机和选中声线暖机另记，全部包含在480秒worker硬限内；主会话另留预检/收尾和
日用恢复时间。全文已可用，不在该矩阵虚构LLM文字到达或ASR等待。

### 不抢日用GPU和不写个人库

父进程核对主会话v2收据、候选HEAD/干净状态、两个解释器路径，再通过下文WDDM
身份门拒绝未批准/未知背景及其他模型进程；不按名称结束进程。worker导入模型前
再次核对，每个用例前后记录检查点；这些采样不证明物理GPU独占或没有背景计算，
仍须主会话在整个项目模型窗口禁止AG/日用等启动模型工作。

worker在收到管道许可前不加载模型。父进程先将其加入专属Windows Job，之后才
发送收据和执行参数；模型、随机端口HTTP和CPU客户端均在该任务树内。到时或
异常只清理自有Job，等其整树退出，写 `owned-job-cleanup.json`；加入Job失败则
只结束刚创建、尚在等待许可的自有子进程。程序不调用日用停止/重启入口，
日用恢复由主会话在确认自有GPU进程退出后按原服务所有权执行。

服务只监听随机环回端口，拒绝全部日用端口。模型进程和客户端封住外部socket/DNS，
启用HF离线，沿用现有ModelScope只读离线保护。所有可写缓存放在本次输出目录，
WeText FST仅经现有相对ASCII路径只读使用；不创建联接、不回写外部源码/依赖。
仅在真实窗口内读取既有选中声音，并在每次调用前后核对同一声音上下文摘要。
构造的公共默认参考暖机与随后当前选中声线的暖机/实测分开记录；报告保存
`voice_scope.selected_uses_default_voice` 与选中声线摘要。选中声线若不同，公共参考
暖机结果不替代它的首声或质量验收；`selected_voice_quality_verified` 始终为false，
直到所有者另行审听/实机验收。不会为得到更快数字切换声线。
固定合成句和生成声音只写忽略的独立证据目录，不连接记忆SDK、个人数据库、
真实学校模型、麦克风或设备；原始音频/日志/JSON不得提交Git。

### 指标含义和放行边界

- `rounds[].first_opus_ms`：首次可解码帧，可能包含前导静音；不是用户端首有效声音。
- `first_energy_qualified_opus_ms`：至少5ms样本幅值≥200 PCM16的首帧，排除静音和
  单点脉冲；仍未证明语义、声线质量或扬声器发声。未找到时保持null，不填0。
- `audio_ms`、`opus_frames`、`total_ms`、`estimated_playback_end_ms`：分别为原生音频
  时长、可播放帧数、客户端TTS调用墙钟、按到达曲线推算的播放结束；两种结束时间不混用。
- `server_generation_rtf`：每自然段从服务请求开始到最后生成PCM的墙钟之和/原生
  音频时长，包含先前块的传输背压；取消样本保持null，不以截短分母比较。
- `client_tts_wall_rtf`：客户端TTS墙钟/接收音频时长，明确替代旧客户端歧义字段
  `rtf`；`continuity[].client_receive_rtf` 另含读流/重采样/预取背压。
- `estimated_supply_gap_ms` / `estimated_max_gap_ms`：累计/最大供给欠载；不是声卡测量。
- `cancel_to_client_return_ms` / `server_cleanup_wait_ms` / `packets_after_cancel`：分别为
  触发取消到本次客户端调用返回、随后健康轮询等待（50ms粒度）、触发后新增旧轮帧数。
  它们不能相加冒充设备残音时长，不能收回已交付的帧。读线程退出和新轮完整性另查。

报告按case/mode给样本数、中位/最大值，保留原始逐帧到达曲线、独立声音文件和
清理摘要。`engine_status`始终needs_isolated_validation、自动放行false，成功跑完
矩阵也不表示可以部署。连续性/音质退化保留buffered回退，由主会话及所有者另验。

AI指出 `llm_first_output_ms` 可能由工具输出触发，本入口明确不使用它作为首文本；
整链路另看 `model_first_text_ms` 和真实ASR话音结束时间。最终验收仍为所有者说完
到首个有效回答声音，排除等待提示/推理内容，并观察连续性、误抢话、续说取消、
插话残音与记忆一致性。该TTS-only基准既不测记忆也不能证明上述整链路通过。

### 第二阶段CPU实际验证

首次专属20项通过（4.42s）：收据边界、GPU占用拒绝、配对矩阵、静音/脉冲门、
五个真实随机环回HTTP/Opus调用（buffered/adaptive与三种取消）。随后增加父Job
许可顺序、超时清理、加入失败清理与无收据worker拒绝，连同第一阶段AD用例
54项通过（11.89s）。全部为CPU/mock/合成正弦波，未运行真实GPU worker。
最终字段/声线范围补充后专属 **25项通过（4.62s）**，两个新增脚本通过Python3.10
语法解析，`git diff --check`通过。不改写第一阶段254项的范围。

公共清单由AI接力增加本阶段两个新脚本及专属测试source关联；AD未越界编辑清单。

## WDDM预检修复：项目模型窗口与经审查的共享桌面基线

主会话真实预检发现旧 `ensure_gpu_idle()` 把compute-apps CSV非空一律拒绝，
在当前WDDM桌面无法执行。AD只读取证复现，未停止服务、未发收据、未加载模型。
本节取代上节原v1收据与“无任何计算进程/物理独占”的过强表述；原GPU测量仍未执行。

[NVIDIA SMI定义](https://docs.nvidia.com/deploy/nvidia-smi/index.html)中 C+G 指同时有
计算与图形上下文，不能视为纯图形；WDDM的进程显存N/A也不能作为未计算证据。
本机CSV还列出权限不可见项，因此改用 `nvidia-smi -q -x -i 0` 的上下文类型，
再合并同UUID的compute CSV中额外PID，缺失XML类型保持unknown，不自动放行。
检测到本机SMI XML声明UTF-8、实际部分路径为ACP936字节，严格UTF-8失败时按系统
ACP解码，拒绝替换乱码后比较路径。没有下载NVML Python包或修改终端/全局编码。

只读快照由新增 `gpu_window.py` 采集：Win32
[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes)
与 QueryFullProcessImageName 用 PROCESS_QUERY_LIMITED_INFORMATION 取得精确创建
FILETIME/映像路径，辅以本地CIM名称、创建UTC、父进程与session，不读取命令行。
路径比较用Windows大小写/分隔符规范，创建标识保留整数字符串，避免PID复用或浮点截断。

### 实际只读证据

`data/test-tmp/ad-wddm-preflight-20261021/snapshot-1.json`（不提交Git）SHA256：
`621452a960921f7a7da77f0b94ccb7052d95febb91d53174be58470f7facf81d`。
本轮快照是driver610.88/WDDM，共38进程：37个C+G、1个C；36个有映像路径和创建
标识，2个为受保护OS逻辑身份（PID4 System与PID23088 DWM）。唯一纯C仍是
PID7196日用Cosy Python，创建FILETIME标识 `134369947639349953`。
本记录不代表主会话已核准停止它；主会话仍须再次核对实际服务owner/启动时间。

先前CSV只显示权限不足的另一个程序，通过有限查询权限已得到实际完整映像与创建
标识，没有按 `Main.exe` 等名称猜测用途。没有关闭或操作它。System/DWM的图像查询
返回AccessDenied，CIM仅提供OS角色和父/会话身份，不能据此宣称二进制映像已验证。
它们的 `identity_state=protected_os_logical` 与普通verified_image明确分开。
GPU Engine性能计数器本次报告无效样本，因此没有用“利用率为零”作为放行条件。

### v2收据和主会话接力

收据改成 `schema_version=2` / `scope=ad-cosy-project-model-window`，并要求：
`project_model_window=true`、`production_stopped=true`、
`other_gpu_model_workers_stopped=true`、`physical_gpu_exclusive=false`。
旧v1/`exclusive_gpu=true`收据不能复用。原checkout/HEAD、到期、480秒和自有Job门保持。

`shared_desktop_baseline` 由主会话审查快照后填写；采集程序不生成已批准基线：

| 字段 | 含义 |
|---|---|
| `gpu_uuid` | 本次快照的目标GPU UUID；不接受另一GPU |
| `reviewed_by` / `reviewed_at_utc` | `main_session` / 主会话真实审查UTC |
| `processes[]` | 主会话逐项核验的背景身份；不是按exe名称或目录批量白名单 |
| 普通进程条目 | 快照的pid、creation_token、executable_path、context_type，另加 `approval_kind=image_identity`、`background_only=true` |
| 受保护OS条目 | 需单独 `approval_kind=protected_os_identity`、background_only=true、非空review_note，并原样固定pid/name/creation_token/parent_pid/session_id/parent_identity/context_type |

受保护OS候选只标识System内核角色或与同session的winlogon父进程对应的DWM；
这**不是自动批准**。主会话若不接受现有逻辑身份取证，应保留阻塞并补证；不能
自动给其他权限不可见程序套用该例外，更不能为获得通过而关闭系统桌面。
任何未解析的非OS owner保持拒绝，即使被错误复制进baseline也不会通过。

新增安全只读命令（从实际候选树运行，输出文件必须全新）：

```powershell
& "$productionRoot/.venv/Scripts/python.exe" -B -X utf8 "$benchRoot/scripts/development/cosyvoice/benchmark_ad_continuity.py" --gpu-preflight --output "$benchRoot/data/test-tmp/ad-wddm-<唯一标识>/snapshot.json"
```

主会话随后逐项审查这些背景角色、单独停止已核实owned日用模型，再按v2收据运行
原 `--run` 命令。AD没有创建真实授权收据或批准本机任何背景进程。采集输出本身
不等于GPU窗口通过，`approval_performed=false`；日用仍在时PID7196的纯C必然阻塞，
即使误将它列入desktop baseline也不能绕过。

### 检查与结果含义

父进程、worker导入模型前、每个case前后核对实时快照。只有与主会话批准的精确
背景身份一致、仍为G/C+G的条目可作为shared desktop context；C+G标签原样保留。
新增PID、创建时间/路径变化、上下文改变、未知类型、重复基线PID和未解析owner均拒绝。
基准模型启动后仅允许worker自己通过Win32取得的精确映像/创建身份成为owned模型，
不允许收据用“允许PID”方式保留其他C进程。出现阻塞只退出/清理自有基准Job，
不操作触发阻塞的外部进程。快照前后检查记录在 `gpu-window-checks.jsonl`。

报告固定 `project_model_window_shared_windows_desktop`、physical_gpu_exclusive=false、
background_noise_present=true。检查点采样不能证明相同背景进程内部没有新计算，
也不能证明两次采样之间完全无人使用GPU；这些限制在报告与成对结果解释中保留。
本窗口只确保主会话协调的本项目模型任务隔离，不宣称物理显卡独占或纯净性能基线。
默认/选中声线、合成数据不写个人库、无下载/无日用控制的边界不变。

最终WDDM/收据/取消/真实HTTP-Opus组合 **75项通过（10.63s）**；两个本轮源文件
通过Python3.10语法解析，`git diff --check`通过。对上述真实快照使用未批准基线
执行分类，allowed=false，PID7196明确为compute_or_unknown_context_not_background；
未把快照或“没有停外部进程”写成独占通过。实际预检没有创建批准基线、收据或GPU
模型实例。修复提交交AI独立审查，主会话继续拥有停/恢复与窗口签发。
公共文档清单需AI增加gpu_window.py与专属测试source关联，AD不修改共享清单。

## 真实项目模型窗口 AD-GPU-20261021-01：完成与归还

2026-10-21主会话在AI独立复审后签发唯一v2项目模型窗口；维护前正式owned日用
已由主会话通过原launcher停止，真实预检已无其他纯C模型进程。主会话逐项批准的
37条共享桌面身份保留，始终不声称物理GPU独占。AD只按一次 `--run --max-seconds480`
执行，没有重试、续租、下载或停止外部进程。受测提交固定为
`172a355de1534e621422aae90de2bab9fcd8dcbb`，Cosy固定源码仍为
`074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`。

主会话最初的已审查基线经PowerShell JSON往返把父进程时间字符串末位0去掉；
严格比较因此拒绝System/DWM。旧文件和失败证据保留，AD未放宽比较或修改基线。
主会话随后用Python原生json从原快照复制，另建
`reviewed-main-baseline-v2-20261021.json`，SHA256
`83c9774832901623f70044cd7eb4efc674356d89a09f38878474053a4e9b3b3a`；AD静态复核
37条完全匹配、唯一阻塞为当时尚在的PID7196。该基线本身不是GPU租约。

### 实际结果（全文已可用，TTS-only）

15/15用例完成：12个正常轮次（两个case×两模式×n=3）和三种取消后接同编码器
新轮。模型构造至可服务18983.981ms（包含导入/默认参考准备，不是纯权重加载），
选中声线另暖机1.699s；worker报告总时长149.920s。每case同种子配对、模式顺序
交替、回复缓存关闭、固定合成文本，保留原自然分段与24kHz/60ms Opus。

下表每格均n=3，单位ms，写作“中位/最大”；音频可播放结束是到达曲线推算，
不是扬声器测量。RTF为服务请求至最后PCM生成时间/原生音频时长，包含块间背压。

| 输入/模式 | 首可解码Opus | 首能量达标帧 | 客户端TTS完成 | 最大供给缺口 | 累计供给缺口 | 服务生成RTF中位/最大 |
|---|---:|---:|---:|---:|---:|---:|
| 多句 buffered | 1789.605/1868.903 | 1791.824/1874.824 | 4409.465/4814.545 | 156.382/226.836 | 156.382/226.836 | .63618/.66807 |
| 多句 adaptive | 1582.236/1627.968 | 1585.521/1631.027 | 5437.864/5523.808 | 0/0 | 0/0 | .76682/.76894 |
| 长句 buffered | 1865.841/1873.823 | 1871.434/1877.118 | 7986.935/8335.095 | 645.414/1007.351 | 645.414/1007.351 | .60366/.60641 |
| 长句 adaptive | 1511.438/1580.149 | 1514.748/1584.578 | 11617.542/11830.188 | 0/0 | 0/0 | .70738/.74575 |

多句原生音频中位6760ms、最长6920ms，长句中位13000ms、最长13280ms。
推算播放结束中位多句buffered/adaptive为8682.452/8407.968ms，长句为
15831.255/14600.149ms；不能把客户端生成完成和播放结束混为同一指标。
adaptive在这六个正常样本中首帧更早且没有估算供给缺口，但生产完成更慢、RTF更高。
样本小且Windows桌面共享，不能泛化为任意文本/背景负载，未达到首有效Opus≤1s目标。
没有ASR/记忆/LLM时间，更没有说完到设备有效回答声音或整链路≤2s的结论。

### 取消与新轮（每边界只有n=1）

| 取消位置 | 已交付旧Opus帧 | 触发后新增旧帧 | 触发至客户端返回ms | 随后服务清理轮询ms | 新轮首Opusms/完整帧数 |
|---|---:|---:|---:|---:|---:|
| 响应头后、首音频前 | 0 | 0 | 86.428 | 2.077 | 1515.941/52 |
| 缓冲中（已积累一个60ms槽） | 0 | 0 | .433 | 75.085 | 1721.326/58 |
| 已交付三帧后 | 3 | 0 | 55.502 | 3.092 | 1459.086/57 |

三次读线程均退出，三个新轮完整交付，服务请求字典/模型guard活动请求清空。
服务清理轮询受50ms间隔影响，不能将两个时间相加冒充设备残音或GPU瞬时抢占。
第三个用例虽然已交付3×60ms帧，前三帧未通过能量门
（first_energy_qualified_opus_ms=null），因此只证明“已交付编码帧后取消”，
**没有证明已发出有效回答声音后的取消**。设备残音、续说、误抢话和实机插话仍未验。
本窗口已关闭，不为补该边界自行重跑；若需补测，由主会话另定新目标/新窗口。

### 当前声线和证据完整性

本窗口从指定production-root读取的档案报告 `selected_uses_default_voice=true`，
测量在选中声线暖机后进行；模型上下文身份仅保留在忽略目录report.json，
不把声音档案/引用资源摘要写入公共Git。
这是本次实际读到的默认/公共零样本声线范围，不把旧自定义声线的历史身份或听感
移植为本次结果，也未为提速修改档案。AI需将该身份与主会话维护前选定档案对齐；
selected_voice_quality_verified=false，声质/当前声线听验与圆屏均待所有者。

正常12轮各保存原生和Opus解码WAV，共24文件；离线核对均为24kHz单声道PCM16，
原生样本数与到达记录总音频时长一致，解码样本数与实际Opus帧数×1440一致，
无空文件或字节截尾。此项不证明语义逐字完整或块边界听感；没有额外加载ASR。
三次取消后的新轮保留了真实解码帧数/逐帧时间线，**未另存新轮WAV**；不能把
正常24文件冒充包含这三段听验音频。所有原始声音/日志/JSON只在忽略目录，未提交。

原始证据保留于AD树 `data/test-tmp/ad-gpu-AD-GPU-20261021-01/`：

| 文件 | SHA256 |
|---|---|
| report.json | `90b350633537d1e902a581c5df2eee06abb4104d86d588f68c39509065fc689b` |
| samples.jsonl | `eba401b43fcbf1b7f591609eafe4f9b851c77faed6760b9541e1ccfe9364dd2e` |
| owned-job-cleanup.json | `aa86fef33deef12e3607d9b08a2184a8e8764232b81e890219c04b80d1be5417` |
| resource-return-check.json | `b54bc293180cc0887b6f166c3f89b8be19a4ed31b0128a5368362988bf2b5128` |
| audio-audit.json | `2ad59f73b66fb247e82365aba37aafd683ae5502688b66faff1da4ccca6c6ccc` |
| cpu-quality-audit.json | `727a5418be0579266d35e250a471e73cacddb8adce13c4882e64292621575f86` |
| cpu-boundary-energy-audit.json | `c2653647dc6160e81e7de915a3a2a69ee83ba2b088b13a4eb0cfd950f9020301` |

模型worker60700、父13572在完成后均不存在，基准客户端亦不存在；自有Job回执为
owned_job_exit_confirmed=true。AD在UTC2026-10-20T20:00:30.039019（北京时间
2026-10-21 04:00:30）独立只读查询时纯C列表为空、剩余37个共享桌面上下文，
该时刻早于主会话日用恢复，不用之后正式日用的GPU进程否定或冒充该回执。

主会话随后独立核对清理并宣布窗口关闭，经原launcher start恢复原版日用；该恢复
由主会话执行，AD未停止/恢复日用，也没有再次加载GPU。本次测量没有上线新功能。
主会话随后确认原服务running/ready=true，原main仍a93258e、配置未变；该状态来自
主会话恢复核验，AD未自行调用日用端口，不能当成adaptive已部署或已真机验收。
AI独立评估连续性/取消/当前声线门；AD保持buffered默认，未自动放行adaptive、
未接TRT/vLLM或扩大实验。任务→实现fee1d86→基准fb9deec→门修复172a355→本窗口
实际测量与清理的证据链在此保留，结果摘要提交交主会话整合。

### 窗口关闭后的CPU基本音频筛查与可控范围

按主会话要求，只读上述冻结WAV/JSON做CPU筛查，没有GPU、ASR、模型、网络或服务
调用。一次性可重跑分析源保留于同一忽略目录 `cpu_quality_audit.py`，SHA256
`586689935bd53bf7e82ba85af780cf2dc34f206f7d43a543f278701b68940ac4`，原始结果不覆盖。
下列工程筛查阈值不作为语音质量研究标准，也不能代替审听。

- 6/6同seed配对原生样本数和时长完全相同；24文件采样/字节/解码帧数门均通过。
  时长±20%、绝对削波≤1%且削波增量≤1个百分点、非空RMS≥.0015且峰值≥.015、
  分段结构和供给缺口不退化等基本门全部通过。实际原生削波为0，adaptive解码
  近满幅样本比例最大0.0006401%（幅值≥32760），buffered解码为0。
- 原生RMS：buffered .07407–.08882，adaptive .07825–.09049；配对比值
  .98409–1.07743。两模式原生前导低能量均为240–560ms（20ms窗RMS<200 PCM16），
  配对差为0或-20ms、尾部差均0，最长内部低能量均520ms、每对差0。
  音频内的前导/标点静音与供给欠载分开统计；“能量帧可用”不能代替扬声器
  经过这些音频样本后才真正出声的时刻。
- 42个原生模型块/自然段连接处最大单样本跳变为.072784归一化幅度；该处前/后
  5ms RMS为.18194/.17133，附近最大单样本变化为.22119。所有连接处跳变均不高于
  各自邻域最大变化（比值最大.95455），未见孤立的数值大脉冲；不据此宣称无可闻接缝。
- 实际输入分段字符轨迹为多句[10,22]、长句[11,30,19]，与固定源码离线纯文本分段
  一致，服务请求数对应，源文本离线拼接保持原样。未发现原生有声整段或60ms块
  的逐字节完全重复，正常PCM没有多收/少收样本。这些结构/字节证据不能识别
  同长度文本错播、模型语义重复或漏读字词；semantic_word_completeness_verified=false。
- 三次取消后新增旧帧均0，新轮52/58/57帧全部成功解码，首能量达标帧可用，
  guard活动请求0、读线程退出、同编码器可复用。第三种取消仍只有“交付三帧后”
  证据，没有有效回答声音已经发出或设备残音的证据；不改写该实际缺项。

AD意见供AI独立判断：连续供给、CPU基本音频门与软件取消清理支持继续作为显式
adaptive候选组合/有界人工验收；目前不建议改日用全局默认。原因是生成完成/RTF
成本上升、实际声线身份与owner听验需对齐、有效声后取消及设备体验尚未通过。
后续任何补测须另按主会话的新目标/窗口安排；本收据已经关闭，不能复用。
