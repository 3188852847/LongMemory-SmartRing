# AD：正式三模式窗口预检交接

日期：2026-10-21。驱动基线 `ecf23d5a35f874a3f8e0e7e63dfaa86410462c1a`，
分支 `codex/ad-three-mode-driver-20261021`。本轮只新增本记录；AI 审查/启动器文件不改。
只读本地源码/包元数据/文件属性，并做 CPU Opus 合成帧预检；没有连接日用服务、启动 GPU 模型、下载或安装。

## 新发现：能量门需在正式窗口前修正

[驱动 EnergyGate](../../../scripts/development/cosyvoice/benchmark_ad_three_modes.py) 当前要求
连续120个24kHz样本绝对值均≥200，即逐样本连续5ms。正常周期波形会过零，不能据此判断没有有效能量。
本轮现装 CPU Opus 的可复现反例为400Hz、幅度5000、60ms、24kHz单声道PCM16正弦：

| 观测 | 实际值 |
|---|---:|
| 输入/解码样本数 | 1440/1440 |
| 编解码帧数 | 1 |
| 解码峰值 | 5289 |
| 解码整帧 RMS（均方根） | 3275.768 |
| 解码后绝对值≥200的样本 | 1259 |
| 最长逐点连续达标样本 | 90，低于当前120门槛 |
| 当前 EnergyGate | false |
| 存在连续5ms窗口 RMS≥200 | true |

无torch导入、无网络、无音频文件输出。前轮44项通过不能排除该问题：原合成传输测试主要使用常量PCM，
未覆盖正常过零波形。若保持当前门限，非静音短句可能被误报为 silent 或达不到取消触发。
不为凑齐案例换文本/重复推理，也不能把这种失败归因于模型慢或 Opus 损坏。

**最小修复交 AI**：将5ms定义改为连续120样本窗口的 RMS≥200，跨解码帧保留窗口，
窗口未满不能宣告达标；按整数平方和比较 `sum(sample²) >= 120 * 200²`，避免逐样本必须不经过零。
增加正弦、静音和跨帧凑满窗口测试，并同步能量代理说明。仍仅为声学代理，不证明听见首字或语义。
按 ROOT 分工，本会话不修改 AI 正在审查的驱动/测试。正式窗口使用审后修复版本。

精确CPU复跑命令如下；从W工作树执行，不创建文件，不打开HTTP端口：

```powershell
Set-Location -LiteralPath 'D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ad-cosy-continuity-20261021'
@'
import importlib.util, json, math, struct, sys
from pathlib import Path
path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('ad_energy_cpu_counterexample', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
_, encoder, decoder_factory, dll = m.load_cpu(Path(sys.argv[2]))
try:
    values = [round(5000 * math.sin(2 * math.pi * 400 * i / 24000)) for i in range(1440)]
    packets = []
    encoder.encode_pcm_to_opus_stream(struct.pack('<1440h', *values), end_of_stream=True, callback=packets.append)
    decoded = decoder_factory().decode(packets[0], 1440)
    out = struct.unpack('<1440h', decoded)
    longest = current = 0
    for value in out:
        current = current + 1 if abs(value) >= 200 else 0
        longest = max(longest, current)
    window_squares = [sum(v*v for v in out[i:i+120]) for i in range(len(out)-119)]
    print(json.dumps(dict(frames=len(packets), decoded_samples=len(out), peak=max(map(abs, out)),
        rms=round(math.sqrt(sum(v*v for v in out)/len(out)), 3),
        samples_abs_ge200=sum(abs(v)>=200 for v in out), longest_pointwise_run=longest,
        current_gate=m.EnergyGate().feed(decoded), window_rms_gate=max(window_squares)>=120*200**2,
        torch_imported='torch' in sys.modules, audio_files_written=False)))
finally:
    encoder.reset_state()
    encoder.close()
    dll.close()
'@ | & 'D:/03-项目/01-正式项目/智慧圆屏/local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/.venv/Scripts/python.exe' -I -B -X utf8 - 'D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ad-cosy-continuity-20261021/scripts/development/cosyvoice/benchmark_ad_three_modes.py' 'D:/03-项目/01-正式项目/智慧圆屏/local/runtime/xiaozhi-esp32-server/main/xiaozhi-server'
```

审后门限的建议边界（由AI固定规则并记录，AD本轮不偷偷替换算法）：

- 120样本窗口未满时无结论，跨帧保留；恰好120个幅度200常量应达RMS门，199不应达标；静音不达标。
- 正弦等正常过零波形不能因过零被否定；上表400Hz真实Opus解码应达标。
- **仅RMS不够排单点尖峰**：一个32767样本加119个零，其窗口RMS约2991，仍远高于200。
  若语义是“持续有能量”，建议另要求同120样本窗内至少60个（半窗）样本绝对值≥200，
  允许正常过零但拒绝单点/极少点尖峰；这属于待AI定稿的代理规则，不是已验证的语音质量阈值。
  至少覆盖单个大尖峰、尖峰跨帧边界、静音、窗口凑满与reset后不带入旧轮等测试。

