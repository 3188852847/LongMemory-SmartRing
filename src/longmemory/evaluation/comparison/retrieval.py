"""冻结已有 L1 语料，仅比较检索；不重跑提取、回答，不修改旧实验。

这是检索消融，不是新增完整记忆方法或论文复现。共享同一次提取结果，
避免比较时把模型重新改写造成的差异误归因给检索器。
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from longmemory.adapters.llm.local_embedding import LocalBGEEncoder
from longmemory.core.memory.retrieval.vector import ExactVectorIndex, VectorDocument, fingerprint
from longmemory.evaluation.runner import provenance
from longmemory.methods.contracts import MemorySupport, RetrievedTrace
from longmemory.methods.dialogue_chunks.method import event_json
from .dataset import load_dataset
from .methods import METHOD_NAME, open_method, state_digest
from .runner import DEFAULT_DATASET, PROTOCOL, ROOT, now, write_json
from .scoring import score_evidence

PROTOCOL_VERSION = "frozen-l1-retrieval-ablation-v1"


def load_source(path, dataset):
    raw = path.read_bytes()
    report = json.loads(raw)
    manifest = report["manifest"]
    if (manifest["protocol"] != PROTOCOL or report["status"] != "completed"
            or manifest["dataset"]["sha256"] != dataset.sha256):
        raise ValueError("需要同一合成数据集已完成的比较报告。")
    if json.loads((path.parent / "manifest.json").read_text(encoding="utf-8")) != manifest:
        raise ValueError("旧报告的 manifest 不一致。")
    history = json.loads((path.parent / "history.json").read_text(encoding="utf-8"))
    if history != [event_json(e) for e in dataset.history]:
        raise ValueError("旧实验历史与所选合成数据不一致。")
    names = tuple(name for name in ("longmemory_v1", METHOD_NAME) if name in manifest["method_order"])
    if not names:
        raise ValueError("没有受支持的 L1 实验方法。")
    for name in names:
        build = report["builds"][name]
        if build["status"] != "completed" or state_digest(path.parent / name) != build["state_sha256"]:
            raise ValueError("旧实验构建未完成或冻结状态已改变。")
    return report, hashlib.sha256(raw).hexdigest(), names


def read_corpus(name, directory, valid_sources):
    method = open_method(name, directory, frozen=True)
    try:
        # 仅这个实验导出器了解已有两个 L1 方法，公共方法契约不强迫论文
        # 摘要/图结构伪装为原子事实。所有数据通过只读连接读取。
        base = method._base if name == METHOD_NAME else method
        documents = tuple(VectorDocument(str(m.id), m.content, tuple(
            str(e.source_message_id) for e in base.memory_store.list_evidence(m.id)))
            for m in base.memory_store.list_active())
        if any(set(d.source_event_ids) - valid_sources for d in documents):
            raise ValueError("L1 来源不属于这批用户历史。")
        return documents
    finally:
        method.close()


def retrieval_metrics(question, support):
    result = score_evidence(question, support)
    items = support.retrieved or ()
    result.update(retrieved_count=len(items), context_chars=len(support.context))
    # 未知题并不要求完全不召回：相关事实仍可能合理，不能把空结果当拒答质量。
    if question.abstain:
        result.update(first_sufficient_rank=None, source_hit_fraction=None)
    else:
        relevant = {sid for group in question.evidence_sets for sid in group}
        result["source_hit_fraction"] = (sum(bool(set(i.source_event_ids) & relevant) for i in items)
                                         / len(items) if items else 0.0)
        seen, first = set(), None
        for rank, item in enumerate(items, 1):
            seen.update(item.source_event_ids)
            if first is None and any(set(group) <= seen for group in question.evidence_sets):
                first = rank
        result["first_sufficient_rank"] = first
    # 这只是重复来源占用，不等于语义重复率：相同事实的不同来源可能仍重复。
    seen, redundant = set(), 0
    for item in items:
        sources = set(item.source_event_ids)
        redundant += bool(sources) and sources <= seen
        seen.update(sources)
    result["fully_redundant_source_items"] = redundant
    return result


def summary(rows):
    result = {}
    for name, strategy in dict.fromkeys((r["method"], r["strategy"]) for r in rows):
        group = [r for r in rows if (r["method"], r["strategy"]) == (name, strategy)]
        answerable = [r for r in group if not r["expected_abstention"]]
        result[f"{name}/{strategy}"] = {
            "total": len(group), "completed": sum(r["status"] == "completed" for r in group),
            "answerable_total": sum(not r["expected_abstention"] for r in group),
            "evidence_complete": sum(r["status"] == "completed" and r.get("evidence_complete") is True for r in group),
            # 未找到/失败/未运行计 0，不能丢掉困难题；充分证据排名不是
            # 标准逐文档 MRR，尤其多事实题需要累积齐一组来源。
            "mean_reciprocal_sufficient_rank": (sum(
                1 / r["first_sufficient_rank"] if r["status"] == "completed" and r.get("first_sufficient_rank") else 0
                for r in answerable) / len(answerable) if answerable else None),
        }
    return result


def frozen_unchanged(state, digest, index_path, index_hash):
    try:
        return (state_digest(state) == digest
                and hashlib.sha256(index_path.read_bytes()).hexdigest() == index_hash)
    except (OSError, ValueError):
        return False


def run_retrieval(source_path, dataset, encoder, *, output_root, split="dev", min_score=None):
    source_path, output_root = source_path.resolve(), output_root.resolve()
    if output_root.is_relative_to(source_path.parent):
        raise ValueError("新结果不能写进旧实验目录。")
    if split not in {"dev", "holdout"}:
        raise ValueError("无效的题目划分。")
    if min_score is not None and (type(min_score) not in (int, float)
                                 or not math.isfinite(min_score) or not -1 <= min_score <= 1):
        raise ValueError("无效的余弦阈值。")
    source, source_hash, names = load_source(source_path, dataset)
    questions = [q for q in dataset.questions if q.split == split]
    if not questions:
        raise ValueError("所选划分没有问题。")
    metadata = encoder.metadata
    if encoder.identity != fingerprint(metadata):
        raise ValueError("编码器身份与元数据不一致。")
    directory = output_root / ("retrieval-" + uuid4().hex)
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {"protocol": PROTOCOL_VERSION, "started_at": now(), "source_report_sha256": source_hash,
                "source_manifest": source["manifest"], "code": provenance(), "encoder": metadata,
                "encoder_id": encoder.identity, "split": split, "limit": 5, "min_score": min_score,
                "strategies": ["original_keyword", "dense_cosine"], "new_llm_requests": 0,
                "limitations": ["retrieval_only_no_answer_quality", "synthetic_not_paper_benchmark",
                                "source_hit_fraction_not_semantic_precision", "no_calibrated_abstention_threshold",
                                "same_source_redundancy_not_semantic_dedup", "linear_scan_not_scale_benchmark",
                                "context_size_observed_not_equalized", "single_run_latency_not_benchmark"]}
    write_json(directory / "manifest.json", manifest)
    rows = [{"method": name, "strategy": strategy, "question_id": q.id, "query": q.query,
             "expected_abstention": q.abstain, "status": "interrupted", "error": "not_run"}
            for name in names for q in questions for strategy in manifest["strategies"]]
    report = {"manifest": manifest, "builds": {}, "questions": rows, "status": "running"}
    with (directory / "report.json").open("x+", encoding="utf-8") as stream:
        def checkpoint():
            report["summary"] = summary(rows)
            stream.seek(0)
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.truncate()
            stream.flush()
        checkpoint()
        try:
            for name in names:
                state = source_path.parent / name
                digest = source["builds"][name]["state_sha256"]
                build = report["builds"][name] = {"status": "running", "source_state_sha256": digest}
                start = perf_counter()
                try:
                    if state_digest(state) != digest:
                        raise ValueError("source changed")
                    docs = read_corpus(name, state, {e.event_id for e in dataset.history if e.role == "user"})
                    index = ExactVectorIndex.build(docs, encoder, encoder_id=encoder.identity)
                    index_path = directory / (name + "-vectors.json")
                    index.save(index_path)
                    index_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()
                    # 重开索引后再查询，校验持久化，而非只测试内存中的临时向量。
                    index = ExactVectorIndex.load(index_path, encoder_id=encoder.identity)
                    if state_digest(state) != digest:
                        raise ValueError("source changed")
                    build.update(status="completed", document_count=len(docs),
                                 corpus_sha256=fingerprint([asdict(d) for d in docs]), index_sha256=index_hash)
                except Exception:
                    build.update(status="failed", error="index_build_failed")
                    for row in rows:
                        if row["method"] == name:
                            row.update(status="failed", error="index_build_failed")
                    continue
                finally:
                    build["duration_ms"] = round((perf_counter() - start) * 1000, 3)
                    checkpoint()
                contaminated = False
                for q in questions:
                    for strategy in manifest["strategies"]:
                        row = next(r for r in rows if (r["method"], r["strategy"], r["question_id"]) == (name, strategy, q.id))
                        if contaminated:
                            row.update(error="previous_freeze_violation")
                            checkpoint()
                            continue
                        started, method = perf_counter(), None
                        try:
                            if not frozen_unchanged(state, digest, index_path, index_hash):
                                raise ValueError("frozen state changed")
                            if strategy == "original_keyword":
                                method = open_method(name, state, frozen=True)
                                support = method.recall(q.query)
                            else:
                                matches = index.search(encoder.encode_query(q.query), min_score=min_score)
                                retrieved = tuple(RetrievedTrace(d.item_id, d.content, d.source_event_ids) for d, _ in matches)
                                context = ("以下是与当前问题相关的长期记忆：\n" + "\n".join(f"- {d.content}" for d, _ in matches)) if matches else ""
                                support = MemorySupport(str(uuid4()), context, retrieved)
                                row["scores"] = [s for _, s in matches]
                            row.update(support=asdict(support), retrieval_ms=round((perf_counter() - started) * 1000, 3))
                            # 标签仅在检索返回以后用于评分，不交给编码器或索引。
                            row.update(retrieval_metrics(q, support), status="completed", error=None)
                        except KeyboardInterrupt:
                            row.update(status="interrupted", error="user_interrupted")
                            raise
                        except Exception:
                            row.update(status="failed", error="retrieval_failed")
                        finally:
                            if method is not None:
                                method.close()
                            unchanged = frozen_unchanged(state, digest, index_path, index_hash)
                            row["state_unchanged"] = unchanged
                            if not unchanged:
                                contaminated = True
                                row.update(status="failed", error="frozen_state_changed")
                            checkpoint()
        except KeyboardInterrupt:
            for build in report["builds"].values():
                if build["status"] == "running":
                    build.update(status="interrupted", error="user_interrupted")
        finally:
            report.update(status="completed" if all(r["status"] == "completed" for r in rows) else "incomplete",
                          finished_at=now())
            checkpoint()
    return directory, report


def main(argv=None):
    parser = argparse.ArgumentParser(description="冻结 L1 检索消融；仅本地编码，不调用聊天模型")
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-root", type=Path, default=ROOT / "experiments/runs")
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--min-score", type=float, default=None)
    args = parser.parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
        load_source(args.source_report, dataset)  # 模型加载前先拒绝无效来源。
        encoder = LocalBGEEncoder(args.model_dir)
        path, report = run_retrieval(args.source_report, dataset, encoder, output_root=args.output_root,
                                     split=args.split, min_score=args.min_score)
        print(f"报告：{path / 'report.json'}")
        for name, result in report["summary"].items():
            print(f"{name}: 完成 {result['completed']}/{result['total']}；充分来源覆盖 {result['evidence_complete']}/{result['answerable_total']}")
        print("只验证检索，不代表回答质量；未知题不以零召回评分。未重跑提取或调用学校模型。")
        return 0 if report["status"] == "completed" else 1
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        print("检索实验配置、快照或来源校验失败；请核对文件与 semantic 可选依赖。未输出数据正文。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
