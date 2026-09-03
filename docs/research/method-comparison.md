# 最小跨方法比较：运行与读报告

这是阶段 C 的实验入口，不是聊天入口，也不是论文效果排名。实现依据为 [ADR-0009](../adr/0009-minimal-frozen-comparison-protocol.md)。

## 做什么

同一合成历史 → 两种方法分别形成记忆 → 关闭并冻结状态 → 每题独立召回和回答 → 逐题检查证据与答案。

- `longmemory_v1`：当前“第一人称规则提取＋规范化事实＋关键词召回”，原算法不变。
- `dialogue_chunks_v1`：原消息按同会话连续两条分块，保留双方角色、时间和来源；关键词召回。批次封存后不支持追加，不接入当前日常聊天管理接口。
- `longmemory_llm_extract_v2`（显式启用）：独立模型产生来源绑定候选，整批校验后原子保存 L0/L1/来源/候选审计；仍使用 v1 关键词召回。这是提取消融条件，不是完整语义检索升级，也不是论文复现。
- 每方法最多五个召回条目，统一最多注入 4000 字符；来源覆盖按完整召回结果计算，不代表截断后的注入必然充分。
- 回放不让模型生成新历史；回答阶段不保存问题、回答或新事实，不带上一题上下文。实验不使用圆屏或小智服务。

## 一条命令离线运行

在 LongMemory 项目终端：

```powershell
Set-Location "D:\02-项目\LongMemory-SmartRing"
uv run --locked python -m longmemory.evaluation.comparison.runner --provider fake
```

已有环境也可用 ` .\.venv\Scripts\python.exe -m longmemory.evaluation.comparison.runner --provider fake`，不需要安装新依赖。默认只运行 8 道开发题，两种方法共 16 次回答器调用；不调用网络、不读 `.env` 里的真实模型选择、不接触日常库。

Fake 只会少量猫名/拒答规则；它对茶名、姓名、研究方向等回答失败不代表真实模型也失败。离线运行的价值是验证接口、来源、状态冻结和报告，不以 Fake 答案分数挑选方法。

## 使用学校模型

由用户在能访问学校模型时执行，助手不代为网络探测：

```powershell
uv run --locked --env-file .env python -m longmemory.evaluation.comparison.runner --provider openai_compatible
```

使用既有 `LONGMEMORY_LLM_*` 设置，HTTP 仍要求显式允许且会明文发送凭据和合成内容。默认开发集共 16 次模型请求，串行执行、失败不重试；可能有调用成本和服务等待，不代表需要同时运行小智。

两种方法都用中性记忆助手系统提示，不带爱莉希雅角色，减少表达风格干扰。服务端采样配置未核实、没有强制种子；一次运行只能做初步检查，不能下统计结论。

留出题先不运行。完成基于开发题的算法调整后，单独用 `--split holdout` 检查保留题，并记录使用次数；这四题不是盲测基准。

## D1：加入模型提取条件

候选接口、兼容适配器及实验装配已离线验证。由用户在校园网执行：

首次真实三组运行已完成，见[复核记录](d1-extraction-review-2026-09-03.md)。以下命令供复现，不要求对已完成运行重复调用或追求更高初筛分数。

```powershell
uv run --locked --env-file .env python -m longmemory.evaluation.comparison.runner --provider openai_compatible --include-llm-extraction
```

这一次同时重跑三组，避免拿另一批随机回答直接拼作同期对照。默认合成历史包含 7 条 user 消息，最多额外调用 7 次提取模型，问答最多 3×8＝24 次，共最多 31 次模型请求；不自动重试、不运行保留题。默认提取单次 max_tokens=1024（可显式 `--extraction-max-tokens` 调整），回答仍用原 `.env` 配置；可能涉及服务费用与等待时间。提取与回答使用同一配置模型，但系统提示完全分开，真实权重和服务端采样仍未核实。

不带新参数仍只运行原两组。CLI 不允许 Fake 冒充 LLM 提取，离线替身仅在合成测试/API 验证中使用；不要把它的通过数当质量指标。

读新报告时，先检查 `builds.longmemory_llm_extract_v2`：

- `status` 与 `duration_ms`：整段历史是否成功构建、总耗时；失败时该组 8 道题仍保留，不继续用残缺历史答题。
- `extraction.request_attempts`：含失败在内的实际提取请求尝试数，不含回答请求，也不是 token/计费统计。
- `extraction.events`：逐事件阶段、耗时、请求数、已校验候选及摘录。失败响应正文不落报告；候选格式成功不等于事实正确。
- `observations`：实际 ADD/NOOP 与记忆 ID；候选的 ADD 不代表一定新增，精确重复仍走原去重逻辑。
- `manifest.method_settings.longmemory_llm_extract_v2`：提取模型配置、提示版本/哈希和未更换的检索算法。

