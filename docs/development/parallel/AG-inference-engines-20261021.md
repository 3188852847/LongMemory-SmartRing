# AG：隔离推理引擎适配与基准

2026-10-21。基线 main `a93258e903954525b88b7af79756aaffe2bd50d6`；分支 `codex/ag-inference-engines-20261021`。本次侧栏会话 ID 由主会话归档时登记。

## 范围与实际文件

只新增 [能力检查](../../../scripts/development/cosyvoice/acceleration/capabilities.py)、[适配器](../../../scripts/development/cosyvoice/acceleration/adapters.py)、[PCM 基准](../../../scripts/development/cosyvoice/acceleration/benchmark.py)、包入口、[专属测试](../../../tests/unit/development/test_cosyvoice_acceleration.py)、本记录及 [ADR-0200](../../adr/0200-isolated-inference-engine-candidates.md)。没有修改 AD 的 service/cosyvoice_streaming/voice_latency 或公共接线，也没有改锁文件。公共文档清单条目由主会话统一接力。

完成标准：固定源码核查、一手官方支持矩阵、可运行的隔离适配与 benchmark、CPU/mock 验证、准确资源阻塞与 owner 下载需求。生产加速、GPU 编译、真实学校调用、个人库/设备/日用服务操作不在已完成范围。主会话本轮明确暂不给 GPU 独占租约。

## 只读现场核查

| 项目 | 本轮实际读数与边界 |
|---|---|
| 工作树 | 分配 AG 树，启动分支匹配且无未知改动；新模块导入来源经真实子进程核对在 AG 树 |
| OS/GPU | Windows11，build26200；RTX4080，显存16376MiB，驱动610.88；首次快照 used7703MiB/free8346MiB，瞬时值不代表可并行占用 |
| WSL | Ubuntu-26.04 与 docker-desktop 均 Running、WSL2；只读列举，没有进入容器或启动新 GPU 进程 |
| Cosy Python | 实际3.10.20；仅 importlib.metadata 查询：torch2.3.1+cu121、transformers4.51.3、onnxruntime1.18.0；无 TensorRT/vLLM/Triton/ORT-GPU |
| 主 Python | 实际3.12.13；torch2.8.0+cpu、transformers4.57.6、pytest9.1.1，用作隔离测试工具；未安装依赖 |
| Cosy 源码 | 实际 HEAD `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`，Git工作区干净；6个参与适配的源码 LF 规范化 SHA256 全部匹配 capabilities.py 常量 |
| 模型资源 | 已有 Fun-CosyVoice3-0.5B；没有 flow.decoder.estimator.fp32.onnx 或 mygpu.plan；不读私人音频/档案 |
| 现有优化 | service 磁盘构造为 fp16=True；runtime_optimizations 为固定 Transformers4.51.3 hidden-head bypass；本次保留，未查日用 HTTP 或声称重新验收当前进程 |

读到的机器历史清单驱动为610.74；本轮直接 nvidia-smi 为610.88，按此次读数登记，不改写历史清单，也未升级驱动。没有运行 torch.cuda.is_available、模型加载、compile 或 GPU benchmark。

## 适用性矩阵

