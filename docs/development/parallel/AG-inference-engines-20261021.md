# AG：隔离推理引擎适配与基准

2026-10-21。基线 main `a93258e903954525b88b7af79756aaffe2bd50d6`；分支 `codex/ag-inference-engines-20261021`。本次侧栏会话 ID 由主会话归档时登记。

## 范围与实际文件

首阶段新增 [能力检查](../../../scripts/development/cosyvoice/acceleration/capabilities.py)、[适配器](../../../scripts/development/cosyvoice/acceleration/adapters.py)、[PCM 基准](../../../scripts/development/cosyvoice/acceleration/benchmark.py)、包入口、[专属测试](../../../tests/unit/development/test_cosyvoice_acceleration.py)、本记录及 [ADR-0200](../../adr/0200-isolated-inference-engine-candidates.md)。第二阶段新增BGE配对、SDK11静态核查与Cosy runner，详见后文。没有修改 AD 的 service/cosyvoice_streaming/voice_latency 或公共接线，也没有改锁文件。公共文档清单条目由主会话统一接力。

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

## 第一阶段适用性矩阵（第二阶段变化见后）

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

## 第一阶段可重跑命令与真实验证

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

## 第二阶段资源优先级：先用已有资源

主会话要求收窄后，撤回首阶段两只Linux wheel下载命令；它们缺runtime/完整锁，不能作为用户下一步。旧命令仅留在首阶段提交e6e8db5的历史中，本记录不再提供半套下载。当前无新增下载/安装需求。

| 优先级 | 现在推进 | 资源/结论 |
|---|---|---|
| P0 | AD同模型adaptive（自适应缓冲）、AC CPU话轮 | 主会话近期优先；不把BGE数毫秒局部收益宣传成聊天首答收益 |
| P1 | 既有BGE CPU INT8一次性真实配对 | 已在AG-CPU-BGE-20261021-01完成，结果见下；不切日用/不改个人索引 |
| P2 | 既有Windows TensorRT11.2.1.2独立候选 | SDK、CP310绑定wheel、CUDA13.3 DLL已在本机；静态兼容检查可做，GPU导出/构建待新调度；不先安装旧10.13或混用DLL |
| P3 | Linux vLLM/TRTLLM完整环境 | 暂缓获取。完整传递依赖锁、镜像digest/平台/体积及恢复边界尚未齐全；不发下载或部署命令 |

P3重新进入执行前需交完整可复现环境：Linux/Python/torch/CUDA/TRT/vLLM/transformers及Cosy固定源的相容锁、所有工件哈希、NGC镜像manifest digest及拉取/展开体积、模型revision和转换资源指纹、隔离目录/端口/显存/进程所有权与回退步骤。没有这些证据时保持needs_isolated_validation，不能把两个顶层版本当全锁。

## 第二阶段：真实BGE CPU配对

新增 [BGE实验](../../../scripts/development/cosyvoice/acceleration/bge_benchmark.py)，默认只读safetensors头与配置，不加载torch/模型；--execute必须提供主会话CPU调度收据。现有BGE固定revision为7999e1d3359715c523056ef9478215996d62a620，真实payload91.381MiB、Linear权重49MiB，估算INT8权重54.631MiB；估算不含框架与激活，不把文件大小当进程峰值。

主会话发放一次性AG-CPU-BGE-20261021-01后，只运行一次：12条明确合成文档、4查询、FP32/INT8交替3次、batch8、512窗口/超长与空输入。实际前向19+19=38次。torch线程2、interop1；模型加载前通过Windows Job Object设置2048MiB单进程提交内存限制、两逻辑CPU亲和性和关闭Job即结束自有子进程，Assign成功后才创建start gate放行加载。180秒父看门狗；子进程禁止socket连接/DNS/UDP及HF在线访问，CUDA_VISIBLE_DEVICES为空、模型明确to(cpu)，导入来源为AG树LocalBGEEncoder，快照沿既有hash校验；权重/服务/索引不写。

