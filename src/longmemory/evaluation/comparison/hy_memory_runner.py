"""独立命名的逐题副本协议：不放宽既有 strict frozen runner 的摘要检查。"""

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import platform
import shutil
from time import perf_counter
from uuid import uuid4

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.adapters.llm.openai_compatible import SYSTEM_PROMPT
from longmemory.evaluation.runner import provenance
from longmemory.methods.hy_memory.assembly import assemble_hy_backend
from longmemory.methods.hy_memory.settings import load_offline_settings
from longmemory.methods.hy_memory.sdk_bridge import SOURCE_COMMIT
from .dataset import load_dataset
from .hy_memory_preparation import history_payload, changed_files
from .methods import open_method, observe_history, state_digest
from .runner import summarize
from .scoring import score, SCORER_VERSION


PROTOCOL = "hy-closed-source-per-question-clone-qa-v1"


def file_hashes(directory):
    hashes = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError("hy_comparison_links_not_allowed")
        if path.is_file():
            hashes[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _copy_engine(source, target):
    file_hashes(source)  # copytree 前拒绝联接/链接，不跨出合成状态。
    shutil.copytree(source, target)


def run_hy_comparison(dataset, *, output_root, hy_opener, generator_factory=FakeAnswerGenerator,
                      split="dev", context_chars=4000, model_metadata=None, hy_metadata=None):
    """hy_opener(directory, create_engine, create_sources) 返回拥有 close 的 assembly。

    只创建新的运行和题目副本。Hy 题目副本使用新空来源账本，构建账本保留于
    sealed/build；来源覆盖依据 SDK 返回的原历史 event_id，不伪造 query 来源。
    """
    if split not in {"dev", "holdout"} or type(context_chars) is not int or not 1 <= context_chars <= 16000:
        raise ValueError("hy_comparison_options_invalid")
    questions = [question for question in dataset.questions if question.split == split]
    if not questions:
        raise ValueError("hy_comparison_no_questions")
    allowed_metadata = {"provider", "model", "endpoint_sha256", "prompt_sha256", "simulated"}
    model_metadata = model_metadata or {"provider":"fake", "simulated":True}
    if set(model_metadata) - allowed_metadata:
        raise ValueError("hy_answer_metadata_not_public")
    # Hy 元数据只由显式公开配置获得，不接收任意含密钥字典。
    if hy_metadata is not None and set(hy_metadata) - {"settings", "dependency_lock_sha256", "sdk_source"}:
        raise ValueError("hy_metadata_invalid")
    if hy_metadata is not None:
        # 避免嵌套 api_key/base_url 原样泄漏；真实设置由 HySettings.public() 白名单产出。
        def reject_secret(value):
            if isinstance(value, dict):
                if {str(key).lower() for key in value} & {"api_key", "authorization", "token", "password", "base_url"}:
                    raise ValueError("hy_metadata_secret_field")
                for child in value.values(): reject_secret(child)
            elif isinstance(value, list):
                for child in value: reject_secret(child)
        reject_secret(hy_metadata)
    # Windows 传统文件 API 在深工作树上存在 260 字符限制；内部名保持短，
    # 方法全名仍在报告映射，不改全局策略或迁移项目到 ASCII 路径。
    run = Path(output_root) / ("hy-" + uuid4().hex[:16])
    run.mkdir(parents=True, exist_ok=False)
    manifest = {"protocol":PROTOCOL, "started_at":datetime.now(UTC).isoformat(), "code":provenance(),
        "python":platform.python_version(), "dataset":{"name":dataset.name,"version":dataset.version,"sha256":dataset.sha256},
        "split":split, "question_ids":[q.id for q in questions], "context_chars":context_chars,
        "state_layout":{"longmemory_v1":"sealed/b", "hy_memory_pro_chat":"sealed/h", "questions":"q/<b|h>/<index>"},
        "answer_model":model_metadata, "hy":hy_metadata,
        "system_prompt_sha256":hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(), "scorer":SCORER_VERSION,
        "prompt_hash_scope":"shared_answer_prompt_reference; fake_generator_does_not_execute_prompt",
        "limitations":["not_strict_frozen_protocol", "hy_clone_semantic_mutation_not_ruled_out",
            "same_history_different_extraction_retrieval", "sdk_scores_not_comparable", "lexical_proxy_requires_review",
            "fake_or_simulated_models_are_not_quality_evidence", "no_observed_cost_or_external_tokens"]}
    (run / "history.json").write_text(json.dumps(history_payload(dataset), ensure_ascii=False, indent=2), encoding="utf-8")
    names = ("longmemory_v1", "hy_memory_pro_chat")
    rows = [{"method":name,"question_id":q.id,"category":q.category,"query":q.query,"status":"interrupted","error":"not_run"}
            for name in names for q in questions]
    report = {"manifest":manifest,"builds":{},"questions":rows,"status":"running"}
    def checkpoint():
        report["summary"] = summarize(rows)
        temporary = run / "report.tmp"
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(run / "report.json")
    checkpoint()
    for name in names:
        short_name = "h" if name == names[1] else "b"
        build = run / "sealed" / short_name
        build.mkdir(parents=True)
        method = None
        started = perf_counter()
        record = report["builds"][name] = {"status":"failed","observations":[]}
        try:
            assembly = hy_opener(build, create_engine=True, create_sources=True) if name == names[1] else None
            method = assembly.method if assembly else open_method(name, build, frozen=False)
            for event in dataset.history:
                result = method.observe(event) if assembly else observe_history(method, event)
                record["observations"].append(asdict(result))
                checkpoint()
                if result.processing_status != "completed":
                    raise RuntimeError("hy_incomplete_build")
            method.wait_until_ready()
            if assembly:
                record["sdk_diagnostics"] = method.engine.sdk_call("diagnostics")
            method.close()
            method = None
            # 同路径独立重开，不用 recall 写访问状态来证明持久化。
            reopened = hy_opener(build, create_engine=False, create_sources=False) if assembly else None
            method = reopened.method if reopened else open_method(name, build, frozen=True)
            method.wait_until_ready()
            method.close()
            method = None
            fingerprint = state_digest(build)
            record.update(status="completed", persistence="closed_and_reopened_not_quality_measurement", sealed_sha256=fingerprint)
        except Exception as exc:
            record.update(status="failed", error="build_or_reopen_failed", error_type=type(exc).__name__)
            for row in rows:
                if row["method"] == name: row.update(status="failed", error="memory_build_failed")
        finally:
            if method is not None:
                try: method.close()
                except Exception: record["close_error"] = "close_failed"
            record["duration_ms"] = round((perf_counter()-started)*1000,3)
            checkpoint()
        if record["status"] != "completed":
            continue
        contaminated = False
        for index, question in enumerate(questions):
            row = next(row for row in rows if row["method"] == name and row["question_id"] == question.id)
            if contaminated:
                row.update(error="sealed_source_changed", status="interrupted")
                continue
            clone = run / "q" / short_name / str(index)
            clone.mkdir(parents=True)
            method = None
            phase = "clone"
            before = None
            started = perf_counter()
            try:
                if state_digest(build) != fingerprint:
                    raise RuntimeError("sealed_state_changed")
                if name == names[1]:
                    _copy_engine(build / "engine", clone / "engine")
                    before = file_hashes(clone / "engine")
                    method = hy_opener(clone, create_engine=False, create_sources=True).method
                else:
                    _copy_engine(build, clone / "engine")
                    before = file_hashes(clone / "engine")
                    method = open_method(name, clone / "engine", frozen=True)
                phase = "recall"
                support = method.recall(question.query)
                row["support"] = asdict(support)
                row["injected_context"] = support.context[:context_chars]
                row["context_truncated"] = len(support.context) > context_chars
                row["retrieval_ms"] = round((perf_counter()-started)*1000,3)
                if name == names[1]: row["sdk_diagnostics"] = method.engine.sdk_call("diagnostics")
                method.close()
                method = None
                phase = "answer"
                answer = generator_factory().generate(query=question.query, memory_context=row["injected_context"])
                if not isinstance(answer,str) or not answer.strip(): raise ValueError("invalid_answer")
                row.update(answer=answer, **score(question,support,answer), status="completed", error=None)
                row["evidence_metric_scope"] = "full_retrieved_sources_before_context_truncation"
            except Exception as exc:
                row.update(status="failed",error=phase+"_failed",error_type=type(exc).__name__)
            finally:
                if method is not None:
                    try: method.close()
                    except Exception: row.update(status="failed",error="close_failed")
                if before is not None:
                    row["clone_state_audit"] = changed_files(before,file_hashes(clone / "engine"))
                row["sealed_source_unchanged"] = state_digest(build) == fingerprint
                if not row["sealed_source_unchanged"]:
                    contaminated = True
                    row.update(status="failed",error="sealed_state_changed")
                row["duration_ms"] = round((perf_counter()-started)*1000,3)
                checkpoint()
    report["status"] = "completed" if all(row["status"] == "completed" for row in rows) else "completed_with_errors"
    report["finished_at"] = datetime.now(UTC).isoformat()
    checkpoint()
    return run, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--sdk-python", required=True, type=Path)
    parser.add_argument("--output-root", default=Path("experiments/runs"), type=Path)
    args = parser.parse_args(argv)
    settings = load_offline_settings(args.settings)
    lock = args.sdk_python.resolve().parents[2] / "requirements.lock"
    def opener(directory, *, create_engine, create_sources):
        return assemble_hy_backend(settings=settings, state_directory=directory / "engine",
            source_path=directory / "sources.db", create=create_engine, create_sources=create_sources, python=args.sdk_python)
    path, report = run_hy_comparison(load_dataset(args.dataset), output_root=args.output_root,
        hy_opener=opener, hy_metadata={"settings":settings.public(), "sdk_source":SOURCE_COMMIT,
            "dependency_lock_sha256":hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() else None})
    print(json.dumps({"report":str(path / "report.json"), "status":report["status"], "summary":report["summary"]}, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