| 方向 | 固定源的真实能力 | 当前条件 / 本轮实现 | 流式与取消边界 |
|---|---|---|---|
| 当前 torch fp16＋hidden-only | 原生 CV3 LLM/flow/HiFT，现有本项目优化 | 保留对照；无新增依赖 | 原模型支持音频/生成器文字；现有 stream_runtime 负责协作取消，不能据此声称 GPU 瞬停 |
| 原生 `load_trt` | 仅替换 flow.decoder.estimator，CV3 构造器有入口；fp16 DiT 有性能警告 | 新适配器加载现成 fp32 plan；验证源/摘要/GPU/TRT版本/I/O名字顺序/类型形状；构造失败不删原值。缺 TensorRT10.13.3.9 与 ONNX/plan | 本适配器仅独立 fp32 buffered 模型；拒绝 fp16 指针与未验证 streaming mask。HTTP 仍可由消费方切完成音频 |
| 原生 vLLM | 固定 README 支持0.9.0及0.11.x；选精确0.11.0；注册类仍名 CosyVoice2ForCausalLM，官方 CV3 示例沿用 | 新 factory 检查 Linux、0.11.0/4.57.1/torch2.8.0及实验模型路径；拒绝缺文件/既有无身份导出；不复制权重。当前 Windows 原环境不适用 | 原生音频流可候选；文字生成器明确不支持；上游导出和删层不可热撤回，失败丢弃隔离进程，abort 另验 |
| Triton＋TensorRT-LLM | 固定源码有 CV3 专用 README/run_cosyvoice3.sh，不是 CV2 宣传 | 独立 Linux 容器、模型转换和多阶段服务。官方源码基底 NGC25.06；贡献镜像 soar97 并非 NVIDIA 官方发行镜像；全部镜像/权重摘要尚未锁定，不提供直接运行上游部署脚本 | 需另验取消、gRPC、角色/声线/档案契约；不能直接接 AD HTTP 协议。公开 L20 四并发结果不套本机 |
| torch.compile | 2.3 支持局部编译；固定2.3.1源码拒绝 Windows Inductor | 新可撤回 estimator.forward 候选，Linux独占窗口才可试；dynamic=True，记录冷/热及重编译；不改LLM | 编译异常丢弃整次输出后新请求回退，不拼接音频；保留现有取消路径 |
| CUDA Graph | 固定源码没有完整TTS capture；PyTorch要求稳定形状/地址与捕获边界 | 能力检查明确 blocked。KV cache、流长和并发变化尚无静态 bucket（固定长度分组）契约，不伪造开关 | 整段TTS捕获、取消、重放缓存均未验 |
| TTS INT8/INT4/FP8 | 固定 source 未提供已验证量化checkpoint/校准流程 | 明确 blocked，不把 Qwen 通用支持写成 CV3 验收；需固定语音模型工件与音质/采样验证 | 不能用仅文本精度判断声质 |
| BGE CPU INT8 | 现有torch2.8动态Linear权重量化API | 新 out-of-place Bert 候选与合成评分 Recall@k/首位门；真实模型不加载，索引不写 | CPU任务归调用方；最终记忆检索/问答一致性另验 |
| 批处理/并发 | TRTLLM离线LLM batch 与token2wav batch不同，吞吐不能代表首答 | harness 支持1/2/4有界并发、同engine一组、引擎组交替；不并行加载不同GPU引擎、不等待日用请求凑批 | 必须同时看供给间隙、取消和首答；线程并发不等于原生算子batch |
| 学校远程LLM | 服务器不受本机控制 | 能力行固定 blocked: remote_school_server_not_owned | 本机vLLM/TensorRT无法为学校API开开关；AF仅观测网络/缓存 |

