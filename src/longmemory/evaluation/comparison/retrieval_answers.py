"""重放已冻结的检索结果，单独测回答；不提取、不编码、不写旧状态。

这不是任意 JSON 的回答工具：输入必须追溯到同一合成数据集、原方法库
及检索索引。来源标签只用于事后评价，不交给回答器。
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from longmemory.core.memory.retrieval.vector import ExactVectorIndex, fingerprint
from longmemory.methods.contracts import MemorySupport, RetrievedTrace
from . import retrieval
from .runner import (DEFAULT_DATASET, ROOT, FakeAnswerGenerator,
                     OpenAICompatibleAnswerGenerator, SYSTEM_PROMPT, load_dataset,
                     load_model_settings, now, provenance, summarize, write_json)
from .methods import open_method, state_digest
from .scoring import SCORER_VERSION, score, score_evidence

PROTOCOL = "frozen-retrieval-answer-replay-v1"
HEADER = "以下是与当前问题相关的长期记忆：\n"
MODEL_FIELDS = {"provider", "model", "timeout_seconds", "max_tokens", "sampling",
                "usage_tokens", "endpoint_sha256"}


def render(items):
    return HEADER + "\n".join("- " + i.content for i in items) if items else ""


def budget_support(support, maximum):
    """按排名保留完整前缀条目，不切半句话，不跳过长条目选择后面的短条目。

    同一个字符上限不代表相同 token 数；保留实际注入项用于单独评证据。
    """
    selected = []
    for item in support.retrieved:
        if len(render(selected + [item])) > maximum:
            break
        selected.append(item)
    return MemorySupport(support.call_id, render(selected), tuple(selected))


def answer_summary(rows):
    result = summarize(rows)
    for name, metrics in result.items():
        group = [r for r in rows if r["method"] == name]
        # 冻结违规后即使收到答案也不算有效证据；失败题仍保留固定分母。
        metrics["evidence_complete"] = sum(r["status"] == "completed"
            and r.get("evidence_complete") is True for r in group)
        metrics["evidence_evaluable_questions"] = sum(r["status"] == "completed"
            and r.get("evidence_complete") is not None for r in group)
        metrics["answerable_denominator_all_questions"] = sum(not r["expected_abstention"] for r in group)
    return result


def validate_inputs(retrieval_path, source_path, dataset):
    source, source_hash, names = retrieval.load_source(source_path, dataset)
    raw = retrieval_path.read_bytes()
    report = json.loads(raw)
    manifest = report["manifest"]
    if (report["status"] != "completed" or manifest["protocol"] != retrieval.PROTOCOL_VERSION
            or manifest["source_report_sha256"] != source_hash
            or manifest["source_manifest"] != source["manifest"]
            or manifest["split"] not in {"dev", "holdout"}
            or manifest["limit"] != 5
            or manifest["strategies"] != ["original_keyword", "dense_cosine"]
            or fingerprint(manifest["encoder"]) != manifest["encoder_id"]
            or json.loads((retrieval_path.parent / "manifest.json").read_text(encoding="utf-8")) != manifest):
        raise ValueError("检索报告身份或来源不匹配。")
    threshold = manifest["min_score"]
    if threshold is not None and (type(threshold) not in (int, float)
                                 or not math.isfinite(threshold) or not -1 <= threshold <= 1):
        raise ValueError("检索阈值无效。")
    questions = [q for q in dataset.questions if q.split == manifest["split"]]
    expected = {(name, strategy, q.id) for name in names
                for strategy in manifest["strategies"] for q in questions}
    rows = report["questions"]
    keys = [(r["method"], r["strategy"], r["question_id"]) for r in rows]
    if len(keys) != len(expected) or set(keys) != expected:
        raise ValueError("检索题目缺失或重复。")
    supports = {}
    for name in names:
        build = report["builds"][name]
        path = retrieval_path.parent / (name + "-vectors.json")
        if (build["status"] != "completed"
                or build["source_state_sha256"] != source["builds"][name]["state_sha256"]
                or hashlib.sha256(path.read_bytes()).hexdigest() != build["index_sha256"]):
            raise ValueError("索引或原库身份变化。")
        index = ExactVectorIndex.load(path, encoder_id=manifest["encoder_id"])
        docs = retrieval.read_corpus(name, source_path.parent / name,
                                    {e.event_id for e in dataset.history if e.role == "user"})
        if (tuple(index.documents) != docs or len(docs) != build["document_count"]
                or fingerprint([asdict(d) for d in docs]) != build["corpus_sha256"]):
            raise ValueError("索引语料与原库不一致。")
        by_id = {d.item_id: d for d in docs}
        method = open_method(name, source_path.parent / name, frozen=True)
        try:
            for q in questions:
                for strategy in manifest["strategies"]:
                    key = name, strategy, q.id
                    row = rows[keys.index(key)]
                    if (row["status"] != "completed" or row["state_unchanged"] is not True
                            or row["query"] != q.query or row["expected_abstention"] != q.abstain):
                        raise ValueError("查询未完成或不匹配。")
                    data = row["support"]
                    items = tuple(RetrievedTrace(i["item_id"], i["content"], tuple(i["source_event_ids"]))
                                  for i in data["retrieved"])
                    if len(items) > 5 or len({i.item_id for i in items}) != len(items):
                        raise ValueError("召回条目数量无效。")
                    for item in items:
                        doc = by_id[item.item_id]
                        if (item.content, item.source_event_ids) != (doc.content, doc.source_event_ids):
                            raise ValueError("召回正文或来源被修改。")
                    if strategy == "original_keyword":
                        old = method.recall(q.query)
                        if items != old.retrieved or data["context"] != old.context:
                            raise ValueError("关键词结果与原方法不同。")
                    else:
                        scores = row["scores"]
                        if (len(scores) != len(items) or any(type(s) not in (int, float)
                                or not math.isfinite(s) or not -1 <= s <= 1 for s in scores)
                                or scores != sorted(scores, reverse=True)
                                or (threshold is not None and any(s < threshold for s in scores))):
                            raise ValueError("向量排名记录无效。")
                    if data["context"] != render(items):
                        raise ValueError("上下文不是来源绑定的完整条目。")
                    supports[key] = MemorySupport(data["call_id"], data["context"], items)
        finally:
            method.close()
    return report, hashlib.sha256(raw).hexdigest(), names, questions, supports


def run_answers(retrieval_path, source_path, dataset, generator_factory, *, output_root,
                model_config, context_chars=4000):
    if (type(context_chars) is not int or not 1 <= context_chars <= 16000
            or not model_config or set(model_config) - MODEL_FIELDS):
        raise ValueError("预算或模型元数据无效。")
    retrieval_path, source_path, output_root = (p.resolve() for p in (retrieval_path, source_path, output_root))
    if any(output_root.is_relative_to(p.parent) for p in (retrieval_path, source_path)):
        raise ValueError("新结果不能写入旧实验目录。")
    # 整体摘要同时保护报告、索引、原数据库与 manifest；错误正文不披露。
    roots = (source_path.parent, retrieval_path.parent)
    digests = tuple(state_digest(p) for p in roots)
    parent, parent_hash, names, questions, supports = validate_inputs(retrieval_path, source_path, dataset)

    def unchanged():
        try:
            return tuple(state_digest(p) for p in roots) == digests
        except (OSError, ValueError):
            return False

    if not unchanged():
        raise ValueError("准备期间冻结来源发生变化。")
    groups = [(n, s) for n in names for s in parent["manifest"]["strategies"]]
    # 每题轮换组顺序，减轻所有向量组总在同一时段运行的偏差；仍非随机盲评。
    ordered = [(q, group) for i, q in enumerate(questions)
               for group in groups[i % len(groups):] + groups[:i % len(groups)]]
    print(f"已校验 {len(groups)} 组 × {len(questions)} 题；最多 {len(ordered)} 次回答尝试，不重试、不提取、不编码。")
    rows = [{"method": n + "/" + s, "source_method": n, "strategy": s,
             "question_id": q.id, "query": q.query, "category": q.category,
             "expected_abstention": q.abstain, "status": "interrupted", "error": "not_run"}
            for q, (n, s) in ordered]
    directory = output_root / ("retrieval-answers-" + uuid4().hex)
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {"protocol": PROTOCOL, "started_at": now(), "code": provenance(),
                "retrieval_report_sha256": parent_hash, "retrieval_manifest": parent["manifest"],
                "frozen_directory_sha256": list(digests), "answer_model": model_config,
                "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
                "scorer": SCORER_VERSION, "split": parent["manifest"]["split"],
                "context_budget": {"unit": "unicode_characters", "maximum": context_chars,
                                   "policy": "whole_item_ranked_prefix_including_header"},
                "execution_order": [[r["method"], r["question_id"]] for r in rows],
                "answer_request_limit": len(rows), "new_extraction_requests": 0,
                "new_embedding_requests": 0,
                "limitations": ["cached_ranking_not_reencoded_or_cryptographically_authenticated",
                    "character_cap_not_equal_token_length", "tiny_dev_corpus_top5_near_full_recall",
                    "lexical_proxy_requires_review", "single_run_no_statistical_significance",
                    "rotating_order_not_randomized", "provider_sampling_defaults_unverified",
                    "fake_is_engineering_only", "no_token_usage_measurement"]}
    write_json(directory / "manifest.json", manifest)
    report = {"manifest": manifest, "questions": rows, "status": "running", "answer_attempts": 0}
    with (directory / "report.json").open("x+", encoding="utf-8") as stream:
        def checkpoint():
            report["summary"] = answer_summary(rows)
            stream.seek(0)
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.truncate()
            stream.flush()
        checkpoint()
        try:
            for row, (q, (n, s)) in zip(rows, ordered):
                if not unchanged():
                    row.update(status="failed", error="frozen_source_changed", state_unchanged=False)
                    break
                full = supports[n, s, q.id]
                injected = budget_support(full, context_chars)
                row.update(support=asdict(full), injected_support=asdict(injected),
                           injected_context=injected.context, context_truncated=injected.context != full.context,
                           retrieved_evidence_complete=score_evidence(q, full)["evidence_complete"],
                           evidence_metric_scope="injected_whole_items", started_at=now())
                started = perf_counter()
                try:
                    generator = generator_factory()
                    report["answer_attempts"] += 1
                    checkpoint()  # 发出调用前记尝试，失败和中断不能隐去成本。
                    answer = generator.generate(query=q.query, memory_context=injected.context)
                    if not isinstance(answer, str) or not answer.strip():
                        raise ValueError("empty answer")
                    row.update(answer=answer, **score(q, injected, answer), status="completed", error=None,
                               reference_answer=q.answer_contains, evidence_sets=q.evidence_sets)
                except KeyboardInterrupt:
                    row.update(status="interrupted", error="user_interrupted")
                    raise
                except Exception:
                    row.update(status="failed", error="answer_failed")
                finally:
                    row.update(answer_ms=round((perf_counter() - started) * 1000, 3), state_unchanged=unchanged())
                    if not row["state_unchanged"]:
                        row.update(status="failed", error="frozen_source_changed")
                    checkpoint()
                if not row["state_unchanged"]:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            report.update(status="completed" if all(r["status"] == "completed" for r in rows) else "incomplete",
                          finished_at=now())
            checkpoint()
    return directory, report


def main(argv=None):
    parser = argparse.ArgumentParser(description="重放冻结检索结果的回答对比；不重新提取或编码")
    parser.add_argument("--retrieval-report", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-root", type=Path, default=ROOT / "experiments/runs")
    parser.add_argument("--provider", choices=("fake", "openai_compatible"), default="fake")
    parser.add_argument("--context-chars", type=int, default=4000)
    args = parser.parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
        settings = load_model_settings(provider=args.provider)
        if settings.provider == "openai_compatible" and settings.allow_http:
            print("警告：HTTP 会明文传输凭据与合成问题/记忆；仅在确认风险的校园网运行。")
        factory = FakeAnswerGenerator if settings.provider == "fake" else lambda: OpenAICompatibleAnswerGenerator(settings)
        config = {"provider": settings.provider, "model": settings.model or "fake",
                  "timeout_seconds": settings.timeout_seconds, "max_tokens": settings.max_tokens,
                  "sampling": "provider_default_unverified", "usage_tokens": None,
                  "endpoint_sha256": hashlib.sha256(settings.base_url.encode()).hexdigest()}
        path, report = run_answers(args.retrieval_report, args.source_report, dataset, factory,
                                  output_root=args.output_root, model_config=config, context_chars=args.context_chars)
        print(f"报告：{path / 'report.json'}")
        for group, result in report["summary"].items():
            print(f"{group}: 完成 {result['completed']}/{result['total']}；答案词面初筛 {result['answer_proxy_pass']}/{result['total']}")
        print(f"回答尝试：{report['answer_attempts']}；provider={settings.provider}。Fake 仅验证工程，词面初筛不是语义结论。")
        return 0 if report["status"] == "completed" else 1
    except (OSError, ValueError, KeyError, TypeError):
        print("来源、配置或输出目录校验失败；未输出数据正文或密钥。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