| 实际指标 | 本次结果 |
|---|---|
| 一次矩阵总墙钟 | 4.928秒；加载约2245.486ms、量化112.083ms；没有重试 |
| batch1查询中位数 | FP32 13.416ms / INT8 9.133ms；比值1.469，仅这4查询×3次 |
| batch8文档中位数 | FP32 57.043ms / INT8 32.625ms；比值1.748，仅3次，不报P95 |
| 合成旧FP32文档＋INT8查询 | Recall@3 1.0→1.0、首位一致率1.0 |
| 合成INT8文档＋INT8查询 | Recall@3 1.0→1.0、首位一致率1.0 |
| recipe与边界 | 512维、CLS pooling、L2归一化、512token有限输出、513token拒绝、空输入拒绝；两候选均通过 |
| 退出/恢复 | exit0，stop_reason=null，原模型实例恢复；Job关闭、资源归还；没有GPU或真实学校调用 |

内存测量限制必须保留：该次receipt的peak_private_mib约0.84MiB是Windows虚拟环境入口包装进程采样，**不是实际模型worker峰值**。用无模型PID探针已复现Popen.pid与解释器os.getpid不同；原Job单进程2048MiB限制继承到实际worker，但不能据此给出实测峰值。原收据原样保留，追加stage2-annotations说明，未为补峰值重跑BGE。后续harness已改为查询整个Job的PeakJobMemoryUsed，并同时限制聚合Job提交内存2048MiB；用轻量无模型子进程验证实际Job限制查询及继承，未产生第二次BGE测量。

量化是独立recipe/身份。适配器输出quantization recipe；报告未来显式分baseline_identity/candidate_identity/candidate_metadata，本次旧报告model_identity只表示FP32基线，旁注按相同量化调用补足候选配方指纹，不假装当时原报告已发出：

- 基线身份：43435848b0ebf50613b0090a38953e56754b11962a79000f096121f0b15b297b。
- 候选身份：ce4912d9f13ee93b6459e08e1d6158bff4861db08f532e31a1f4c0ed33285d8e。
- 不沿用原provider_identity写索引，不把本次小合成集通过推广为真实记忆问答或日用切换结论。未来生产需独立旧索引query/新索引配对质量与身份迁移验收；当前不授权个人重建。

原始输出保留于本树忽略目录experiments/runs/ag-bge-ab142f4539d342f8af47c41189374adc/，不提交原产物。report.json SHA256=7651e23a8857225dc33e2777a4a3938cb5d6632e6aceaac2f9938f6d471c28f2；receipt.json=27831434330e75c00010553121b92c84171d21a57959cbec2bf6b5e1b06322bd；stage2-annotations.json=37c0af1f6205ce023e9a50d82432498114e1b6fa839be66b906274c87d0e1e14。报告内包含实际运行时harness/adapter及本树encoder源码摘要；随后只修资源统计/身份标识，不改这次原始字节或重跑模型。

实际运行版本的harness-at-run.py/adapter-at-run.py/encoder-at-run.py已逐字节归档到同一忽略目录，摘要与原report记录全部匹配；harness为33e958794af3325061308d4906ed0bd41a10496452422fd7ae7513ec502645ed。后续只读重算模型6文件摘要与加载前receipt一致，model-protection.json=28bd20d351f4c3c8f55653b91134fa520cec52bbfb706da836715230b0f9f4be，原权重和快照保留。

## 第二阶段：既有Windows SDK11兼容结论

新增 [静态SDK核查](../../../scripts/development/cosyvoice/acceleration/trt11_compatibility.py)。本机NvInferVersion.h用TRT_*_ENTERPRISE宏间接给出11.2.1.2，CP310 Windows wheel和nvinfer_11.dll存在；不导入绑定或创建CUDA上下文。

