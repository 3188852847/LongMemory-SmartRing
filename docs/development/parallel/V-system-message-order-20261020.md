# V：圆屏公共system约束顺序修复候选

2026-10-20。V确认工作树clean后从 `34f902291ad319382732b00f35667cd63639628f` 新建 `codex/v-voice-system-order-20261020`；先前 `177950f` 分支、SDK环境和证据保留。本候选不修改网关显式think边界，不宣称其解决了最新实机异常；未merge/push、改生产/私有配置、读个人历史或新增真实模型/搜索请求，未做性能采样。

## 代码事实及窄修范围

[web_response](../../../scripts/development/xiaozhi/voice_web_search.py)有两处项目自有末尾system：首轮 `_instruction(configured)` 包含原日期、检索时间与发表时间的区别、隐私等规则；搜索完成后再追加“不再调用工具”等约束。首轮不论是否具备工具都会追加。`_ObservedLLM.response` 的公共编排路径会调用web_response；某轮是否经过该具体路径仍由X实际取证，不能用静态代码冒充现场抓包。

候选只在本模块新增 `_with_system_instruction`，两处共用。首消息是文本system就合入；没有可合并首system时前置一条自有system，不改变原结构化content。普通合成问候以user结尾；搜索回答保留assistant工具调用→tool结果，结束于tool而不伪造新user。后续user/assistant/tool顺序、ID、参数及结果保留，原有合法中途system保持原位，原列表与第一阶段请求快照均不变。

原日期和约束文本保持，工具可用性判断、每轮至多一次搜索、执行端仅使用本轮原问句、错误回执和取消行为保持；不删除回答、不新增stop或EOS过滤，不改学校模型或推断服务器可由本项目管理。决定见[ADR-0193](../../adr/0193-owned-voice-system-instruction-placement.md)。

## 离线重现与测试

基线使用 `git show 34f9022:scripts/development/xiaozhi/voice_web_search.py` 的原函数，候选使用本工作树函数；注入纯合成配置、固定时钟和提供器，搜索也是内存替身。五种路径各做前后对照共10组：未配置/已配置、提供器有无函数接口、真实工具序列的合成替身。普通轮角色从system→user→system变为system→user；搜索二次回答从system→user→system→assistant→tool→system变为system→user→assistant→tool。各路径原策略逐字保留一次，原含日期的路径保留日期；全部原输入不变，工具ID配对有效。这里的“搜索”仅指合成函数，不产生任何网络请求。

合成编码展示只按已查V4分支给user/developer末尾增加符号化 `[ASSISTANT_GENERATION]`，用来显示尾system风险；不运行实际学校tokenizer、不推断权重，不把该风险解释写成已定位根因。[一手V4编码来源](https://docs.vllm.ai/en/v0.23.0/api/vllm/tokenizers/deepseek_v4_encoding/)说明的是特定实现；学校框架、版本和模板仍未知。

[定向单测](../../../tests/unit/development/test_voice_web_search.py)首轮36项通过（0.43秒），覆盖原列表不变、有无工具、日期/隐私规则、无首system、结构化system、原有中途system及旧工具历史、二次回答的成功/空/失败结果、当前原问句覆盖模型关键词、取消后不再请求回答。原测试把“完成system之后倒数第二项为tool”及“未配置约束在最后”当作固定位置，现按明确新契约检查末尾tool/末尾原user及调用关系；未删测试或弱化隐私/失败校验。

本地忽略证据根 `data/test-tmp/voice-system-order-34f9022-v/` 保留 `reproduce.py` 与 `result.json`；结果SHA-256为 `8d30680c1081ec6aa9ebb109075766252870fb1cfe74d38371ab800f3b5f5433`。不提交原始产物，公共记录不含个人对话、密钥或真实端点。

最终定向回归100项通过（1.57秒，无跳过），包含本模块36项、语音观测、等待交接/缓存及14项文档机制测试；JUnit在证据根 `regression.xml`，两份变更文档严格检查通过。另将相同合成驱动原样复制到独立 `python310/`，用现有小智Python3.10.20运行十组对照，结果摘要与主环境完全一致；该目录保留对应结果。不安装依赖、不加载模型、不改SDK或小智环境。`src/` 网关代码与main34逐文件差异为空，已有显式think边界保持。

## 实机反馈与发布条件

根会话转交X的最新单轮元数据确认该轮走model，字幕/发声属于该模型轮；归档含Unicode形式EOS，先前ASCII未命中已更正，不能否定设备反馈。此信息不证明学校具体模板，也不把本候选标为现场修复完成。V不重复读取该真实轮或个人历史。

交主会话/Z审精确提交，X核对该轮公共编排/末尾role及真实搜索路径。受控真实合成验证由主会话另行安排：不只看首content，需检查完整问候与当前问题相关、无日期/检索规则复述、无控制token，结束状态/usage/DONE完整，工具与取消契约保持；必要时再验真实字幕、语音和打断。验证若失败，应保留原响应格式证据重新定位，不能靠删普通正文或增加stop掩盖。原8次门按主会话交接已用6次，V不打开、不重置或新建替代额度；本候选真实模型/搜索请求均0。
