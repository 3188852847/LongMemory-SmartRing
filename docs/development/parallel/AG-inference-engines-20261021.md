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
# & 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' @flowArgs --execute --receipt $mainReceipt --receipt-sha256 $mainReceiptHash --production-root 'D:/03-项目/01-正式项目/智慧圆屏'
```

一手选项依据：[固定release11.2 sampleOptions.cpp](https://github.com/NVIDIA/TensorRT/blob/release/11.2/samples/common/sampleOptions.cpp)、[输出JSON格式](https://github.com/NVIDIA/TensorRT/blob/release/11.2/samples/common/sampleReporting.cpp)、[固定Cosy导出器](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/bin/export_onnx.py)、[torch2.3导出限制](https://docs.pytorch.org/docs/2.3/onnx.html)。当前只证明入口/资源/契约，不能证明模型成功导出、可构建或已加速。

vLLM/Linux继续保留待办：官方0.11.0 Docker tag可作为来源线索，但此次Docker Hub tag元数据页面不可访问，未核实manifest digest/体积；且纯vLLM镜像不等于固定CV3的完整依赖锁。尚无可运行完整锁+镜像+模型转换方案，故不提供半套owner获取脚本、不执行拉取/解析联网依赖、不声明完成；先执行无需新资源的本地SDK路径，再决定是否值得独立准备Linux完整环境。

### f65a0e4审查后的CPU-only执行准入修复

AI指出非空window ID和每阶段Job不能证明项目窗口或覆盖完整22分钟，本轮修复该实际缺口。新增 [window_admission.py](../../../scripts/development/cosyvoice/acceleration/window_admission.py)、[WDDM采集器](../../../scripts/development/cosyvoice/acceleration/wddm_snapshot.py) 和 [拒绝测试](../../../tests/unit/development/test_flow_window_admission.py)。采集器冻结自AD提交172a355de1534e621422aae90de2bab9fcd8dcbb，原文件SHA256=87ec064da57cded02bd3881724ba03fc0b29b5b62d3613c3f9e96001ff2f8892；不跨树导入或修改AD文件，后续共同规则变更需主会话协调同步。

最新入口替代旧的ID许可和阶段Job：--execute必须有main提供的--receipt、--receipt-sha256、--production-root和固定--python；--gpu-window-id已删除。收据原字节SHA256由主会话外部交接，不由本工具生成或发放。已关闭且过期的AD-GPU-20261021-01显式拒绝，AD scope/ID也不能改个期限复用。软件校验是对调度证据的匹配，不给自己授予停日用/GPU权限。

主会话新收据契约（仅字段说明，不是当前有效许可）：

- schema_version=2；scope=ag-flow-project-model-window；state=active；issued_by=main_session；新window_id前缀AG-FLOW-GPU-。
- project_model_window/production_stopped/other_gpu_model_workers_stopped必须为true，physical_gpu_exclusive必须为false，旧exclusive_gpu字段不接受。
- candidate_commit绑定本树实际清洁HEAD，checkout/production_root/output为精确绝对路径，输出必须新建；max_seconds精确1320，issued_at_utc/expires_at_utc有时区、不得未来发放/过期，剩余至少整轮预算加10秒；收据寿命至多1小时。
- bindings_sha256来自CPU-only --admission-plan：包含全部AG加速源码原字节、固定厂家源码指纹、权重/SDK关键资源、两解释器入口和Win32查询到的真实映像（避免只看venv包装器）、python*.dll摘要；Cosy环境枚举全部已安装distribution版本及METADATA/RECORD摘要。该摘要不是对每个第三方安装文件的逐字节审计，关键模型/SDK文件另按固定原字节检查。实际Cosy3.10.20及六个固定依赖版本也单独核对，不混装/升级。
- shared_desktop_baseline须含GPU UUID、WDDM、驱动版本、main_session审查者/时间和唯一processes集合；审查距发放不得超过120秒。每个桌面上下文精确PID、创建token、context_type G或C+G及background_only批准；普通映像精确路径，受保护System/dwm保留AD逻辑角色/父代/会话和明确review_note。desktop_baseline_sha256为该完整对象的规范JSON摘要。

主会话在审查并合入适当候选、工作树清洁后可先运行原flowArgs加--admission-plan，只读输出binding对象与摘要，不生成收据、不采GPU、不导入torch；当前仅离线实现/测试，没有生成真实新窗口。环境/依赖摘要由metadata subprocess读取，未载入模型或运行推理。任意绑定/源码变化要重新审查收据，不能悄悄更新字段。

运行设计为唯一随机命名外层Windows Job：父进程进入execute即开始1320秒总计时，初始收据/CPU绑定核查也计入。controller先阻塞stdin，父进程Assign到外层Job成功后才发许可；controller、真正Python、原生broker、trtexec和采集辅助进程都继承同一Job，阶段不再新建Job或重置时限。外层硬限总提交内存6144MiB/两逻辑CPU。父进程communicate只使用总截止剩余值；超时、Assign失败或controller异常时仅终止本次Job，确认ActiveProcesses=0再Close，并保留outer-job-cleanup结果；不按进程名称或基线PID结束任何外部应用。Job查询句柄可能由子进程持有，故不能仅依赖KILL_ON_JOB_CLOSE。

controller/导出worker在模型前及各阶段门、运行采样点重新读取原收据SHA/状态/期限、核对源码原字节和精确WDDM基线。采集沿AD的NVML XML＋compute CSV、Win32映像/创建时间及CIM父代/会话；不读取命令正文。未知C/C+G、driver/GPU变化、PID重用/路径变化/身份未解析、桌面集合新增或消失均拒绝。自有GPU进程还必须IsProcessInJob=true且映像属于本次绑定的解释器或trtexec，不能凭python名称或进程树猜测。源码改动/收据撤销在下一检查点停止；采样间隙和同PID内部背景负载仍不可观测，保留background_noise_present及physical_gpu_exclusive=false，不把显存容量/工作区采样冒作硬独占。

CPU-only实际验证：三组加速相关测试90 passed，含关闭AD ID、过期/未来/无时区/撤销、scope/commit/bindings/路径错误、未知C+G、PID重用/映像/驱动漂移、精确集合变化、非Job成员、依赖摘要漂移、Assign失败不发许可、外层唯一Job全程超时清理、真实轻量子进程的命名Job成员查询及持查询句柄时的终止归零，以及解释器真实映像只读元数据。10模块由实际Cosy Python3.10 AST解析通过。旧的ID-only broker测试改为明确拒绝该已失效前提，没有放宽实现或重跑GPU。所有NVML快照均为合成输入，未采集实际GPU、未加载/导出/trtexec、未下载/安装、未停/启日用；AD旧窗口未使用。

本分支仅提交上述自有文件，不merge main、不push。主会话接力：审查精确提交，将ADR/本记录加入公共清单；把能力字段交AD，不默认启用候选；如继续真实加速，先协调新的项目模型窗口与完整离线资源，再做同输入/声线/种子的冷/热及并发对照和owner听验。现有buffered、角色/声音与学校免费模型保持原设置。

收尾复核：三组加速测试与14项文档机制测试合计104 passed（2.38秒）；上述两份自有文档采用内存清单补录执行audit，checked_documents=2、findings=[]，没有修改主会话负责的公共清单。Git差异检查通过。此前草稿中的125项计数不对应本次三组测试范围，已按实际输出更正，不作为额外验收证据。

### 唯一真实窗口001：失败事实与证据保留

ROOT签发AG-FLOW-GPU-20261021-01，绑定清洁e4dc45cd、原plan及新精确共享桌面基线；发放原字节SHA256为79326d14df79f0e5a6666321796284c1a65be75a0a6d86a49746f96818d7def2。AG仅执行一次，UTC 2026-10-20 22:44:52.750199至22:45:30.316225，入口退出码1。到达DiT FP32导出，子进程在torch.onnx的graph._export_onnx处出现MemoryError，随后RuntimeError: Could not allocate bytes object!；没有生成ONNX/engine，未进入trtexec构建/运行，未完成任何10样本数值验收或声音验收。日志另有opset18支持警告，不能把警告等同此次错误原因。

21次准入记录中前20次通过；最后一次export:running拒绝：此前被认定为本Job成员的PID4744此时身份无法解析（Win32错误87），同时新增PID63724 OpenWith.exe的C+G上下文，精确桌面集合变化。保存的这些事实不能把4744直接改写成外来模型，也不能免除63724的拒绝；不推断OpenWith出现原因。控制器最后保存GPUWindowBlocked，导出日志另有独立分配错误，因此两者都保留，不将stale采样作为唯一根因。Job显式终止并确认ActiveProcesses=0，记录owned_tree_exit_confirmed=true、cleanup_error=null、production_services_touched=false。e4旧异常路径没有保存Job峰值，无法事后补测；不把6GiB限制或TensorRT能力当已证根因。

ignored原始目录为`experiments/runs/ag-flow-6496873888c34589899f89c0c3debcd4/`，保留全部8个原文件及后加attempt-summary.json；摘要SHA256=c98762d6aa8511c1c3fa4d709938858a83c586b87651583c34fc20c39be0366a，含retained8文件摘要。ROOT随后报告已独立核对这些字节、退出状态、无剩余模型上下文及flow.pt原摘要，关闭001并保留issued副本；closed收据SHA256=2242d0fe04feef9686a9bf0113f238cec202d219b0d269026d9d18085638152d。ROOT负责恢复buffered日用，AG未操作生产生命周期，以上不替代ROOT的ready验收记录。不提交原日志、张量、plan或二进制，也不修改原失败产物。

### CPU-only：异常路径计量与退出取证

新增[job_accounting.py](../../../scripts/development/cosyvoice/acceleration/job_accounting.py)公开只读查询：JobExtendedLimitInformation及BasicAndIoAccounting。原自有WindowsResourceJob.snapshot与OuterJobQuery.snapshot均使用该接口，只需查询权限，不读取AD/launcher私有句柄/字段。记录Job/单进程峰值提交字节、Job/进程内存硬限、亲和性和limit flags，以及活动/累计/终止进程、CPU 100ns计量、缺页与IO字节/次数；这些不是工作集，也不自动证明某次失败由限额导致。

父入口无论成功、非零退出、超时或Assign失败，均在终止前和终止后、关闭句柄前尽力保存outer-job-resources.json；查询失败写errors且仍清理，保留原异常。每次合法准入采样附同一外层Job的计量。阶段保存export-exit.json等退出证据与原日志摘要：若检查期间子进程已自行非零退出，OwnedStageFailure优先携带其退出码，同时保留并发准入拒绝；正常退出或尚存活的子进程遇外部上下文变化仍拒绝。无stale PID豁免、无重试、无阈值放宽。001另加入显式关闭集合，即使修改收据日期也不能再用。

轻量CPU验证覆盖8MiB分配后的正常/异常退出，以及1GiB测试Job拒绝一次2GiB VirtualAlloc提交请求（立即失败，未实际占用2GiB缓冲），确认峰值/限额/CPU/IO计量可在退出后读取，终止后active_processes=0且峰值保留；命名Job的只读查询句柄也验证通过。合成测试保留子进程非零退出与同时新增外部上下文两条证据，并核对采样失败仍终止。真实GPU预算仍为6GiB/2CPU/1320秒，本轮仅轻量CPU测试。

### CPU小图：opset17/18实测与低内存提案

只读取现装torch2.3.1的onnx/utils.py、_constants.py及_internal/onnx_proto_utils.py。utils.py:1544针对大于ONNX_TORCHSCRIPT_EXPORTER_MAX_OPSET的请求只发warning，注释说明仍允许较新opset的自定义symbolic；_constants.py中旧导出器max/default为17，另一个ONNX_MAX_OPSET=19不是同一能力字段。utils.py:1647–1693先由graph._export_onnx生成Python proto字节，再经_add_onnxscript_fn及_export_file；export_params=False分支传空参数字典。这里可定位分配阶段，不能确定原生分配大小或6GiB因果。

使用固定Cosy3.10环境，CUDA_VISIBLE_DEVICES为空，禁止CUDA初始化、checkpoint加载及网络连接；小图仅88参数，Linear＋LayerNorm＋CPU scaled_dot_product_attention，输入长度3/5与完整/尾部掩码。父进程先Assign自有2GiB/2CPU Job再通过stdin放行，60秒CPU预算，ORT仅CPUExecutionProvider，不加载真实Flow或声线。

第一份ignored证据`experiments/runs/ag-cpu-opset-20261021-01/`保留失败：图参数输入仍启用常量折叠时，Linear权重变成onnx::MatMul_32，直接按named_parameters喂入失败。没有掩盖该参数映射前提错误。第二份独立小图证据`experiments/runs/ag-cpu-opset-20261021-02/`仅对参数输入变体关闭常量折叠，内嵌参数变体保持原配置：

| 小图变体 | opset17 | opset18 |
|---|---|---|
| 内嵌参数、常量折叠开启 | 图写入17；4组CPU比较通过 | 图写入18；4组CPU比较通过，保留支持范围warning |
| 参数输入、常量折叠关闭 | 图写入17；4组CPU比较通过 | 图写入18；4组CPU比较通过，保留支持范围warning |

共16组比较，rtol=1e-4/atol=1e-5，最大绝对误差3.5762786865234375e-7；只证明这些玩具算子/形状。report.json SHA256=472f7c77e248669ec43ad8fe99826a94ac2adc66c93153c7022f3cca580c7a81，probe.py=3afe3c65ebc2da14f91b9117d932335c60e2a37f6a303e57b3d1d60e283ffb33，receipt.json=04006552c94362cc03dc47b6d6f9ceb28ebc1a9fcca90bc0a3049fd66f978717。该小图Job峰值525000704字节、退出码0、终止前后active_processes=0；不可外推真实Flow峰值/耗时/性能。source-analysis.json另保存三份现装源码原字节摘要，SHA256=ca0a0c98c590496b64c6297a5b9712e3e288fab55f531a7bb57391bb7961c318。全部原始证据继续ignored。

可审低内存候选尚未实施到真实导出器：先export_params=False生成无内嵌大权重的图，明确关闭折叠对参数映射的影响；逐个检查参数名/维度/类型与原FP32权重一致，再以有界块写external data并用offset/length引用，避免一次构造整份Python权重proto。必须拒绝缺失/衍生/不明参数，打包后ORT及原10样本比较与trtexec解析仍需重新验收；每个图/外部数据文件均纳入不可变摘要。普通onnx.save_model追加raw_data可能仍复制整份权重，不能仅换文件后缀宣称省内存。真实内存下降、导出时间和SDK读取兼容性均未知，当前只提出方向，不估算为结果。

opset更改与低内存打包是独立变量：不因小图成功直接把真实18改成17，也不引入dynamo/新依赖、FP16、profile变化或提高6GiB限制。若主会话选择进一步实施，先确定单项变化及CPU小图/外置数据契约，再用新plan和ROOT新窗口检验真实模型；本次没有第二次真实导出或GPU操作。新源码/提交使旧0d918f...bindings失效，001已用完，不沿用旧plan或收据。

本轮收尾验证：加速相关四组测试及文档机制测试合计113 passed（2.84秒），含真实轻量CPU进程与只读Job计量、子进程/并发拒绝双证据、关闭001及计量查询失败后的清理。11模块通过Python3.10语法核对；两份自有文档内存清单audit检查无findings，公共清单仍交主会话处理。本轮只提交自有源码/测试/这两份文档，不提交ignored原始证据、不merge/push，不代表真实模型导出已修复。

### 从c74b8883继续：外置权重候选已实施，真实Flow仍待验

按ROOT委派，在既有AG树新分支`codex/ag-flow-external-data-20261021`从c74b88834683080d4dc4ee4b770f48707ff5b349开始。先复核001的attempt-summary及retained8文件摘要，全部匹配；未改变原失败事实，也没有补造其峰值。AD声线窗口优先，本阶段没有停日用、采实际GPU、加载真实Flow、执行trtexec或获取/安装资源。

新增[external_weights.py](../../../scripts/development/cosyvoice/acceleration/external_weights.py)。图导出只接受固定torch2.3.1+cu121、自有CPU FP32/eval实例及CPU样例；使用export_params=False、keep_initializers_as_inputs=True、do_constant_folding=False，维持默认opset18。按图输入精确匹配registered parameter/buffer名称、dtype与固定维度，CPU ndarray只作零拷贝视图；流写块大小最多4MiB、按FP32边界对齐，每块检查有限值。无整权重tobytes或将权重先填入TensorProto.raw_data；小图中只添加EXTERNAL TensorProto引用。每参数记录offset/length/原字节摘要，另记录整数据文件、小图摘要和实际最大write大小。

支持边界为平坦图及非空连续小端FP32参数；未知/转置折叠衍生参数名、非连续/非FP32、符号参数维度、嵌套图、稀疏initializer、本地函数及已有外置引用明确失败。图上限64MiB、外置数据上限6GiB；这些不替代整轮已有6GiB产物采样和Job限额。输出必须全新，固定文件名model.onnx/weights.bin/manifest.json，拒绝路径逃逸。逐文件与参数引用校验通过后最后创建manifest，供下游识别完成；失败/取消仅unlink本次成功创建的文件，保留failure.json，不覆盖或递归清理既有目录。强制杀进程若留下部分文件，无清单即不可消费。微型测试验证了取消保留旁侧文件，原失败目录也不在清理范围。

已接入flow工具的显式`--export-recipe external_fp32_v1`候选，默认`legacy_embedded`不变；配方成为bindings内容，切换配方必改摘要。新配方先在CPU生成分离图/权重，打包后才转GPU做原FP32 reference；关闭折叠和改变导出设备的影响都必须由后续原10样本验证，不能用小图替代。ORT仍显式CPU，最终只暴露原六输入与estimator_out。主控制器缺ONNX，故只调stdlib-only verify_bundle_files；完整ONNX图/参数引用校验位于Cosy导出环境，不能因此给主环境安装包。构建路径指向external-candidate/package/model.onnx，其他trtexec参数/精度/profile不变；构建前再次核对清单及原字节。执行入口/唯一外层Job/准入/原6GiB、2CPU、1320秒预算不变。未生成新的真实admission-plan或收据，001仍关闭。

CPU验证利用既有Cosy3.10.20环境：torch2.3.1+cu121、numpy1.26.4、onnx1.16.0、ORT1.18.0。该环境无pytest，因此[独立CPU套件](../../../tests/fixtures/external_weights_cpu_suite.py)使用标准库unittest，由主pytest通过stdin门在自有2GiB/2CPU/60秒Job内启动；禁止网络、CUDA初始化及checkpoint加载。15项套件覆盖精确映射与输出、形状/dtype/非连续/符号维度拒绝、未知onnx::MatMul_32拒绝、有限值/取消/超额清理、既有目录保护、篡改/摘要/外置路径拒绝等。88参数的Linear/LayerNorm/attention微图实际写出352字节权重；opset17/18各4组ORT CPU比较均通过，最大绝对误差3.5762786865234375e-7；每个配方实际7次write、最大64字节，所有参数恢复为initializer且输入只保留x/mask。18的支持范围警告仍记录，真实配方不改成17。

独立ignored证据在`experiments/runs/ag-external-cpu-21e2ef1e9ef147cc8e420048b3f6bdf4/`：cpu-suite.json SHA256=364a0b275645365dea9fde4c21f1e35750b70be507dc7f05bb98ef6ced56d4a1；receipt.json=b8998c19a9e36196ae3580c8053f845359cd51fda7111419536e7ec05c9b60a1。收据包含完整argv、源码摘要、Job限额、CPU/IO和终止前后计量；峰值提交555446272字节、退出码0、清理后active_processes=0、cuda_initialized=false、real_flow_loaded=false。SHA256.json列出微型数据/图/清单/日志指纹，仅ignored保留，不提交二进制。此峰值包含框架和整个测试套件，不能与旧小图或原失败直接比较，也不能据此声称真实内存下降。

未验证项：真实DiT是否保留全部可精确绑定的参数名/FP32连续布局、CPU trace与GPU eager原10输入数值、图优化和外置格式的SDK11.2.1.2/中文路径读取、原6GiB内峰值/耗时/容量，以及声音/取消/设备行为。任何映射失败应报告具体名字并停止，不能临时猜测或修改profile/精度。ROOT→AI审查代码后，AD完成才可由ROOT安排新窗口；新的候选提交、配方、资源/环境或输出路径均需新plan绑定，不能复用001或旧0d918f...摘要。

### vLLM：隔离Linux环境完整交接条件，当前不构成可安装锁

官方0.11.0材料确认Linux、Python3.9–3.12及默认CUDA12.8二进制；该版本cuda.txt固定torch/torchaudio2.8.0、torchvision0.23.0、Linux x86_64的xformers0.0.32.post1。common.txt仅约束transformers>=4.55.2，并非完整传递锁。本项目既有适配器选择transformers4.57.1；固定Cosy源码仍用074ca6dc...，不能把其torch2.3.1/transformers4.51.3的requirements原样混入此环境。依据：[固定平台文档](https://docs.vllm.ai/en/v0.11.0/getting_started/installation/gpu.html)、[固定cuda.txt](https://github.com/vllm-project/vllm/blob/v0.11.0/requirements/cuda.txt)、[固定common.txt](https://github.com/vllm-project/vllm/blob/v0.11.0/requirements/common.txt)。

| 交接对象 | 固定目标/边界 | 进入执行前仍缺的工件或证据 |
|---|---|---|
| Linux基底 | 单独Linux x86_64环境；候选Python3.10.20在官方支持范围内 | 实际发行版/glibc/解释器工件摘要、对应镜像manifest与平台digest；官方tag不等于选定Python版本或已验证digest |
| vLLM/PyTorch ABI | vLLM0.11.0、torch/torchaudio2.8.0、torchvision0.23.0、xformers0.0.32.post1；目标CUDA12.8二进制族 | 每个Linux wheel/共享库的精确build、来源与SHA256；实际加载库/驱动兼容验收；不复用Windows SDK11或cu121 DLL |
| Cosy层 | 固定Cosy提交、transformers4.57.1候选；x-transformers2.11.24等原依赖须逐项兼容 | 全量传递依赖锁/平台markers/工件摘要；Deepspeed0.15.1等固定原依赖与torch2.8尚未整合验证，不能用忽略依赖命令伪装完成 |
| ONNX/flow/HiFT | 初轮vLLM只替换speech-token LLM，适配器load_trt=False | Tokenizer/ORT provider选择及CUDA/cuDNN相容锁；不默认把原Linux ORT-GPU1.18/cu121组合视为cu128兼容，不强装原requirements中的TRT10.13 |
| 镜像和离线物料 | 镜像、全量wheelhouse及模型都由所有者取得 | 平台/层digest、下载及展开体积、完整依赖工件清单、离线重建/自检记录；当前没有完整可复现成品，不拉镜像 |
| 模型身份 | 独立staged模型，保留原日用目录；不能沿用无身份旧vllm导出 | Fun-CosyVoice3模型精确revision及llm/flow/hift/tokenizer/campplus/BlankEN等全文件摘要；导出产生config/tokenizer/权重指纹及容量 |
| 进程/资源 | Linux专用进程/目录/cache；共享物理GPU由ROOT另排，AD优先 | 新窗口与Linux进程/cgroup归属、独立资源限额和退出核验、实际显存/主存/磁盘预算；未知值不先宣称可容纳或加速 |
| 回退/验收 | 上游导出会改head并删层，只销毁独立进程和自有实验输出回退 | 同一合成输入/seed/参考音频的eager对照、首PCM/总时延/续说和abort记录；不支持文字生成器/热切换的边界保留 |

该表完整列出交接类别，但缺项仍真实存在，所以不提供半套安装/镜像拉取/模型转换命令，不尝试联网依赖解析或借本次CPU许可启用Linux GPU。当前交付的可运行代码集中在既有依赖可验证的外置权重候选；vLLM保持blocked/needs_isolated_validation。BGE原FP32与旧局部INT8证据不变，未重建个人索引，也不混入本轮发布。

AD真实声线窗口期间按ROOT要求暂停模型加载/批量测试，仅做文档/静态审查；收到关闭窗口通知后才恢复本段CPU验证。最终六组pytest共118 passed（5.32秒），其中一次子进程执行15项unittest，不把内部15项重复加总。新增普通逻辑测试证明配方改变bindings、默认路径/其他builder参数不变、主控制器核验不需ONNX；最初一项新测试错误地按正斜杠比较Windows路径，修为按Path.parts比较后通过，未放宽实现。

最终源码对应的独立CPU证据为`experiments/runs/ag-external-cpu-final-e2fec63c3ccb41f4a74fe5c1a8b8e73d/`：cpu-suite.json SHA256=51ba38c3f60cec02f5817b31670495e9d5c3ad5eaa076646c7cccb16d0732850；receipt.json=756320817475511a5dd29c962bb82ebe47df9a6ea4d0fdfd4aebdf0f67ad373a；library-at-run.py=7ba619e25d441ce7ef3f2a4de59b757479740d2e6f34d771aa6ca3e42e043384。目录保留实际套件/库/Job查询源码副本、现装Torch导出器源码摘要及全部工件指纹，15项CPU套件零失败/零错误；Job峰值554733568字节、退出码0、终止后活动进程0，CUDA未初始化、真实Flow未加载。它是最终源码的微型验证，不改变001原始结果，也不证明真实模型已解决MemoryError。仅提交自有代码/测试/ADR/本记录，不merge main、不push、不修改公共文档清单。
