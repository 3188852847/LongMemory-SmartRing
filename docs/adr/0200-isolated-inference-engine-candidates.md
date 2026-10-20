# ADR-0200：推理引擎候选的实例、精度与平台边界

2026-10-21。状态：隔离工具已实现，生产接线及 GPU/实际声质验收待完成。编号由主会话预留。

## 决定

新增引擎实验层，不改正式声音服务、日用配置、模型选择或检索索引。能力清单分开报告固定源码支持、平台/依赖条件及实例验收；不自动选引擎。学校远程 LLM 的推理服务器不受本机控制，本地 vLLM 开关不能加速该服务器。

原生 flow TensorRT 只接预构建、同 GPU/版本/固定源码且摘要匹配的 fp32 plan，要求独立 fp32、模型内部 buffered 实例。保留原 estimator，构造成功后替换，失败保留原值；撤回不覆盖后安装的适配。固定上游 flow 直接绑定数据指针，fp16 输入不能绑定 fp32 引擎；ONNX 图未暴露运行时 streaming 掩码，暂不宣称内部流式等价。精度和模式均纳入对照条件。

局部 `torch.compile` 仅编译 flow estimator.forward，不改 LLM（语言模型）、语音采样或 hidden-head bypass（跳过无消费者的文本词表输出）。固定 torch2.3.1 的 Inductor 在 Windows 明确抛错；Linux 隔离候选才可试验。延迟编译失败撤回并抛错，调用方丢弃整次候选响应，在新请求中回退，不能把半段候选音频拼到基线。

vLLM0.11.0/torch2.8.0/transformers4.57.1 是另一套 Linux 依赖，不能混装到 CosyVoice 原 torch2.3.1 环境。固定源码的导出会改语音 head、写模型子目录并移除原层，必须用事先准备的实验模型目录和独立进程；不支持生成器式文字输入。Triton/TensorRT-LLM 专用路径也属于另一套部署，未固定所有容器/转换权重摘要前不运行上游自动 clone/download/upgrade 脚本。

BGE CPU 动态 INT8 只生成独立 Bert Linear 权重候选，保留原模型，不重建持久索引。相同合成库和查询必须同时核对 Recall@k（前 k 名中的相关文档召回率）、首位一致性及实际速度。不存在已证明的 CosyVoice3 INT8/INT4/FP8 量化契约时，不套通用 Qwen 模型支持。

量化改变 embedding recipe（向量生成配方）及 provider identity（编码器身份）；候选输出独立元数据/指纹，不能沿用现有FP32身份。19+19次真实CPU前向的12候选/4查询实验只验合成旧索引查询及合成新索引配对，不授权日用切换、个人索引重建或身份迁移。第二阶段收窄为已有资源优先：AD同模型自适应缓冲/AC CPU话轮优先，BGE只交局部测量；不先下载Linux绑定wheel。现有Windows TensorRT11.2.1.2具有独立兼容候选条件，但固定转换器的EXPLICIT_BATCH/FP16构建API与SDK不兼容；导出/构建/推理/精度仍需独占GPU验证，不能用SDK历史测试替代。

第三阶段选择已有官方trtexec作为独立C++ builder/runner，避开向Cosy日用环境安装绑定或混用CUDA13/torch cu121指针。只提取固定flow checkpoint中的DiT估计器，固定FP32/buffered掩码、batch2及16..512帧profile，通过torch→ORT→TRT三者同输入数值比较后仍只形成离线flow候选。原生进程先等待Job资源限制配置，才放行构建/运行；没有GPU窗口不执行。显存采样守卫、workspace与PyTorch分配器上限分别标记，不能把workspace当总显存硬限。取消先仅支持终止自有实验Job，不承诺TTS请求粒度取消；生产接入继续待验。

AI审查f65a0e4后追加执行准入：非空窗口ID不是许可。要求主会话v2项目模型窗口收据及原字节摘要，绑定清洁提交、源码、资源、解释器真实映像/运行DLL、安装包METADATA/RECORD摘要、输出路径与新期限，显式拒绝已关闭AD-GPU-20261021-01。采用AD 172a355的WDDM采集规则并加精确桌面集合/驱动校验；只有本次唯一外层Job的成员且映像已绑定才算自有GPU worker，未知C/C+G和身份漂移均停止。桌面仍共享，同PID内背景负载不可观测，不声称硬独占。全部准入、导出、构建、运行共用1320秒总期限和一个外层Job；父进程赋予stdin许可前先Assign，收尾显式Terminate自有Job并确认0活动进程再Close，避免子进程查询句柄阻止关闭式清理。该追加仅CPU/离线验证，未授权或执行GPU。

