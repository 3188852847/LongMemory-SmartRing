# 冻结 L1 的本地检索消融

这一步只回答“相同事实库换检索器有什么变化”，不是完整问答对比。2026-09-03 已完成官方固定快照校验和首次真实 CPU 离线运行，32 次检索全部完成，见[结果复核](semantic-retrieval-review-2026-09-03.md)。这不是最终问答或成熟记忆系统验收。

## 新代码各自做什么

- `core/memory/retrieval/vector.py`：编码接口、带来源的条目、余弦排序、索引保存/重开。
- `adapters/llm/local_embedding.py`：固定 BGE 快照校验与纯本地 CPU 编码；延迟加载可选依赖。
- `evaluation/comparison/retrieval.py`：读取既有冻结 L1，关键词/向量独立查询，逐题记录来源与失败。
- `scripts/development/prepare_embedding.py`：仅下载固定官方版本必要文件，或校验导入手动下载的文件。

现有比较 runner、三个原方法、日常数据库和设备行为不变。模型与生成索引不进入 Git。

## 环境与模型准备

以下用于新环境复现；当前机器已准备完成，不必重新安装或导入。在项目根目录 PowerShell 执行，普通终端即可，不需要 ESP-IDF 或校园模型：

```powershell
uv sync --locked --extra console --extra semantic
uv run --locked --extra console --extra semantic python scripts/development/prepare_embedding.py
```

本轮曾在下载分词器时发生传输失败，随后从用户提供的 `G:\00-下载\bge-small` 导入以下文件，并逐项通过官方固定版本 Git/LFS 哈希校验；未修改用户下载目录，也未重复下载已有权重。以后遇到相同情况可按下面方式手动准备（示例文件夹需替换为实际路径）：

- tokenizer.json
- tokenizer_config.json
- special_tokens_map.json
- vocab.txt
- README.md（上游说明与许可）

[下载固定版本文件](https://huggingface.co/BAAI/bge-small-zh-v1.5/tree/7999e1d3359715c523056ef9478215996d62a620)。

```powershell
uv run --locked --extra console --extra semantic python scripts/development/prepare_embedding.py --from-directory "D:\path\to\downloaded-files"
```

导入仍需 HTTPS 读取官方元数据校验，但不下载文件；已有完整 snapshot.json 会拒绝覆盖。文件损坏也拒绝覆盖，不自动删除或重建。不要把 `.bin` 权重改名成 `.safetensors`。

注意：普通 `uv run`/`uv sync` 未指定 extra 时，不能假定可选依赖仍可用；这组命令显式保留 console 和 semantic。

## 运行这次既有开发实验

```powershell
$bgeDir = "data/models/bge-small-zh-v1.5/7999e1d3359715c523056ef9478215996d62a620"
$sourceReport = "experiments/runs/comparison-c356e00df09548ceaeb436d37c130bd2/report.json"
uv run --locked --extra console --extra semantic python -m longmemory.evaluation.comparison.retrieval --source-report $sourceReport --model-dir $bgeDir
```

无需加载 .env，运行不访问学校服务，不重新提取，也不生成回答。原实验必须是同一合成数据集已完成的报告，原库哈希、manifest 和历史必须匹配。只处理 longmemory_v1 与 longmemory_llm_extract_v2，不把分块表示偷偷改成原子事实。

新结果在 `experiments/runs/retrieval-<唯一ID>/`，含 manifest、两份索引和 report；索引保存模型身份、正文和全部来源。它们属于隔离合成产物，默认不提交。

## 怎么看结果

- `evidence_complete`：是否凑齐任一充分来源集合，未知题为 null；分母保留所有可回答题。
- `first_sufficient_rank`：前几条累计才包含充分来源，找不到为 null。
- `mean_reciprocal_sufficient_rank`：上述排名的倒数均值，失败/未运行/未找到为 0；不是标准逐文档 MRR。
- `source_hit_fraction`：带标注相关来源的条目占召回条目比例，仅为来源代理，不是人工语义准确率。
- `fully_redundant_source_items`：来源完全被前面覆盖的条目数，不等于语义重复率。
- `context_chars`、`retrieval_ms`：观察上下文长度与该次检索耗时。此轮不强制相同字符数、不含模型加载耗时，不是端到端延迟或问答比较。
- `state_unchanged`：旧语料与新索引查询期间未变；变化后停止该语料的剩余查询。

默认 top-5 无相似度阈值；小语料可能接近全量召回，要看排名和噪声，不要只看覆盖率。未进行阈值校准；`--min-score` 为显式研究参数，配置记录入 manifest，不能挑最好的一次当通用结论。

没有答案，不评拒答和最终问答。暂不使用 holdout；首轮排名已复核，下一阶段接相同回答条件与更多干扰事实。

完整边界见 [ADR-0011](../adr/0011-frozen-corpus-semantic-retrieval.md)。