## 精确调用账本与取消/复用

T0=`下午的阳光落在窗边。`；T1=`我们可以先整理桌面，再慢慢安排接下来的事情。`。
每条作为完整TTS请求，cache=false，不经过自然分段/LLM/记忆，不注入草稿voice_profile。

| 顺序 | 文本 | 模式 |
|---|---|---|
| 启动热身1 | `你好，我准备好了。` | 构造器 `_generate`：默认参考、默认非增量 |
| 启动热身2 | 同上 | `prepare_selected_voice`：显式主项目档案，finally适配成功时增量，use_cache=false |
| 测量1～3 | T0 | buffered → incremental → adaptive |
| 测量4～6 | T1 | buffered → incremental → adaptive |
| 测量7～9 | T0 | adaptive → incremental → buffered |
| 测量10～12 | T1 | adaptive → incremental → buffered |
| 取消1 | T1 | adaptive，首个达标能量帧后观察仍在途，再关闭自有连接 |
| 复用1 | T0 | adaptive，同一个CPU编码器重置后复用，先确认服务清理归零 |

当前标准构造器含默认热身1；档案存在且启用选中热身时再有热身2。
AI启动器不得在构造后再重复 prepare_selected_voice，也不得偷偷加模型试跑。
选中热身缺失/失败时停止，不拿默认热身替代。按此标准路径准确为2+12+1+1=16次合成入口调用，
内部文本拆段/token步骤不另冒充HTTP调用。收据记录实际热身2次；≤15秒限制分别按两次实际热身耗时核对。

取消须观测 generation_in_flight=true 且 stream_runtime.active_requests>0。
若首帧播放时模型已经生成完，当前实现停止并报 no_cancel_proof；不补跑/换长句、不宣称真实取消通过。
若取消清理未归零、线程未退出或下一次复用失败，保留失败和此前12次记录，停止后续调用。
12次完整测量可作为已取得观测，整个矩阵仍不完整，不能排除失败案例后自动批准日用切换。

## 主项目当前声线应如何核对

服务应由AI受控启动器构造，显式 `profile_root=主项目`，不能在隔离树依赖默认ROOT。
service CLI没有profile-root参数；v2请求自己设置model_streaming，不需为了本矩阵打开全局模型流式。

ROOT/启动器在获准窗口内从主项目 VoiceProfileStore 取得预期 config_digest（profile()[1]）和
context_digest（model_context()[2]，包含参考音频摘要/风格等），与新18774实例
`capabilities.audio_stream.profile_identity` 的同名字段比较。该实例的 state应为valid，
profile_identity.selected_voice_warm 和顶层 selected_voice_warm 均为true。
随后每次检查身份不变、incremental_usable=true、force_buffered=false、stream_runtime.applied=true、
runtime.fp16/hidden_only=true，并校验当前 service_sha256。
前后/取消后应 generation_in_flight=false、active_requests=0。

**当前驱动只比较新实例前后身份，尚不独立证明它等于主项目所选声线**；这一步由AI启动器显式预期值比较补足。
不需要新增HTTP字段，也不应把真实摘要/档案/参考WAV复制进公开报告。
本轮未读取主项目声线档案/音频或请求日用健康接口，故没有伪报“已核对当前声线匹配”。

## 300秒预算的真实边界

驱动不加载模型或启动服务；它从收据 started_at_utc 算已用时间，剩余额度为
`min(300 - age, expiry - now)`，因此**只有收据起点在模型加载前**，才会把加载/热身时间扣账。
父子CPU客户端在开始时再次核对剩余额度；operation含前后健康/取消清理上限15秒，不重试。
但驱动在服务就绪之前根本没有运行，不能硬中止挂住的模型加载/热身，也不能验证填写起点是否真实。

**AI启动器需补的最小整窗保证**：加载前启动独立单调时钟与父进程监管，拥有其唯一隔离模型进程，
同一300秒预算覆盖加载、两次热身、资源检查及14次请求；将同一起点传收据，绝不在ready后重新起算。
热身15秒上限也需由启动器监管，不能只在事后读取health耗时。
驱动CPU子进程退出不代表GPU kernel已停止；整窗失败由AI启动器/ROOT确认自有隔离服务和GPU清理，
ROOT核对日用所有权/检查点后恢复，AD不自行停日用或恢复服务。
自有CPU Job（进程所有权容器）退出确认最多另有4秒宽限，不在截止后新增合成调用。
在AI补齐之前不能称当前驱动单独提供“从加载前起300秒硬保证”。