- 固定convert_onnx_to_trt使用NetworkDefinitionCreationFlag.EXPLICIT_BATCH，本机11.2.1.2头文件已无kEXPLICIT_BATCH；fp16分支使用的BuilderFlag.FP16也已移除。故**固定转换器不能直接使用SDK11**，不放宽首阶段10.13适配器版本守卫。需独立构建器create_network(0)、强类型ONNX与明确精度图；fp32对照需明确TF32策略。
- runtime路径仍有set_input_shape、set_tensor_address、num_io_tensors和execute_async_v3对应API；这仅说明接口形状可迁移，不能证明混合CUDA13 SDK与torch cu121对象/流可互操作。优先分进程导出/构建/CPU张量边界，SDK11不装入日用Cosy环境。
- 固定export_onnx.py走AutoModel、opset18、六输入和estimator_out，动态sequence轴，但未暴露streaming模式输入，默认图固定该掩码语义；脚本原写入model_dir，本轮不执行，未来改写实验副本。CV3可由AutoModel识别、DiT有out_channels，只构成导出入口证据；ONNX算子解析、形状可泛化、实际构建/推理/数值与声质均尚未验证。
- 后续GPU矩阵应有日用fp16 eager、fp32 eager控制、fp32 TRT11三路，区分精度变化与引擎效果；同输入/种子/声线/取消与质量门，不直接比较不同精度后宣称纯引擎收益。