上述版本依据：[固定 requirements](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/requirements.txt)、[固定 vLLM 说明](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/README.md)、[vLLM0.11.0 CUDA依赖](https://github.com/vllm-project/vllm/blob/v0.11.0/requirements/cuda.txt)、[平台要求](https://docs.vllm.ai/en/v0.11.0/getting_started/installation/gpu.html)、[TensorRT-LLM Linux要求](https://nvidia.github.io/TensorRT-LLM/1.0.0/reference/support-matrix.html)。TensorRT SDK11.2.1.2 的机器级历史验收不证明 Cosy Python 中已安装10.13.3.9绑定，也不授权混用两版DLL。

## 给主会话/AD 的接口

`probe(source, model, include_gpu=False)` 返回只读报告；engine 行字段：`engine/source_commit/platform/model_capability/audio_streaming/text_streaming/cancellation/status/reasons`。`status` 只有 blocked 或 needs_isolated_validation，没有 production_ready；不要把它映射为本实例已加速。`audio_streaming` 指模型能力，`protocol_streaming` 可另外注明完整音频的传输分块。

适配 API 为 `install_flow_trt`、`install_flow_compile`、`create_native_vllm`、`bge_cpu_int8_candidate`。GPU入口必须提供 `ExperimentContext(isolated_instance=True, window_id=主会话调度收据)`；它不自行获取租约，调用方仍需保证独立进程、无活跃请求与服务所有权。TRT manifest 字段为 `source_commit/plan_sha256/tensorrt_version/gpu_name/precision`；plan摘要在实际生成后计算，当前没有虚构值。`Adapter.applied` 仅表示候选安装成功，仍未通过质量门。

`Adapter.restore()` 只撤回自己的实例改写，未知后装适配不覆盖。TRT 保留基线权重，因此峰值显存可能增加；未测之前不能以理论节省显存安排并发。vLLM factory 是新隔离进程路径，不承诺 restore。局部编译运行异常抛 `CandidateExecutionError`，由实验调用方丢弃本响应、恢复后从新请求跑基线。

`runner(case_id, seed, cancel_event) -> Iterator[AudioChunk(samples=tuple[float,...], sample_rate=int)]`，samples是已转CPU的归一化单声道PCM。GPU/全局随机数种子不允许由多个线程同时重置，真实并发runner需请求独立随机源/串行确定性实验，不能据本轮CPU替身推断GPU可重复。`measure` 返回首次PCM、首次≥5ms能量达标块、总耗时、RTF、供给中断次数/最长间隙、cancel_close_ms。静音或脉冲不算声音；能量达标也不证明它是正确最终答案。runner负责真实原生取消，harness只证明取消事件与迭代器close。

`paired_benchmark` 在同输入/种子下轮流运行engine，另做并发1/2/4；基准方需先独立warmup并另记冷启动，不能把demo里的快时间报告为模型速度。能量/摘要分析放在每次生成计时之后；group_wall_ms另含分析开销并显式标记，不能当纯推理吞吐。`audio_gate` 自动筛查时长±20%、削波增量≤1%、连续性无退化并保留人工声质/取消门；这组工程筛查阈值不是语音质量研究结论。`ranking_gate` 接收同合成库的分数及相关文档标签，要求Recall@k不降且首位一致；真实样本及最终问答另验。任何候选选择前还要比较用户说完到设备有效回答声音，并排除等待提示和推理内容。

## 可重跑命令与本轮真实验证

从 AG 工作树执行，使用已存在解释器，不安装。只读能力检查可直接用 Cosy Python运行绝对脚本路径：

```powershell
& 'D:/03-项目/01-正式项目/智慧圆屏/local/runtime/CosyVoice/.venv/Scripts/python.exe' -I -B scripts/development/cosyvoice/acceleration/capabilities.py --source 'D:/03-项目/01-正式项目/智慧圆屏/local/runtime/CosyVoice' --model 'D:/03-项目/01-正式项目/智慧圆屏/local/runtime/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B'
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -B -m scripts.development.cosyvoice.acceleration.benchmark --demo --concurrency 2
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -B -m pytest tests/unit/development/test_cosyvoice_acceleration.py tests/unit/development/test_cosyvoice_runtime_optimizations.py tests/unit/development/test_cosyvoice_stream_runtime.py -q
```

| 验证 | 实际结果 |
|---|---|
| 专属第一轮 | 29 passed；随后增加fp16指针/streaming保护 |
| 专属＋hidden-only＋stream_runtime组合 | 51 passed，4.32秒；无skip；全部CPU/mock，含真实CPU Linear量化与原权重保持 |
| 能力检查 | 实际Cosy3.10.20执行AG脚本，6源码指纹true、包版本如上、ONNX/plan缺失，未导入torch或初始化CUDA |
| CPU demo | 并发2，两case×两seed×两engine×两并发共16records；evidence_kind=cpu_mock_only；GPU与device_first_answer标记false |
| 最终组合（含文档机制） | 65 passed，3.97秒；与51项相同三组加既有test_doc_maintenance；无skip |
| Python3.10兼容 | 实际Cosy3.10.20解释器对4个新增模块进行3.10 AST语法解析通过；不冒作GPU执行 |
| 文档检查 | 默认公共清单报2个unlisted-document/2个unknown-selection；尚未接力登记。内存中为两文档添加draft/reference条目后，同一audit检查2文档、0 findings；未改公共清单。曾尝试experiments中的临时manifest，检查器按公开目录边界拒绝，随后改用内存清单 |
| 真实GPU/听感/圆屏/学校 | 未运行；没有速度收益、音质、取消时限或日用切换结论 |

## 所有者资源获取：精确工件与边界

当前无需下载即可使用能力检查、CPU量化替身和mock基准。主会话尚未发GPU租约，故本轮不执行任何安装、模型下载、git fetch/clone、WSL/Docker变更。以下只供所有者取得固定工件，**不是安装或部署命令**；将目标目录换成自己的新增实验资源目录，禁止写日用Cosy `.venv`。有同名文件即拒绝覆盖。

官方 PyPI 元数据提供的精确工件：

| 工件 | SHA256 | 官方元数据 |
|---|---|---|
| vllm-0.11.0-cp38-abi3-manylinux1_x86_64.whl | `3861c75ff2b12e24f6d179ff5c084d791b42ded8675d76c8706697c79f68cd62` | [PyPI0.11.0](https://pypi.org/pypi/vllm/0.11.0/json) |
| tensorrt_cu12_bindings-10.13.3.9-cp310-none-manylinux_2_28_x86_64.whl | `3ca2635394789dd62346ff5ee3f02def53cee2cd21247cc342461dc721893a1e` | [NVIDIA PyPI10.13.3.9](https://pypi.org/pypi/tensorrt-cu12-bindings/10.13.3.9/json) |

```powershell
$artifactDir = 'D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ag-inference-engines-20261021/experiments/runs/ag-owner-artifacts-20261021'
New-Item -ItemType Directory -Path $artifactDir -ErrorAction Stop | Out-Null
$artifacts = @(
  @{Name='vllm-0.11.0-cp38-abi3-manylinux1_x86_64.whl'; Url='https://files.pythonhosted.org/packages/47/33/d19e0763c34392ec956534536fa837c060495bfff31ed83452135ea7608d/vllm-0.11.0-cp38-abi3-manylinux1_x86_64.whl'; Hash='3861c75ff2b12e24f6d179ff5c084d791b42ded8675d76c8706697c79f68cd62'},
  @{Name='tensorrt_cu12_bindings-10.13.3.9-cp310-none-manylinux_2_28_x86_64.whl'; Url='https://files.pythonhosted.org/packages/03/b4/768d8e1d4cd949422ede434397d5f68b2281a2a269602257ab2922674f36/tensorrt_cu12_bindings-10.13.3.9-cp310-none-manylinux_2_28_x86_64.whl'; Hash='3ca2635394789dd62346ff5ee3f02def53cee2cd21247cc342461dc721893a1e'}
)
foreach ($item in $artifacts) {
  $targetFile = Join-Path $artifactDir $item.Name
  if (Test-Path -LiteralPath $targetFile) { throw "拒绝覆盖 $targetFile" }
  Invoke-WebRequest -Uri $item.Url -OutFile $targetFile
  if ((Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.Hash) { throw "工件摘要不符：$targetFile；保留现场，勿安装" }
}
```

两文件都是Linux候选，不能装入Windows日用环境，也不组成完整运行时。vLLM还需独立Linux Python3.10、torch/torchaudio2.8.0、transformers4.57.1与固定Cosy依赖重解锁；原uv.lock不动。TensorRT绑定还需同版实际runtime库，不能把PyPI几十KB包装sdist或703字节libs占位sdist当完整库；不能混用机器11.2.1.2。完整运行时wheel/NGC镜像digest与全部传递依赖未锁定前不建议执行安装。无需新Cosy模型即可规划本地导出，但实际导出/构建仍需GPU独占窗口并写实验副本，生成后记录plan哈希与GPU/TRT身份。

TRT-LLM专用路径另需转换LLM与FP16-ONNX资源；固定脚本引用贡献者yuekai仓库且未pin revision，官方模型与贡献转换工件须分别登记。当前不使用其Stage0自动下载、不直接运行其clone/升级依赖的Compose。下一接力应先在新隔离Linux环境形成完整锁和镜像digest，后由所有者获取；不能向Windows原环境建议一个 `pip install vllm` 解决。

## 提交与接力

本分支仅提交上述自有文件，不merge main、不push。主会话接力：审查精确提交，将ADR/本记录加入公共清单；把能力字段交AD，不默认启用候选；如继续真实加速，先协调独占GPU与完整离线资源，再做同输入/声线/种子的冷/热及并发对照和owner听验。现有buffered、角色/声音与学校免费模型保持原设置。
