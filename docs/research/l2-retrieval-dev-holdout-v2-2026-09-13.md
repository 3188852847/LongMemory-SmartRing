# L2 场景召回 V2 开发/留出协议（2026-09-13）

## 数据边界

- 文件：`datasets/synthetic/l2_retrieval_v2.json`
- 冻结 SHA-256：`0beb68c78347de7e14c897adc87ae679ac0e4fbda2e6784515c4691987b76fa2`
- 场景：11 个当前有效，2 个已过期
- 开发集：24 题，其中 15 题可回答、9 题无答案
- 留出集：14 题，其中 9 题可回答、5 题无答案

内容全部为合成生活场景，不含个人记忆。本版本新增相近但缺少关键属性的问题、过期场景问题以及需覆盖两个场景的问题。

## 冻结前开发基线

| 策略 | 可回答 Hit@3 | 全证据覆盖 | MRR | 无答案正确空召回 |
|---|---:|---:|---:|---:|
| `l2_keyword_v1` | 15/15 | 15/15 | 0.967 | 0/9 |
| `l2_dense_cosine` | 15/15 | 15/15 | 1.000 | 0/9 |

稠密检索使相关场景排名更稳定，但开发集的主要矛盾已不是“找不到”，而是“没有证据时仍然返回候选”。下一版候选应将召回排名和可回答性门控分开，不继续用单个余弦阈值兼任两种职责。

留出集在数据冻结前只做了结构校验；不记录或使用其召回指标调整下一候选。

## 指标语义修正

冻结后的特征核对发现，不能把“无答案”一律解释为“不应召回任何上下文”。因此新增独立标注 `l2_retrieval_v2_relevance_v1.json`，其 SHA-256 为 `d386829fb7dc6ff6b57644d9fd6461b1ae9022a4b454e7984ca6650ab86f94e4`，并与上述数据集哈希强绑定。

开发集中，21 题存在当前有效的主题相关场景；其中 15 题有直接作答证据，6 题只是主题相关但缺少被问属性。另有 3 题不存在当前可用的相关场景。

| 策略 | 21 道主题题 Hit@3 | 3 道无可用主题题正确空召回 |
|---|---:|---:|
| `l2_keyword_v1` | 21/21 | 0/3 |
| `l2_dense_cosine` | 20/21 | 0/3 |

这不否定原始 0/9 记录，而是修正它的解释：其中 6 题需要证据充分性门控，不应单靠召回阈值处理。见 ADR-0136。

## 复现

默认只运行开发集：

```powershell
uv run --no-sync python -m longmemory.evaluation.l2_retrieval
```

加入项目内已校验的本地 BGE：

```powershell
uv run --no-sync python -m longmemory.evaluation.l2_retrieval --embedding-model-dir "data/models/bge-small-zh-v1.5/7999e1d3359715c523056ef9478215996d62a620"
```

只有候选门控已冻结时，才显式增加 `--split holdout`。

## 证据充分性开发运行

以本地 BGE 生成关键词＋稠密 RRF 候选，再用明确选择的模型配置档逐题复核。当前运行器固定为 `dev`，最多 24 次请求，不重试，不读个人数据库：

```powershell
uv run --no-sync python -m longmemory.evaluation.l2_sufficiency `
  --model-profile official `
  --allow-model-requests `
  --embedding-model-dir "data/models/bge-small-zh-v1.5/7999e1d3359715c523056ef9478215996d62a620"
```

报告保存数据、标注、编码器、门控提示和不含密钥的模型身份；每题保存候选分数、结构化决定、误放行和误拦截。真实开发结果在实际运行前不预写。