一手依据：[NVIDIA11.2.1发布说明](https://docs.nvidia.com/deeplearning/tensorrt/latest/getting-started/release-notes-11/11.2.1.html)、[release11.2官方源码与Windows CUDA13.3包说明](https://github.com/NVIDIA/TensorRT/blob/release/11.2/README.md)、[11.x移除Python API](https://docs.nvidia.com/deeplearning/tensorrt/latest/api/migration/tensorrt-10x-to-11x-python-api-reference.html)、[11.2 runtime绑定](https://github.com/NVIDIA/TensorRT/blob/release/11.2/python/src/infer/pyCore.cpp)。静态报告保留SDK头文件指纹，当前状态仍needs_isolated_validation。

## 第二阶段：无需下载的Cosy/AD评测接力

新增 [Cosy runner](../../../scripts/development/cosyvoice/acceleration/cosy_runner.py)：make_runner接收调用方在整合树已隔离加载的本树synth，要求GPU调度收据、现有native取消适配和stream_chunks契约；禁用回复缓存，只接受3条固定合成case，WAV解码为真实PCM，设置同一seed后不允许并发重置，关闭迭代器沿原取消清理。模块不加载模型/创建服务器；本轮仅真实合成WAV替身测试，没有GPU执行。

evaluation_contract为AD/AI提供两层接口：producer有buffered/incremental、3case×2seed×2mode=12次测量，warmup另记；AD consumer在相同producer trace比较current/adaptive，分别记录协议支持与本实例可用、first_effective_answer_pcm/first_opus/buffer_ready、underrun、worst_gap、cancel_requested/last_delivered_frame/native_cleanup及followup_usable。AG的model PCM runner**不测AD实际播放策略收益**；需由AD真实consumer给这些观测，不能把生产块提前当自适应播放加速。设备扬声器、误抢话/续说和说完到有效声音仍须owner真实验收。

第二阶段组合回归74 passed（4.51秒），含原hidden-only/stream_runtime、文档机制、BGE合成矩阵替身、独立身份、实际Windows轻量Job限额查询及真实WAV解码替身；不重复运行BGE真实模型，也不运行GPU。

## 提交与接力

### 第三阶段：既有trtexec的有界真实执行入口

新增 [flow_trtexec.py](../../../scripts/development/cosyvoice/acceleration/flow_trtexec.py) 与 [契约测试](../../../tests/unit/development/test_flow_trtexec.py)，默认只生成只读资源/命令计划。没有执行trtexec、torch模型加载、ONNX导出或任何GPU工作，等待主会话先完成AD当前播放基准再发新窗口。本轮没有把TensorRT/vLLM标作原任务已全部完成。

现有官方trtexec.exe为947312字节、CP310 wheel为890696字节；源码/权重/工具资源的静态核对已通过，无需下载和安装。关键SHA256如下，代码还核对DiT模块、mask.py、yaml和SM89构建资源DLL：

| 已有资源 | SHA256 |
|---|---|
| flow.pt（1329116148字节） | a6fab32a7825e5b0bc855ddd948f8db9370b0a786fbc249caa4595e95b608e4b |
| trtexec.exe | 0b7f547a086b191d95424ac2739f8fe9a61a6b39a0ca4cb0d3dfbbf643796913 |
| nvinfer_11.dll | 19a836028d37b9dfe3171b88678c7c3b5abdba94ac79bee81c3be963569c5cd3 |
| nvonnxparser_11.dll | 9d15046ade1740a0f53d2d707e632de6b44525a6a5e02d1e78c5b39bb7b1000c |
| SDK自带CP310 wheel | f7f5174f416075c8101352e9afe04b991c50a87ce024fb26af41dd95ffb0c097 |
| CUDA13.3 bin/x64/cudart64_13.dll | b00ca6f53699120da815bf3e06e2e4285fae2f201235b883dcbb50eec51e2a2a |

仅解析flow.pt ZIP中的46353字节data.pkl opcode元数据（pickletools，不反序列化、不读张量payload），确认323个decoder.estimator.*键。后续window中才用现装torch2.3.1+cu121、numpy1.26.4、onnx1.16.0、ORT1.18.0、transformers4.51.3、x-transformers2.11.24：直接按已指纹核对的DiT配置实例化，只读mmap checkpoint、strict/assign加载估计器前缀，避免AutoModel的LLM/HiFT/前端和YAML构造副作用。缺前缀/版本/形状即停，不自行下载或补权重。

本轮静态resource_plan返回resources_match=true；本机trtexec二进制中九个所需flag字符串均存在，与官方release11.2参数源码相符，尚未执行工具确认解析。plan同时保存执行脚本/Job脚本摘要，真正窗口中另记GPU/驱动/显存元数据，防止只沿历史设备结论。第三阶段组合84 passed（5.10秒）、8模块实际Cosy3.10解释器AST语法通过；包含无GPU轻量broker后代继承Job/真实Windows限额查询与合成数值拒绝路径，未执行模型/GPU。公共文档清单仍由主会话接力。

候选流水线：

1. 独立Cosy Python进程导出FP32/buffered wrapper，数学SDPA、禁TF32，opset18，六输入x/mask/mu/t/spks/cond，输出estimator_out；固定batch2是CFG有条件/无条件双路，不是两个用户并发，只有序列轴动态。ORT明确CPU provider，无静默GPU回退。核对全部I/O名称、float类型、静态维和seq_len，再测N=16/127/128/257/512各全有效与尾1/4填零mask，共10组同输入torch/ORT allclose，rtol1e-2/atol1e-4。只落实验ONNX/合成FP32原始输入和reference。
2. 独立官方trtexec C++进程构建同GPU FP32 engine：profile min16/opt128/max512、noTF32、builderOptimizationLevel0、maxTactics8、workspace512MiB、skipInference。CUDA13 DLL只加该原生子进程PATH，不装Python TRT、不更改全局环境，不与torch cu121交换GPU指针。
3. 每组加载保存的同一个engine、实际原始输入及shape，单次运行并导出JSON结果。SDK11默认CUDA Graph开启、传输关闭，故显式noCudaGraph/noSpinWait/includeDataTransfers、warmUp0/duration0/iterations1。检查输出名称/维度/有限值并与同一torch reference逐值allclose。单次时延只供诊断，不作稳定速度或端到端声称。

profile外（少于16或多于512）、内部streaming、fp16/bf16/量化、CUDA Graph均不在此次候选支持内；现阶段保持eager，不补零截断或自动扩profile。streaming=False/True Python控制流固定在图中，不能把它当动态mask模式开关。后续若接声音服务还需fp32 eager控制组、日用fp16基线、声质/自然边界、续说/误抢话/取消残音与设备验收；当前C++ runner只支持中断自有离线Job，未提供请求级native abort。

有界窗口提案（均为预算/估算，未经GPU实测）：导出≤240秒，构建≤600秒，10组运行各≤45秒，全轮≤1320秒；宿主进程与全部后代Job提交内存合计硬限6144MiB、两逻辑CPU。估计宿主3–6GiB、GPU2–6GiB、磁盘产物3–6GiB，导出/构建约1–4/2–10分钟；实际可能触限失败，失败保留证据停止，不自动扩大或重试。先要求D盘空闲≥8GiB、GPU空闲≥8192MiB，产物目录采样限6GiB；PyTorch分配器限6144MiB、原生builder workspace512MiB，nvidia-smi采样设备总used>12288MiB即终止本Job。后两者不是GPU总内存硬限，不以空闲显存代替主会话租约。Python与原生程序均由start gate等候Job配置后执行；KILL_ON_JOB_CLOSE覆盖入口包装器、实际Python和C++后代。临时目录/CUDA cache/engine/日志全在新实验目录。

从AG树运行下列命令默认只读计划，--execute还要求显式固定Cosy解释器及新GPU窗口收据；目前没有该收据，不能执行第二条：

```powershell
$flowArgs = @('-B','-m','scripts.development.cosyvoice.acceleration.flow_trtexec',
  '--source','D:/03-项目/01-正式项目/智慧圆屏/local/runtime/CosyVoice',
  '--model','D:/03-项目/01-正式项目/智慧圆屏/local/runtime/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B',
  '--sdk','D:/01-开发环境/08-CUDA/TensorRT/TensorRT-11.2.1.2',
  '--toolkit','D:/01-开发环境/08-CUDA/Toolkit/v13.3',
  '--python','D:/03-项目/01-正式项目/智慧圆屏/local/runtime/CosyVoice/.venv/Scripts/python.exe',
  '--output',('D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ag-inference-engines-20261021/experiments/runs/ag-flow-'+[guid]::NewGuid().ToString('N')))
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' @flowArgs
# 仅主会话实际发放新窗口后：
# & 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' @flowArgs --execute --gpu-window-id $issuedGpuWindow
```

一手选项依据：[固定release11.2 sampleOptions.cpp](https://github.com/NVIDIA/TensorRT/blob/release/11.2/samples/common/sampleOptions.cpp)、[输出JSON格式](https://github.com/NVIDIA/TensorRT/blob/release/11.2/samples/common/sampleReporting.cpp)、[固定Cosy导出器](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/bin/export_onnx.py)、[torch2.3导出限制](https://docs.pytorch.org/docs/2.3/onnx.html)。当前只证明入口/资源/契约，不能证明模型成功导出、可构建或已加速。

vLLM/Linux继续保留待办：官方0.11.0 Docker tag可作为来源线索，但此次Docker Hub tag元数据页面不可访问，未核实manifest digest/体积；且纯vLLM镜像不等于固定CV3的完整依赖锁。尚无可运行完整锁+镜像+模型转换方案，故不提供半套owner获取脚本、不执行拉取/解析联网依赖、不声明完成；先执行无需新资源的本地SDK路径，再决定是否值得独立准备Linux完整环境。

本分支仅提交上述自有文件，不merge main、不push。主会话接力：审查精确提交，将ADR/本记录加入公共清单；把能力字段交AD，不默认启用候选；如继续真实加速，先协调独占GPU与完整离线资源，再做同输入/声线/种子的冷/热及并发对照和owner听验。现有buffered、角色/声音与学校免费模型保持原设置。
