"""最小跨方法实验：历史只回放，问题独立，状态冻结，失败逐题保留。"""

import argparse
from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
from time import perf_counter
from uuid import uuid4

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.adapters.llm.openai_compatible import OpenAICompatibleAnswerGenerator, SYSTEM_PROMPT
from longmemory.adapters.llm.candidate_extractor import OpenAICompatibleCandidateProducer, PROMPT_VERSION, PROMPT_SHA256
from longmemory.evaluation.runner import provenance
from longmemory.infrastructure.config.settings import load_model_settings
from longmemory.methods.dialogue_chunks.method import event_json
from .dataset import load_dataset
from .methods import METHODS, REGISTERED_METHODS, METHOD_NAME, observe_history, open_method, state_digest
from .scoring import SCORER_VERSION, score, score_evidence

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATASET = ROOT / "datasets/synthetic/method_comparison_v1.json"
PROTOCOL = "history-replay-frozen-qa-v1"


def now():
    return datetime.now(UTC).isoformat()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def summarize(rows):
    summaries = {}
    for name in dict.fromkeys(row["method"] for row in rows):
        subset = [row for row in rows if row["method"] == name]
        completed = [row for row in subset if row["status"] == "completed"]
        evidence = [row for row in subset if row.get("evidence_complete") is not None]
        summaries[name] = {
            "total": len(subset), "completed": len(completed),
            "failed": sum(row["status"] == "failed" for row in subset),
            "interrupted": sum(row["status"] == "interrupted" for row in subset),
            "answer_proxy_pass": sum(row.get("answer_proxy_pass", False) for row in completed),
            "answer_denominator_all_questions": len(subset),
            "evidence_complete": sum(row["evidence_complete"] for row in evidence),
            "evidence_evaluable_questions": len(evidence),
        }
    return summaries