## 本机资源核对结果（只读/CPU）

路径基准P=`D:/03-项目/01-正式项目/智慧圆屏`，C=`P/local/runtime/CosyVoice`，
X=`P/local/runtime/xiaozhi-esp32-server/main/xiaozhi-server`，W=`P/local/worktrees/ad-cosy-continuity-20261021`。

| 资源 | 实际路径/元数据 |
|---|---|
| 主解释器 | `P/.venv/Scripts/python.exe`，3.12.13 |
| 模型服务解释器 | `C/.venv/Scripts/python.exe`，3.10.20 |
| CPU Opus客户端解释器 | `X/.venv/Scripts/python.exe`，3.10.20 |
| CosyVoice源码 | C，HEAD `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`，受跟踪文件干净 |
| 小智源码 | `P/local/runtime/xiaozhi-esp32-server`，HEAD `eb4b28c59ed7ed885258498cf757ce14352d620e`，受跟踪文件干净 |
| 模型 | `C/pretrained_models/Fun-CosyVoice3-0.5B`，必需yaml/llm.pt/flow.pt/hift.pt/campplus.onnx/speech_tokenizer_v3.onnx及CosyVoice-BlankEN目录均存在 |
| 模型yaml | 6934字节，SHA256 `f5a6b2c6f05139d0f18861a1fe506f751e787026b77c05f7e8fef9f8a4405965` |
| 模型环境包元数据 | torch/torchaudio `2.3.1+cu121`，transformers `4.51.3`，numpy `1.26.4`，soundfile `0.12.1`，onnxruntime `1.18.0`，未发现onnxruntime-gpu发行包 |
| CUDA运行库位置 | `C/.venv/Lib/site-packages/torch/lib`；cudart64_12、cublas64_12、cublasLt64_12及cuDNN8 DLL存在，torch/version.py标记CUDA12.1 |
| CPU Opus包 | `X/.venv/Lib/site-packages/opuslib_next`，发行包1.1.5；numpy1.26.4 |
| 实际已加载CPU DLL | `X/native/libopus-1.6.1/Library/bin/opus.dll`，474624字节；GetModuleFileNameW核实该路径，版本字符串`libopus 1.6.1` |
| WeText离线资源 | `P/local/runtime/modelscope-cache/hub/pengzhendong/wetext`，中/英文tn/tagger.fst、verbalizer.fst四文件均在位 |

只核对模型文件属性/yaml摘要，不散列或加载整套权重。CUDA信息是发行元数据与DLL存在性，
不是当前驱动、CUDA加载/计算或GPU空闲证明；本矩阵不编译，无需改全局CUDA SDK或调用nvcc。
CPU实测1440个合成样本经一个Opus帧解码仍为1440样本，来源为W下当前consumer；
反例能量结果如上。所有探针确认torch未导入，无原音频/声线文件输出。

## 可复跑入口与失败收尾交接

工作目录固定W，审后干净HEAD须与新收据 candidate_commit 一致；下列入口沿用现有命令，
AI启动器完成后以其新整窗入口为最终真实启动入口，不手工先起模型再补收据。

```powershell
Set-Location -LiteralPath 'D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ad-cosy-continuity-20261021'
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -B -X utf8 scripts/development/cosyvoice/benchmark_ad_three_modes.py --plan
# 仅由审后AI启动器/ROOT把下列消费端调用置于同一新资源窗，当前未执行：
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -B -X utf8 scripts/development/cosyvoice/benchmark_ad_three_modes.py --run --receipt '<新窗口收据绝对路径>' --production-root 'D:/03-项目/01-正式项目/智慧圆屏' --output 'experiments/results/ad-three-modes-<唯一窗口ID>'
```

输出只摘要；新目录拒绝覆盖。失败不复用关闭窗口，保留summary.jsonl与退出/资源状态，
先确认自有CPU线程/进程树退出，再由AI/ROOT查隔离服务、监听、GPU与声线身份，未清理不恢复日用。
ROOT协调唯一新GPU窗口后，AD执行审后当前声线矩阵，将完整/失败证据交AI复核，不自行切换共享服务。

本轮默认计划输出核对为12测量+取消/复用、最多16合成调用；未重跑44/218/171回归。
当前明确前置为AI修复能量门、整窗监管及主项目身份显式比较；未发现缺失模型必需文件或CPU Opus ABI故障。
本记录链接目标存在；严格文档检查退出1，新增文件未登记，unknown-selection，实际检查0份，
另有本记录及前轮driver记录的unlisted-document警告；未宣称通过，共享manifest留主会话整合。