## 2026-10-21：真实失败后的取证修订

唯一新窗口AG-FLOW-GPU-20261021-01曾执行e4dc45cd，导出进程报MemoryError及Could not allocate bytes object；控制器最后一次采集同时遇到此前自有PID已无法解析和新增OpenWith.exe上下文，按精确基线拒绝。没有ONNX或engine，没有进入TensorRT构建，也没有声质/性能结论。旧实现未保存异常路径Job峰值，不能把6GiB或TensorRT支持作为已证根因；原证据保持原样，窗口已由ROOT关闭。

修订为显式的自有Job查询接口：成功、异常、超时及Assign失败均尽力保存终止前/后的峰值提交内存、限制、活动/累计进程、CPU与IO计量，查询失败单列且不阻止清理。查询句柄只需JOB_OBJECT_QUERY，不访问AD/launcher内部字段。采集期间若子进程已非零退出，以子进程退出作为阶段失败入口，保留同时发生的准入拒绝和原日志摘要；仍停止整个实验，不豁免stale PID或新增外部上下文。峰值/限额本身也不证明某次分配失败的唯一原因。001加入不可复用ID集合；未来需新提交、新plan及ROOT新收据，6GiB/2CPU/1320秒保持不变。

现装torch2.3.1的旧导出器对opset18只警告后继续，常量支持上限为17；88参数的CPU小图在17/18、内嵌参数/参数输入四种变体均通过ORT CPU比较，不能外推真实DiT。小图还证明常量折叠可能改变参数输入映射，因此低内存候选仅作为待审提案：先导出无内嵌参数的图，再逐项核对参数映射并流式写external data（外置张量数据），避免整份权重进入大Python protobuf字节对象。关闭折叠、外置权重打包和trtexec解析都需独立验证并绑定全部文件摘要；真实峰值、耗时与收益未知，不切换正式导出器，不改精度/profile，不提高上限。详细证据和实施门见AG记录。

## 验收和回退

GPU 操作需主会话独占窗口；显存空闲检查不替代调度许可。基准的 runner 接收 case_id、seed、取消事件，返回 CPU PCM（脉冲编码音频）块。分别记录首次 PCM、首个能量达标 PCM、总耗时、RTF（生成耗时/音频时长）、供给间隙和取消关闭时间；它们不等于用户说完到圆屏首个有效回答声音。

自动质量筛查发现时长、削波、静音或连续性退化即保留基线；音色/清晰度、续说取消、误抢话、打断残音与端到端首答仍须独立验收。BGE 候选还需最终问答/记忆一致性验证。并发 1/2/4 分开测，不把吞吐量当单用户延迟，不为等候凑批延迟日用请求。具体实现、固定源与本轮真实证据见 [AG 记录](../development/parallel/AG-inference-engines-20261021.md)。

## 一手依据

- [固定 CosyVoice3 构造器](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/cli/cosyvoice.py) 和 [flow 指针调用](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/flow/flow_matching.py)。
- [固定 vLLM 示例](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/vllm_example.py)、[vLLM0.11.0 平台要求](https://docs.vllm.ai/en/v0.11.0/getting_started/installation/gpu.html)、[该版 CUDA 依赖](https://github.com/vllm-project/vllm/blob/v0.11.0/requirements/cuda.txt)。
- [固定 CosyVoice3 TRT-LLM 说明](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/runtime/triton_trtllm/README.Cosyvoice3.md)。其 L20 多并发数字不用于 RTX4080 单用户承诺。
- [torch2.3.1 Windows 编译守卫](https://github.com/pytorch/pytorch/blob/v2.3.1/torch/_dynamo/eval_frame.py)、[CUDA Graph 约束](https://docs.pytorch.org/docs/2.3/notes/cuda.html)、[CPU 动态量化 API](https://docs.pytorch.org/docs/2.8/generated/torch.ao.quantization.quantize_dynamic.html)。
