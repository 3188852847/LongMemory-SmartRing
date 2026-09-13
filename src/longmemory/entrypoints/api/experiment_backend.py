"""本机实验档案投影与追加式人工复核；不执行实验、不访问个人数据库。"""

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import threading
from uuid import UUID

from longmemory.evaluation.comparison.review import RUBRIC, summarize_review
from longmemory.evaluation.l1_sufficiency_policy_replay import (
    SUPPORTED_SOURCE_PROTOCOLS as L1_REPLAY_SOURCE_PROTOCOLS,
    replay_l1_sufficiency_policy,
)

RUN_ID = re.compile(r"(?:comparison|retrieval|retrieval-answers)-[0-9a-f]{32}\Z")
PROTOCOLS = {"history-replay-frozen-qa-v1": "comparison",
             "frozen-l1-retrieval-ablation-v1": "retrieval",
             "frozen-retrieval-answer-replay-v1": "answers"}
MAX_BYTES = 8 * 1024 * 1024
L1_SOURCE_ID = re.compile(r"l1-sufficiency-(?:rescore-)?[0-9a-f]{32}\Z")
L1_REPLAY_ID = re.compile(r"l1-sufficiency-policy-replay-[0-9a-f]{32}\Z")


class ExperimentError(ValueError):
    def __init__(self, code, status=400):
        self.code, self.status = code, status


def safe_file(root, path):
    """拒绝目录穿越、符号链接和 Windows junction；只允许固定目录后代。"""
    if not path.is_relative_to(root):
        raise ExperimentError("invalid_experiment_path")
    for part in (root, *path.parents, path):
        if part == root or part.is_relative_to(root):
            if part.is_symlink() or part.is_junction():
                raise ExperimentError("linked_experiment_path")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ExperimentError("invalid_experiment_path")
    return path