def run_comparison(dataset, generator_factory, *, output_root, model_config,
                   methods=METHODS, split="dev", context_chars=4000,
                   candidate_producer_factory=None, extraction_config=None):
    """只创建全新运行目录；没有接收既有状态/日常数据库的参数。

    generator_factory 每题创建无历史回答器；模型只接收当前问题和方法
    产生的截断后上下文，不接收参考答案、评分来源标签或之前的回答。
    """
    if not methods or len(set(methods)) != len(methods) or any(name not in REGISTERED_METHODS for name in methods):
        raise ValueError("方法必须是互不重复的已注册名称。")
    if split not in {"dev", "holdout"} or type(context_chars) is not int or not 1 <= context_chars <= 16000:
        raise ValueError("无效的划分或上下文预算。")
    questions = [q for q in dataset.questions if q.split == split]
    if not questions:
        raise ValueError("所选划分没有问题。")
    # 模型元数据白名单；禁止把 ModelSettings.asdict() 中的 Key 写进报告。
    allowed = {"provider", "model", "timeout_seconds", "max_tokens", "sampling", "usage_tokens", "endpoint_sha256"}
    if set(model_config) - allowed:
        raise ValueError("模型元数据包含未允许的字段。")
    if METHOD_NAME in methods:
        if candidate_producer_factory is None or not extraction_config or set(extraction_config) - allowed:
            raise ValueError("新提取方法需要显式生成器及无密钥的模型元数据。")
    elif candidate_producer_factory is not None or extraction_config is not None:
        raise ValueError("未选择新方法时不接受提取配置。")
    run_dir = output_root / ("comparison-" + uuid4().hex)
    run_dir.mkdir(parents=True, exist_ok=False)
    history = [event_json(event) for event in dataset.history]
    write_json(run_dir / "history.json", history)
    manifest = {
        "protocol": PROTOCOL, "started_at": now(), "dataset": {"name": dataset.name, "version": dataset.version, "sha256": dataset.sha256},
        "code": provenance(), "runtime": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version},
        "split": split, "question_order": [q.id for q in questions], "method_order": list(methods),
        "answer_model": model_config, "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "scorer": SCORER_VERSION, "context_budget": {"unit": "unicode_characters", "maximum": context_chars},
        "method_settings": {"longmemory_v1": {"algorithm_version": "1", "retrieval_limit": 5, "session_handling": "preserved_in_platform_ledger_not_used_by_algorithm"},
                            "dialogue_chunks_v1": {"algorithm_version": "1", "chunk_messages": 2, "cross_session_chunks": False, "retrieval_limit": 5}},
        "limitations": ["synthetic_development_not_paper_benchmark", "lexical_answer_proxy_requires_review",
                        "character_budget_not_token_budget", "fake_answers_not_quality_measurement",
                        "single_run_no_statistical_significance", "shared_history_holdout_not_blind_external_test",
                        "no_token_cost_measurement", "original_methods_ignore_or_use_session_metadata_differently"],
    }
    if METHOD_NAME in methods:
        manifest["method_settings"][METHOD_NAME] = {
            "algorithm_version": "2", "retrieval_limit": 5, "retrieval": "unchanged_v1_keyword",
            "session_handling": "preserved_in_platform_ledger_not_used_by_algorithm",
            "extraction_model": extraction_config,
            # 离线工厂替身没有执行模型提示，不能给它虚构提示执行记录。
            "prompt_version": PROMPT_VERSION if extraction_config.get("provider") == "openai_compatible" else None,
            "prompt_sha256": PROMPT_SHA256 if extraction_config.get("provider") == "openai_compatible" else None,
            "candidate_schema": 1,
            "question_filter": "unchanged_v1_heuristic", "subject_scope": "user:self",
        }
        manifest["limitations"].extend(["quote_presence_not_semantic_entailment",
                                        "extraction_adds_build_requests", "single_message_extraction_no_coreference"])
    write_json(run_dir / "manifest.json", manifest)
    # 预先列出全部题，意外中断不能让未完成的样例从分母里消失。
    rows = [{"method": name, "question_id": q.id, "category": q.category,
             "query": q.query, "status": "interrupted", "error": "not_run"}
            for name in methods for q in questions]
    builds, interrupted = {}, False
    report = {"manifest": manifest, "builds": builds, "questions": rows, "status": "running"}
    with (run_dir / "report.json").open("x+", encoding="utf-8") as stream:
        def checkpoint():
            report["summary"] = summarize(rows)
            stream.seek(0)
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.truncate()
            stream.flush()
        checkpoint()
        try:
            for name in methods:
                directory = run_dir / name
                directory.mkdir()
                method, build_start = None, perf_counter()
                builds[name] = {"status": "running", "observations": []}
                try:
                    if name == METHOD_NAME:
                        method = open_method(name, directory, frozen=False, producer=candidate_producer_factory())
                    else:
                        method = open_method(name, directory, frozen=False)
                    for event in dataset.history:
                        observation = observe_history(method, event)
                        builds[name]["observations"].append(asdict(observation))
                        if name == METHOD_NAME:
                            builds[name]["extraction"] = method.build_diagnostics()
                        checkpoint()
                    method.wait_until_ready()
                    method.close()
                    method = None
                    fingerprint = state_digest(directory)
                    builds[name].update(status="completed", state_sha256=fingerprint,
                                        duration_ms=round((perf_counter() - build_start) * 1000, 3))
                except Exception:
                    builds[name].update(status="failed", error="memory_build_failed")
                    for row in rows:
                        if row["method"] == name:
                            row.update(status="failed", error="memory_build_failed")
                    checkpoint()
                    continue
                finally:
                    builds[name]["duration_ms"] = round((perf_counter() - build_start) * 1000, 3)
                    if method is not None:
                        if name == METHOD_NAME:
                            builds[name]["extraction"] = method.build_diagnostics()
                        method.close()
                    checkpoint()
                checkpoint()
                contaminated = False
                for question in questions:
                    row = next(r for r in rows if r["method"] == name and r["question_id"] == question.id)
                    if contaminated:
                        row.update(status="interrupted", error="previous_freeze_violation")
                        checkpoint()
                        continue
                    started, method = perf_counter(), None
                    row.update(started_at=now(), status="failed", error=None)
                    phase = "memory_recall"
                    try:
                        before = state_digest(directory)
                        if before != fingerprint:
                            raise RuntimeError("state changed before query")
                        # 每题重开方法，丢弃方法内临时状态；磁盘状态禁止更新。
                        method = open_method(name, directory, frozen=True)
                        support = method.recall(question.query)
                        method.close()
                        method = None
                        row.update(retrieval_ms=round((perf_counter() - started) * 1000, 3),
                                   support=asdict(support), injected_context=support.context[:context_chars],
                                   context_truncated=len(support.context) > context_chars)
                        row.update(score_evidence(question, support))
                        row["evidence_metric_scope"] = "full_retrieved_sources_before_context_truncation"
                        if state_digest(directory) != fingerprint:
                            raise RuntimeError("state changed during query")
                        phase = "answer"
                        model_start = perf_counter()
                        generator = generator_factory()
                        answer = generator.generate(query=question.query, memory_context=row["injected_context"])
                        if not isinstance(answer, str) or not answer.strip():
                            raise ValueError("invalid answer")
                        row.update(answer=answer, answer_ms=round((perf_counter() - model_start) * 1000, 3))
                        phase = "scoring"
                        row.update(score(question, support, answer))
                        row.update(status="completed", expected_abstention=question.abstain,
                                   reference_answer=question.answer_contains, evidence_sets=question.evidence_sets)
                    except KeyboardInterrupt:
                        row.update(status="interrupted", error="user_interrupted")
                        raise
                    except Exception:
                        row.update(status="failed", error=phase + "_failed")
                    finally:
                        if method is not None:
                            method.close()
                        after = state_digest(directory)
                        row.update(state_unchanged=after == fingerprint, state_sha256_after=after,
                                   duration_ms=round((perf_counter() - started) * 1000, 3))
                        if after != fingerprint:
                            contaminated = True
                            row.update(status="failed", error="frozen_state_changed")
                        checkpoint()
        except KeyboardInterrupt:
            interrupted = True
        finally:
            if interrupted:
                for build in builds.values():
                    if build["status"] == "running":
                        build.update(status="interrupted", error="user_interrupted")
            report.update(status="interrupted" if interrupted else
                          ("completed" if all(r["status"] == "completed" for r in rows) else "completed_with_errors"),
                          finished_at=now())
            checkpoint()
    return run_dir, report


