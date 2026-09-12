# L2 场景召回合成基线（2026-09-13）

## 范围

本次只使用 `datasets/synthetic/l2_retrieval_v1.json` 的 6 条合成场景与 13 个合成问题，不打开个人数据库、不调用回答模型、不改变网页或圆屏日常算法。冻结数据 SHA-256：`b16f442f422e2a72f385814d598e66babbeace545adcfcc52d572ee5d65e77ac`。

本地编码器为项目既有固定快照 `BAAI/bge-small-zh-v1.5`，revision `7999e1d3359715c523056ef9478215996d62a620`，编码器身份 `43435848b0ebf50613b0090a38953e56754b11962a79000f096121f0b15b297b`。CPU、CLS、L2 归一化与查询前缀沿用 ADR-0011。

## 结果

| 策略 | 可回答题 Hit@3 | MRR | 无答案题正确空召回 |
|---|---:|---:|---:|
| `l2_keyword_v1` | 8/9 | 0.889 | 0/4 |
| `l2_dense_cosine`（无阈值） | 9/9 | 1.000 | 0/4 |

BGE 找回了关键词完全漏掉的“昼夜节律怎样”抽象改写。但最难的无答案干扰题最高余弦为 0.530，高于该正确抽象改写的 0.434，因此这组数据上不存在一个简单全局阈值同时保住该正确结果并挡住全部无答案噪声。

## 判断

模拟数据足以否决“把无阈值纯向量 top-k 直接替换日常 L2”以及“拍一个全局余弦阈值”两种方案。它不能证明真实产品效果：场景与问题由开发者构造，规模很小，且尚未测最终回答是否能基于噪声证据正确拒答。

下一实现候选应比较受控融合或两阶段门控，并继续保留无答案题；只有模拟开发集不退化后，才用真实圆屏回执做外部效度检查。

## 复现命令

仅关键词：

```powershell
uv run --no-sync python -m longmemory.evaluation.l2_retrieval
```

加入已校验本地 BGE：

```powershell
uv run --no-sync python -m longmemory.evaluation.l2_retrieval --embedding-model-dir "data/models/bge-small-zh-v1.5/7999e1d3359715c523056ef9478215996d62a620"
```