def read_json(root, path):
    path = safe_file(root, path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ExperimentError("experiment_too_large")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def metadata(manifest):
    if manifest["protocol"] == "frozen-retrieval-answer-replay-v1":
        source = manifest["retrieval_manifest"]["source_manifest"]
    elif manifest["protocol"] == "frozen-l1-retrieval-ablation-v1":
        source = manifest["source_manifest"]
    else:
        source = manifest
    return source


def group_id(row, kind):
    return row["method"] + "/" + row["strategy"] if kind == "retrieval" else row["method"]


class ExperimentBackend:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.runs, self.results = self.root / "runs", self.root / "results"
        self.lock = threading.Lock()

    def _load(self, run_id):
        if not RUN_ID.fullmatch(run_id):
            raise ExperimentError("invalid_run_id")
        report, digest = read_json(self.root, self.runs / run_id / "report.json")
        kind = PROTOCOLS.get(report["manifest"]["protocol"])
        rows = report["questions"]
        if not kind or not isinstance(rows, list) or not rows or len(rows) > 2000:
            raise ExperimentError("unsupported_report")
        keys = [(group_id(r, kind), r["question_id"]) for r in rows]
        if len(keys) != len(set(keys)):
            raise ExperimentError("duplicate_report_rows")
        return report, digest, kind

    def listing(self):
        if not self.runs.exists():
            return {"items": [], "skipped": 0, "limited": False}
        safe_file(self.root, self.runs)
        # 不把整个仓库映射为文件浏览器。只读三种已知协议，损坏文件单独计数。
        candidates = sorted(p.name for p in self.runs.iterdir() if RUN_ID.fullmatch(p.name))
        items, skipped = [], 0
        for name in candidates[:500]:
            try:
                r, digest, kind = self._load(name)
                m, source = r["manifest"], metadata(r["manifest"])
                model = m.get("answer_model", source.get("answer_model", {}))
                items.append({"id": name, "kind": kind, "started_at": m.get("started_at"),
                    "status": r.get("status"), "provider": "local_embedding" if kind == "retrieval" else model.get("provider", "unknown"),
                    "model": m.get("encoder", {}).get("model") if kind == "retrieval" else model.get("model"),
                    "dataset": source.get("dataset", {}).get("name", "unknown"),
                    "split": m.get("split", "unknown"), "total": len(r["questions"]),
                    "completed": sum(x.get("status") == "completed" for x in r["questions"]),
                    "report_sha256": digest})
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                skipped += 1
        items.sort(key=lambda x: (str(x["started_at"] or ""), x["id"]), reverse=True)
        return {"items": items, "skipped": skipped, "limited": len(candidates) > 500}

    def l1_policy_replay_options(self):
        """列出可回放来源和既有结果；不执行模型，也不读个人数据库。"""

        sources, replays, skipped = [], [], 0
        if not self.runs.exists():
            return {"sources": [], "replays": [], "skipped": 0}
        safe_file(self.root, self.runs)
        for path in sorted(self.runs.iterdir()):
            try:
                if L1_SOURCE_ID.fullmatch(path.name):
                    report, digest = read_json(self.root, path / "report.json")
                    manifest = report.get("manifest", {})
                    rows = report.get("rows")
                    if (report.get("status") != "completed"
                            or manifest.get("protocol") not in L1_REPLAY_SOURCE_PROTOCOLS
                            or not isinstance(rows, list) or not rows):
                        raise ValueError("invalid source")
                    sources.append({
                        "id": path.name,
                        "created_at": manifest.get("created_at") or manifest.get("started_at"),
                        "protocol": manifest["protocol"],
                        "dataset": manifest.get("target_dataset_id") or manifest.get("dataset_id"),
                        "total": len(rows),
                        "report_sha256": digest,
                    })
                elif L1_REPLAY_ID.fullmatch(path.name):
                    report, digest = read_json(self.root, path / "report.json")
                    manifest = report.get("manifest", {})
                    summary = report.get("summary")
                    if (manifest.get("protocol") != "l1-sufficiency-policy-replay-v1"
                            or not isinstance(summary, dict)):
                        raise ValueError("invalid replay")
                    replays.append({
                        "id": path.name,
                        "created_at": manifest.get("created_at"),
                        "status": report.get("status"),
                        "source_report_sha256": manifest.get("source_report_sha256"),
                        "report_sha256": digest,
                        "summary": {key: summary.get(key) for key in (
                            "total_cases", "completed_cases", "false_block_cases",
                            "unsupported_pass_cases", "original_candidate_count",
                            "kept_candidate_count", "removed_candidate_count",
                            "candidate_reduction_rate", "context_character_reduction_rate",
                        )},
                    })
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                if L1_SOURCE_ID.fullmatch(path.name) or L1_REPLAY_ID.fullmatch(path.name):
                    skipped += 1
        sources.sort(key=lambda item: str(item["created_at"] or ""), reverse=True)
        replays.sort(key=lambda item: str(item["created_at"] or ""), reverse=True)
        return {"sources": sources[:100], "replays": replays[:100], "skipped": skipped}

    def run_l1_policy_replay(self, body):
        """以持久 request_id 幂等创建本地回放报告；不接收任意路径。"""

        if (not isinstance(body, dict) or set(body) != {"source_id", "request_id"}
                or not isinstance(body["source_id"], str)
                or not L1_SOURCE_ID.fullmatch(body["source_id"])):
            raise ExperimentError("invalid_l1_policy_replay")
        try:
            request_id = UUID(body["request_id"]).hex
        except (ValueError, TypeError, AttributeError):
            raise ExperimentError("invalid_l1_policy_replay") from None
        source_path = safe_file(
            self.root, self.runs / body["source_id"] / "report.json",
        )
        _source, source_digest = read_json(self.root, source_path)
        run_id = "l1-sufficiency-policy-replay-" + request_id
        destination = safe_file(self.root, self.runs / run_id / "report.json")
        with self.lock:
            if destination.exists():
                report, _digest = read_json(self.root, destination)
                if report.get("manifest", {}).get("source_report_sha256") != source_digest:
                    raise ExperimentError("l1_policy_replay_request_conflict", 409)
                return {"id": run_id, "replayed": True, "status": report.get("status"),
                        "summary": report.get("summary")}
            # 重新读取哈希，避免预检和写报告之间来源被替换。
            if read_json(self.root, source_path)[1] != source_digest:
                raise ExperimentError("report_changed", 409)
            try:
                _directory, report = replay_l1_sufficiency_policy(
                    source_path, output_root=self.runs, run_id=run_id,
                )
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                raise ExperimentError("l1_policy_replay_failed") from error
            return {"id": run_id, "replayed": False, "status": report["status"],
                    "summary": report["summary"]}

    def _reviews(self, run_id, digest, report):
        if not self.results.exists():
            return [], 0
        safe_file(self.root, self.results)
        versions, stale = {}, 0
        paths = sorted(self.results.glob(run_id + "*-review.json"))
        if len(paths) > 1000:
            raise ExperimentError("review_limit", 409)
        for path in paths:
            try:
                value, revision = read_json(self.root, path)
                if value.get("report_sha256") != digest:
                    stale += 1
                    continue
                # summarize_review 绑定真实源报告、完整题目和状态，不能将坏附页计分。
                result = summarize_review(self.runs / run_id / "report.json", value)
                key = value["reviewer_kind"], value["reviewer"]
                version = {"reviewer": key[1], "reviewer_kind": key[0], "revision": revision,
                           "created_at": value.get("created_at", ""), "items": value["items"],
                           "summary": result["methods"]}
                if key not in versions or str(version["created_at"]) > str(versions[key]["created_at"]):
                    versions[key] = version
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                stale += 1
        return list(versions.values()), stale

    def detail(self, run_id):
        report, digest, kind = self._load(run_id)
        groups, questions = {}, {}
        for row in report["questions"]:
            group = group_id(row, kind)
            stats = groups.setdefault(group, {"id": group, "total": 0, "completed": 0,
                "answer_pass": 0, "answer_scored": 0, "evidence_pass": 0, "evidence_scored": 0})
            stats["total"] += 1
            completed = row.get("status") == "completed"
            stats["completed"] += completed
            stats["answer_scored"] += completed and type(row.get("answer_proxy_pass")) is bool
            stats["answer_pass"] += completed and row.get("answer_proxy_pass") is True
            stats["evidence_scored"] += completed and type(row.get("evidence_complete")) is bool
            stats["evidence_pass"] += completed and row.get("evidence_complete") is True
            questions.setdefault(row["question_id"], {"id": row["question_id"], "query": row["query"]})
        reviews, stale = self._reviews(run_id, digest, report) if kind != "retrieval" else ([], 0)
        m, source = report["manifest"], metadata(report["manifest"])
        # 元数据白名单投影，不直接将 manifest（可能含配置字段）发送到浏览器。
        return {"id": run_id, "kind": kind, "report_sha256": digest, "status": report.get("status"),
            "started_at": m.get("started_at"), "code_commit": m.get("code", {}).get("commit"),
            "code_dirty": m.get("code", {}).get("dirty"),
            "dataset": {k: source.get("dataset", {}).get(k) for k in ("name", "version", "sha256")},
            "split": m.get("split"), "context_budget": m.get("context_budget"),
            "groups": list(groups.values()), "questions": list(questions.values()),
            "reviews": reviews, "ignored_reviews": stale, "review_enabled": kind != "retrieval"}

    def _history(self, report, run_id):
        kind = PROTOCOLS[report["manifest"]["protocol"]]
        if kind == "comparison":
            parent_id = run_id
        else:
            m = report["manifest"]
            target = (m["retrieval_manifest"] if kind == "answers" else m)["source_report_sha256"]
            parent_id = None
            # 按内容哈希寻找父实验，绝不执行报告携带的任意文件路径。
            for item in self.listing()["items"]:
                if item["kind"] == "comparison" and item["report_sha256"] == target:
                    parent_id = item["id"]
                    break
        if parent_id is None:
            return {}, "父实验缺失或摘要变化，无法核对原始来源。"
        try:
            data, _ = read_json(self.root, self.runs / parent_id / "history.json")
            return {e["event_id"]: {k: e.get(k) for k in ("event_id", "role", "content", "session_id", "occurred_at")}
                    for e in data}, "来源从当前父实验历史读取；不是完整实验完整性重验。"
        except (OSError, ValueError, KeyError, TypeError):
            return {}, "历史文件不可读，来源未核对。"

    def question(self, run_id, question_id):
        report, digest, kind = self._load(run_id)
        selected = [r for r in report["questions"] if r["question_id"] == question_id]
        if not selected:
            raise ExperimentError("question_not_found", 404)
        history, note = self._history(report, run_id)
        rows = []
        fields = ("query", "status", "error", "answer", "answer_proxy_pass", "evidence_complete",
                  "retrieved_evidence_complete", "evidence_metric_scope", "state_unchanged",
                  "context_truncated", "injected_context", "reference_answer", "expected_abstention",
                  "retrieval_ms", "answer_ms", "first_sufficient_rank")
        for row in selected:
            value = {k: row.get(k) for k in fields}
            value["group"] = group_id(row, kind)
            support = row.get("support") or {}
            value["context"] = support.get("context")
            value["retrieved"] = [{"item_id": i.get("item_id"), "content": i.get("content"),
                                   "source_event_ids": i.get("source_event_ids")}
                                  for i in support.get("retrieved") or []]
            ids = {sid for i in value["retrieved"] for sid in i["source_event_ids"] or []}
            value["sources"] = [history.get(sid, {"event_id": sid, "content": "来源不可用", "role": "unknown"}) for sid in sorted(ids)]
            rows.append(value)
        return {"report_sha256": digest, "question_id": question_id, "rows": rows, "source_note": note}

    def save_review(self, run_id, body):
        fields = {"report_sha256", "reviewer", "revision", "method", "question_id", "verdict", "rationale", "request_id"}
        if not isinstance(body, dict) or set(body) != fields:
            raise ExperimentError("invalid_review")
        if any(not isinstance(body[k], str) for k in fields - {"revision"}):
            raise ExperimentError("invalid_review")
        if (not 1 <= len(body["reviewer"].strip()) <= 60 or len(body["rationale"]) > 1000
                or body["verdict"] not in {"pending", "pass", "fail", "unscorable"}
                or (body["verdict"] != "pending" and not body["rationale"].strip())
                or str(UUID(body["request_id"])) != body["request_id"]):
            raise ExperimentError("invalid_review")
        with self.lock:
            report, digest, kind = self._load(run_id)
            if kind == "retrieval":
                raise ExperimentError("answers_required")
            if digest != body["report_sha256"]:
                raise ExperimentError("report_changed", 409)
            path = self.results / (run_id + "-" + body["request_id"] + "-review.json")
            safe_file(self.root, path)
            if path.exists():
                saved, revision = read_json(self.root, path)
                if saved.get("console_request") != body:
                    raise ExperimentError("request_conflict", 409)
                return {"saved": True, "revision": revision, "replayed": True}
            versions, _ = self._reviews(run_id, digest, report)
            old = next((v for v in versions if v["reviewer_kind"] == "human" and v["reviewer"] == body["reviewer"]), None)
            if body["revision"] != (old["revision"] if old else None):
                raise ExperimentError("review_changed", 409)
            items = ([dict(i) for i in old["items"]] if old else [
                {"method": r["method"], "question_id": r["question_id"], "verdict": "pending", "rationale": ""}
                for r in report["questions"]])
            item = next((i for i in items if (i["method"], i["question_id"]) == (body["method"], body["question_id"])), None)
            if item is None:
                raise ExperimentError("question_not_found", 404)
            item.update(verdict=body["verdict"], rationale=body["rationale"])
            value = {"schema_version": 1, "rubric": RUBRIC, "report_sha256": digest,
                "reviewer": body["reviewer"], "reviewer_kind": "human",
                "created_at": datetime.now(UTC).isoformat(), "items": items,
                "scope": "目标事实与信息不足处理；用户自报复核者，不是独立盲评或身份认证。",
                "console_request": body}
            summarize_review(self.runs / run_id / "report.json", value)
            if self._load(run_id)[1] != digest:
                raise ExperimentError("report_changed", 409)
            safe_file(self.root, self.results).mkdir(parents=True, exist_ok=True)
            raw = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
            # 排他创建、保留旧版本。保存失败可能已产生文件，不自动重复写入。
            with path.open("xb") as stream:
                stream.write(raw)
            return {"saved": True, "revision": hashlib.sha256(raw).hexdigest(), "replayed": False}
