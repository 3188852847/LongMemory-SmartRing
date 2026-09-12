# 冻结检索阈值回放记录（2026-09-13）

## 目的

记忆智能阶段需要判断本地 BGE 的余弦分数能否作为“没有相关记忆”的门槛。现有
`HybridMemoryRetriever` 只融合关键词与稠密排名，没有经过校准的最低分；直接切换
个人日常配置可能让无关问题也拿到一个相对最高的记忆。

本次只回放既有冻结报告保存的候选和分数，不重新提取、不重新编码、不调用聊天模型，
也不读取个人数据库正文。旧冻结实验数据库已经落后于当前 schema，不能由现有方法类
重新打开；这也是增加独立分数回放工具的原因。

## 结果

数据来自 `method_comparison_v1` 的 8 道 dev 合成题，其中 6 道可回答、2 道未知。

| 阈值 | 提取条件 | 充分证据覆盖 | 未知题空召回 | 平均召回数 |
|---:|---|---:|---:|---:|
| 0.35 | `longmemory_v1` | 5/6 | 1/2 | 0.875 |
| 0.35 | `longmemory_llm_extract_v2` | 6/6 | 1/2 | 1.625 |
| 0.45 | `longmemory_v1` | 3/6 | 1/2 | 0.625 |
| 0.45 | `longmemory_llm_extract_v2` | 4/6 | 1/2 | 1.125 |
| 0.55 | `longmemory_v1` | 3/6 | 2/2 | 0.375 |
| 0.55 | `longmemory_llm_extract_v2` | 4/6 | 2/2 | 0.625 |
| 0.65 | 两种条件 | 0/6 | 2/2 | 0.000 |

## 决定与边界

- 不从 8 道开发题选择生产阈值，不修改个人库的关键词召回配置。
- 未知题空召回只是检索诊断，不等于最终回答已经正确拒答。
- 原报告只保存当时 top-k 候选，回放无法恢复 top-k 之外的低分条目。
- 下一步优先让真实日常召回结果带可审计分数并结合人工反馈，再评估门控或排序策略。

离线复核命令：

```powershell
uv run --no-sync python -m longmemory.evaluation.comparison.retrieval_thresholds `
  --retrieval-report experiments/runs/retrieval-92deeedf9d8d4d419abdec3f2e45f4c4/report.json `
  --threshold 0.35 --threshold 0.45 --threshold 0.55 --threshold 0.65
```