新增状态目录 `longmemory_llm_extract_v2/` 只包含该实验的 `memory.db`，含独立的候选审计与方法身份表。冻结重开检查身份，禁止 observe、不提供提取器；个人库和通用 V3 schema 不迁移。

首次验收的重点不是期待三组都 8/8：确认非第一人称事实能否被正确提取，同时检查问句、助手猜测、否定和来源。姓名仍可能因关键词检索失败，这是下一轮检索升级的问题。不要改旧分数、挑一题反复重跑或用保留题调提示。

## 产物位置和目录用途

每次运行都会创建不同目录，不覆盖旧结果：

```text
experiments/runs/comparison-<唯一ID>/    # 一次独立实验，默认不提交 Git
├─ manifest.json                       # 数据/代码/提示版本、方法设置、预算与运行顺序
├─ history.json                        # 完整合成事件档案，保留原角色、时间、会话、顺序
├─ report.json                         # 全部逐题结果、故障状态、汇总；每题刷新检查点
├─ longmemory_v1/                      # 本次原子事实方法的专属状态，不复用日常库
│  └─ memory.db                        # 独立 SQLite；问答时只读
└─ dialogue_chunks_v1/                 # 本次对话分块方法的专属状态
   └─ chunks.json                      # 封存原始消息，召回时按固定规则重建块
```

数据库消息的历史时间来自数据集；L1 recorded_at 仍是实际提取时刻，不能拿它当事实发生时间。平台保存会话原值，旧基线忽略会话分组的事实在 manifest 中披露，不自动给日常 V3 加列。

## 读报告的顺序

1. 看 `status`、`summary`：完成多少、失败多少、中断多少；答案分母是全部选定题目，不因模型请求失败变小。
2. 看 `builds`：历史写入时发生了什么操作。不同方法操作名称不同，不以“新增条数更多”判定更好。
3. 逐题看 `support.retrieved` 及 `source_event_ids`：需要的历史证据是否被找到。`evidence_complete` 检查至少一组充分证据；`null` 表示不适用或无法评估，不算零分。
4. 看 `injected_context` 和 `context_truncated`：回答器实际收到什么，而不是只看数据库里有什么。
5. 看 `answer` 和 `answer_proxy_pass`：词面初筛需要人工复核，特别是拒答后又猜测、否定句和同义表达。多事实题分别检查多个必需词语。
6. 看 `state_unchanged`：若为 false，本轮冻结被破坏，后续题中止，不拿这组作正常结果。

例如“我叫林澄”→“我是谁”应保留为当前算法的失败案例，不为通过测试新增专用词项；“研究方向：机器人导航”则能暴露第一人称提取策略的遗漏。

## 独立复核附页

首次真实模型开发集已完成，见[逐题复核与 D1 边界](comparison-dev-review-2026-09-03.md)。词面分数相同并不表示两组失败原因相同。

对任意后续报告，可以离线创建附页（下列路径替换为实际新运行路径）：

```powershell
uv run --locked python -m longmemory.evaluation.comparison.review prepare --report experiments/runs/comparison-<ID>/report.json --output experiments/results/review-<ID>.json --reviewer "复核者名称" --reviewer-kind human
uv run --locked python -m longmemory.evaluation.comparison.review summarize --report experiments/runs/comparison-<ID>/report.json --review experiments/results/review-<ID>.json
```

先阅读来源、注入和整段回答，再在附页填写 verdict（pending/pass/fail/unscorable）和 rationale（依据）。创建时全为 pending；汇总不会自动判断语义。助手复核必须使用 assistant 类型，不冒充人工盲评。工具验证原报告哈希和完整题目清单，拒绝覆写已有输出；不调用模型、不修改原分数。附页可能涉及敏感实验内容，默认留在被 Git 忽略的 experiments/results 内。

## 不包含什么

不是 MemRL 复现；不支持反馈学习、工具任务、参数记忆或任意第三方插件隔离。没有费用/token 统计，没有自动语义裁判，没有置信区间。完整网页聊天会话恢复、两端配置自动同步、个人库会话迁移均不在本阶段。

下一步不是扩建平台，而是 D1：用开发结果决定 LongMemory 第一轮算法升级；与此同时按共同任务选择 D2 的论文对照。
