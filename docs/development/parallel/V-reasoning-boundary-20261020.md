# V：答案与显式推理边界修复

2026-10-20。V工作树先确认clean，从 `765ef5a118f3c5e061bc20430b78a7db11141820` 建立 `codex/v-reasoning-boundary-20261020`；此前分支、证据和SDK环境均保留。所有者报告圆屏语音和字幕都出现异常推理内容，本次不认定旧版已通过实机验收。V只读源代码、构造脱敏合成响应；未读个人对话、未请求学校模型、未改正式配置/生产/SDK、未下载或重做性能采样。

## 已证事实与现场未知

基线 [ModelGateway](../../../src/longmemory/methods/hy_memory/model_gateway.py)设置 `thinking: disabled` 后逐原始SSE行转发，解析只用于usage/DONE；没有主动把推理字段改名为content。[PersistentProviderTransport](../../../src/longmemory/methods/hy_memory/provider_transport.py)传输字节，不做字段合并。仅凭透传不能证明推理污染。

固定小智源码的普通与工具分支都只读取delta.content。普通分支仅在单chunk查找完整think标签，跨chunk会漏出；同chunk同时含开始和结束标签还可能丢掉最终答案。工具分支没有think过滤。V只读其原始LLMProvider类，以AST执行原类方法、用网关SSE解析出的合成OpenAI-compatible chunk对象喂入；没有替代其消费逻辑、调用SDK或外部HTTP。X另负责固定完整源码及真实消费契约验证，V不修改外部小智源码。

| 合成上游格式 | 765ef5a普通分支 | 765ef5a工具分支 | 本候选投影后两分支 |
|---|---|---|---|
| 独立reasoning_content＋最终content | 仅最终答案 | 仅最终答案 | 仅最终答案；不映射推理字段 |
| 同content中完整前导think块＋答案 | 最终答案丢失 | 推理与答案一起输出 | 仅最终答案 |
| think标签跨content增量 | 推理与答案一起输出 | 推理与答案一起输出 | 仅最终答案 |
| 无标签普通content中的推理措辞 | 原样输出 | 原样输出 | 仍原样输出，无法可靠区分 |

该表证明明确可重现的候选缺陷及修复范围，不证明现场实际返回了哪种格式。尚无脱敏现场格式证据。

## 实现边界

- 新增[有界解析器](../../../src/longmemory/methods/hy_memory/answer_content.py)，只认前导精确小写think控制块；普通正文中间、代码围栏及工具参数中的标签不作全局删除。独立reasoning_content只移除、不回填content，空答案不伪造文本。
- 网关流式voice及非流式answer/probe共用同一答案投影。按完整有界SSE事件解析后输出；role、tool_calls、finish_reason、usage和DONE保留。开始标签跨增量最多保留70字符，推理中最多保留7字符尾；不等待整回答再伪分块。
- 首次正常文本及时输出；格式未闭合、JSON错误、首包取消保留unknown，不补DONE、不重试。Hy及baseline提取响应保持原样，不更改提取/存储/检索行为。持久传输层、回答prompt和供应商配置不变。
- 无标签推理、缺少开始标签的模板预填充、非约定语法无法安全剥离。后续只能先核实所选免费供应商实际支持的非推理模式/结构化字段；不猜参数、不额外请求、不自动换模型。决定与回退见[ADR-0192](../../adr/0192-owned-answer-content-boundary.md)。

## 验证与交接

[答案边界单测](../../../tests/unit/methods/test_hy_answer_content.py)覆盖所有两段切分、逐字增量、长推理有界尾部、嵌套/连续块、独立字段/混合增量/多choice、空/工具输出、普通正文保留、未闭合和首包取消。[持久传输测试](../../../tests/unit/methods/test_hy_provider_transport.py)新增真实临时回环HTTP的JSON＋SSE串联：UTF-8多字节中途拆包、标签跨content、两次请求复用同一连接、usage/DONE及预算结算均核对。首轮专项129项通过（2.06秒），不代表设备验收。

原始对照留在本工作树忽略目录 `data/test-tmp/hy-reasoning-boundary-765ef5a-v/`，包含可复跑的 `consumer-repro.py`、全新合成账本及16项 `consumer-results.json`。固定消费源码SHA-256为 `5dfec38041d28436362b4a1b0f5946d1bdff7bb9afb3501c6417037a6bd3b006`，结果文件SHA-256为 `cacac50edb86b2681bbefcf754e9cc629fb93c931be4a7230fdb35ee6d29cb5e`；仅有输出摘要、长度及是否暴露合成标记的布尔值，无个人正文。依赖核对和初版测试驱动分别遇到主环境缺OpenAI依赖、测试logger缺TAG常量；未安装依赖，初版驱动留下的合成目录保留，不作验证证据。

最终补充null/空delta结束包兼容后，定向回归151项通过（6.50秒，无跳过），包括答案/流式/持久传输/预算/非流式回答适配、真实SDK接合成上游的原提取网关集成，以及14项文档机制测试；JUnit保存在同证据根的 `regression-final.xml`，前次150项回归亦保留。两份变更文档的严格检查通过。该集成只读现有SDK、全新合成工作区及向量替身，未加载真实BGE或访问学校模型；未进行性能采样。

交X用固定原提供器及工具分支验证最终正文、字幕/发声共同文本、首文本及取消；交主会话审查整合。未merge/push，不改X文件或其他会话配置。合入后仍须安排真实字幕、语音和打断回归；若实际为无标签普通content，需另核实供应商能力，不能以本补丁宣称现场故障已解决。
