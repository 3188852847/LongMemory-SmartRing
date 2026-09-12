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