def main(argv=None):
    parser = argparse.ArgumentParser(description="历史回放/冻结问答；默认离线合成开发集，不读日常库")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-root", type=Path, default=ROOT / "experiments/runs")
    parser.add_argument("--provider", choices=("fake", "openai_compatible"), default="fake")
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--context-chars", type=int, default=4000)
    parser.add_argument("--include-llm-extraction", action="store_true",
                        help="显式新增 D1 条件；构建阶段额外调用模型，不替换旧两组")
    parser.add_argument("--extraction-max-tokens", type=int, default=1024)
    args = parser.parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
        settings = load_model_settings(provider=args.provider)
        if args.include_llm_extraction and settings.provider != "openai_compatible":
            raise ValueError("CLI 的新提取条件要求真实兼容模型；离线替身只用于测试，不冒充语义提取。")
        if settings.provider == "openai_compatible" and settings.allow_http:
            print("警告：HTTP 将明文发送凭据与合成问题/记忆；仅在已确认风险的校园网运行。")
        factory = FakeAnswerGenerator if settings.provider == "fake" else lambda: OpenAICompatibleAnswerGenerator(settings)
        config = {"provider": settings.provider, "model": settings.model or "fake",
                  "timeout_seconds": settings.timeout_seconds, "max_tokens": settings.max_tokens,
                  "sampling": "provider_default_unverified", "usage_tokens": None,
                  "endpoint_sha256": hashlib.sha256(settings.base_url.encode()).hexdigest()}
        options = {}
        if args.include_llm_extraction:
            extraction_settings = replace(settings, max_tokens=args.extraction_max_tokens)
            options = {"methods": REGISTERED_METHODS,
                       "candidate_producer_factory": lambda: OpenAICompatibleCandidateProducer(extraction_settings),
                       "extraction_config": {**config, "max_tokens": extraction_settings.max_tokens}}
            print(f"本次新增 D1 提取条件：最多 {sum(e.role == 'user' for e in dataset.history)} 次额外提取请求；"
                  f"三组最多 {3 * sum(q.split == args.split for q in dataset.questions)} 次回答请求，失败不重试。")
        path, report = run_comparison(dataset, factory, output_root=args.output_root, model_config=config,
                                      split=args.split, context_chars=args.context_chars, **options)
        print(f"报告：{path / 'report.json'}")
        for name, result in report["summary"].items():
            print(f"{name}: 完成 {result['completed']}/{result['total']}；答案词面初筛 {result['answer_proxy_pass']}/{result['total']}")
        if METHOD_NAME in report.get("builds", {}):
            build = report["builds"][METHOD_NAME]
            print(f"D1 构建：{build['status']}；提取请求尝试 {build.get('extraction', {}).get('request_attempts', 0)} 次。")
        if settings.provider == "fake":
            print("本次使用 Fake，仅验证工程流程。")
        else:
            print("本次使用 openai_compatible；具体模型配置见报告 manifest.answer_model。")
        print("词面初筛不是语义质量结论。留出题仅在 --split holdout 时运行。")
        return 0 if report["status"] == "completed" else 1
    except (OSError, ValueError, KeyError, TypeError):
        print("比较配置或文件无效；未输出密钥/数据正文。请检查数据格式和新输出目录权限。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
