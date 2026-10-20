# ADR-0200：推理引擎候选的实例、精度与平台边界

2026-10-21。状态：隔离工具已实现，生产接线及 GPU/实际声质验收待完成。编号由主会话预留。

## 决定

新增引擎实验层，不改正式声音服务、日用配置、模型选择或检索索引。能力清单分开报告固定源码支持、平台/依赖条件及实例验收；不自动选引擎。学校远程 LLM 的推理服务器不受本机控制，本地 vLLM 开关不能加速该服务器。

原生 flow TensorRT 只接预构建、同 GPU/版本/固定源码且摘要匹配的 fp32 plan，要求独立 fp32、模型内部 buffered 实例。保留原 estimator，构造成功后替换，失败保留原值；撤回不覆盖后安装的适配。固定上游 flow 直接绑定数据指针，fp16 输入不能绑定 fp32 引擎；ONNX 图未暴露运行时 streaming 掩码，暂不宣称内部流式等价。精度和模式均纳入对照条件。

局部 `torch.compile` 仅编译 flow estimator.forward，不改 LLM（语言模型）、语音采样或 hidden-head bypass（跳过无消费者的文本词表输出）。固定 torch2.3.1 的 Inductor 在 Windows 明确抛错；Linux 隔离候选才可试验。延迟编译失败撤回并抛错，调用方丢弃整次候选响应，在新请求中回退，不能把半段候选音频拼到基线。

vLLM0.11.0/torch2.8.0/transformers4.57.1 是另一套 Linux 依赖，不能混装到 CosyVoice 原 torch2.3.1 环境。固定源码的导出会改语音 head、写模型子目录并移除原层，必须用事先准备的实验模型目录和独立进程；不支持生成器式文字输入。Triton/TensorRT-LLM 专用路径也属于另一套部署，未固定所有容器/转换权重摘要前不运行上游自动 clone/download/upgrade 脚本。

BGE CPU 动态 INT8 只生成独立 Bert Linear 权重候选，保留原模型，不重建持久索引。相同合成库和查询必须同时核对 Recall@k（前 k 名中的相关文档召回率）、首位一致性及实际速度。不存在已证明的 CosyVoice3 INT8/INT4/FP8 量化契约时，不套通用 Qwen 模型支持。

## 验收和回退

GPU 操作需主会话独占窗口；显存空闲检查不替代调度许可。基准的 runner 接收 case_id、seed、取消事件，返回 CPU PCM（脉冲编码音频）块。分别记录首次 PCM、首个能量达标 PCM、总耗时、RTF（生成耗时/音频时长）、供给间隙和取消关闭时间；它们不等于用户说完到圆屏首个有效回答声音。

自动质量筛查发现时长、削波、静音或连续性退化即保留基线；音色/清晰度、续说取消、误抢话、打断残音与端到端首答仍须独立验收。BGE 候选还需最终问答/记忆一致性验证。并发 1/2/4 分开测，不把吞吐量当单用户延迟，不为等候凑批延迟日用请求。具体实现、固定源与本轮真实证据见 [AG 记录](../development/parallel/AG-inference-engines-20261021.md)。

## 一手依据

- [固定 CosyVoice3 构造器](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/cli/cosyvoice.py) 和 [flow 指针调用](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/flow/flow_matching.py)。
- [固定 vLLM 示例](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/vllm_example.py)、[vLLM0.11.0 平台要求](https://docs.vllm.ai/en/v0.11.0/getting_started/installation/gpu.html)、[该版 CUDA 依赖](https://github.com/vllm-project/vllm/blob/v0.11.0/requirements/cuda.txt)。
- [固定 CosyVoice3 TRT-LLM 说明](https://github.com/FunAudioLLM/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/runtime/triton_trtllm/README.Cosyvoice3.md)。其 L20 多并发数字不用于 RTX4080 单用户承诺。
- [torch2.3.1 Windows 编译守卫](https://github.com/pytorch/pytorch/blob/v2.3.1/torch/_dynamo/eval_frame.py)、[CUDA Graph 约束](https://docs.pytorch.org/docs/2.3/notes/cuda.html)、[CPU 动态量化 API](https://docs.pytorch.org/docs/2.8/generated/torch.ao.quantization.quantize_dynamic.html)。
