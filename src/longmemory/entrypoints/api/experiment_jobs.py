"""固定实验的本机作业入口：先预检、再明确确认；绝不接收命令或任意路径。

作业台账与报告分离。跨控制台进程用操作系统文件锁串行化模型请求，
刷新只读台账；进程中断后不续跑、不重试，避免重复成本和不可比的实验。
"""
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from uuid import UUID, uuid4
from urllib.parse import urlsplit

from longmemory.evaluation.comparison import retrieval_answers as qa
from longmemory.evaluation.comparison.methods import state_digest
from longmemory.infrastructure.config.settings import load_model_settings
from .experiment_backend import ExperimentError, read_json, safe_file

JOB_ID = re.compile(r"[0-9a-f]{32}\Z")
ACTIVE = {"queued", "running", "stopping"}


class RunLease:
    """非阻塞 OS 文件锁；进程退出自动释放，不凭旧 PID 杀进程。"""
    def __init__(self, path):
        self.stream = path.open("a+b")
        self.stream.seek(0, 2)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise ExperimentError("experiment_busy", 409) from None

    def close(self):
        if self.stream.closed:
            return
        if os.name == "nt":
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        self.stream.close()


class ExperimentJobs:
    def __init__(self, backend, *, enabled=False, settings=None, dataset_path=qa.DEFAULT_DATASET):
        self.backend, self.enabled = backend, enabled
        self.root, self.directory = backend.root, backend.root / "jobs"
        self.dataset_path = Path(dataset_path)
        self.settings = settings
        self.lock = threading.RLock()
        self.quotes = OrderedDict()
        self.stop_event = threading.Event()
        self.thread = None
        self.active_id = None
        self.closed = False

    def _lease(self):
        safe_file(self.root, self.directory).mkdir(parents=True, exist_ok=True)
        return RunLease(safe_file(self.root, self.directory / "execution.lock"))

    def _path(self, job_id):
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            raise ExperimentError("invalid_job_id")
        return safe_file(self.root, self.directory / (job_id + ".json"))

    def _save(self, job):
        # 只替换本作业的小台账，不覆盖原实验或用户复核；读者不会读到半个 JSON。
        path = self._path(job["id"])
        temporary = safe_file(self.root, path.with_suffix(".tmp"))
        temporary.write_text(json.dumps(job, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        os.replace(temporary, path)

    def _records(self):
        if not self.directory.exists():
            return []
        safe_file(self.root, self.directory)
        paths = sorted(self.directory.glob("*.json"))
        if len(paths) > 1000:
            raise ExperimentError("job_limit", 409)
        # 台账损坏时失败关闭，而不是忽略它、再次发送请求。
        return [read_json(self.root, self._path(p.stem))[0] for p in paths]

    def _recover(self):
        records = self._records()
        if not any(j["status"] in ACTIVE for j in records):
            return records
        try:
            lease = self._lease()
        except ExperimentError as error:
            if error.code == "experiment_busy":
                return records
            raise
        try:
            # 取得全局锁说明没有执行中的工作者；绝不自动重发未完成题。
            for job in records:
                if job["status"] in ACTIVE:
                    job.update(status="interrupted", error="service_interrupted", finished_at=qa.now())
                    self._save(job)
        finally:
            lease.close()
        return records

    def options(self):
        items = self.backend.listing()["items"]
        return {"enabled": self.enabled and not self.closed,
            "real_available": self.settings is not None,
            "real_model": self.settings.model if self.settings else None,
            "retrievals": [r for r in items if r["kind"] == "retrieval"
                           and r["status"] == "completed" and r["split"] == "dev"],
            "context_default": 4000, "context_max": 16000}

    def listing(self):
        with self.lock:
            records = self._recover()
            return {"items": sorted(records, key=lambda j: j["created_at"], reverse=True)[:20]}

    def _inputs(self, retrieval_id):
        report, digest, kind = self.backend._load(retrieval_id)
        if kind != "retrieval" or report["manifest"]["split"] != "dev":
            raise ExperimentError("dev_retrieval_required")
        expected = report["manifest"]["source_report_sha256"]
        matches = [r["id"] for r in self.backend.listing()["items"]
                   if r["kind"] == "comparison" and r["report_sha256"] == expected]
        if len(matches) != 1:
            raise ExperimentError("source_not_unique")
        source = self.backend.runs / matches[0] / "report.json"
        cached = self.backend.runs / retrieval_id / "report.json"
        # runner 会读库和索引；不能只检查两个 report 文件而放过目录链接。
        count = size = 0
        for root in (source.parent, cached.parent):
            for folder, dirs, files in os.walk(root, followlinks=False):
                for name in dirs + files:
                    path = safe_file(self.root, Path(folder) / name)
                    count += 1
                    if path.is_file():
                        size += path.stat().st_size
                    if count > 1000 or size > 256 * 1024 * 1024:
                        raise ExperimentError("experiment_too_large")
        dataset = qa.load_dataset(self.dataset_path)
        _, verified, names, questions, _ = qa.validate_inputs(cached, source, dataset)
        if digest != verified:
            raise ExperimentError("report_changed", 409)
        total = len(names) * 2 * len(questions)
        if not 1 <= total <= 64:
            raise ExperimentError("request_limit_exceeded")
        return cached, source, dataset, {"retrieval_id": retrieval_id, "source_id": matches[0],
            "retrieval_sha256": digest, "source_sha256": expected,
            "frozen_sha256": [state_digest(source.parent), state_digest(cached.parent)],
            "dataset_sha256": hashlib.sha256(self.dataset_path.read_bytes()).hexdigest(),
            "groups": [n + "/" + s for n in names for s in ("original_keyword", "dense_cosine")],
            "question_count": len(questions), "total": total}

    def prepare(self, body, owner):
        with self.lock:
            if not self.enabled or self.closed:
                raise ExperimentError("experiment_runs_disabled", 403)
            if (not isinstance(body, dict) or set(body) != {"retrieval_id", "provider", "context_chars"}
                    or body["provider"] not in {"fake", "openai_compatible"}
                    or not isinstance(body["retrieval_id"], str)
                    or type(body["context_chars"]) is not int or not 1 <= body["context_chars"] <= 16000):
                raise ExperimentError("invalid_job_request")
            settings = load_model_settings({}, provider="fake") if body["provider"] == "fake" else self.settings
            if settings is None:
                raise ExperimentError("model_not_configured", 409)
            _, _, _, inputs = self._inputs(body["retrieval_id"])
            config = {"provider": settings.provider, "model": settings.model or "fake",
                "timeout_seconds": settings.timeout_seconds, "max_tokens": settings.max_tokens,
                "sampling": "provider_default_unverified", "usage_tokens": None,
                "endpoint_sha256": hashlib.sha256(settings.base_url.encode()).hexdigest()}
            quote = {**inputs, "quote_id": uuid4().hex, "model": config,
                "context_chars": body["context_chars"], "network": settings.provider != "fake",
                "endpoint_host": urlsplit(settings.base_url).netloc if settings.provider != "fake" else None,
                "insecure_http": settings.base_url.startswith("http://"), "expires_in_seconds": 600}
            self.quotes[quote["quote_id"]] = (quote, settings, owner, time.monotonic() + 600)
            while len(self.quotes) > 32:
                self.quotes.popitem(last=False)
            return quote

    def start(self, body, owner):
        with self.lock:
            if not self.enabled or self.closed:
                raise ExperimentError("experiment_runs_disabled", 403)
            if (not isinstance(body, dict) or set(body) != {"quote_id", "request_id", "confirm", "allow_network", "allow_http"}
                    or body["confirm"] is not True
                    or type(body["allow_network"]) is not bool or type(body["allow_http"]) is not bool):
                raise ExperimentError("confirmation_required")
            try:
                job_id = UUID(body["request_id"]).hex
            except (ValueError, TypeError, AttributeError):
                raise ExperimentError("invalid_job_id") from None
            records = self._recover()
            for job in records:
                if job["id"] == job_id or job["quote_id"] == body["quote_id"]:
                    if job["quote_id"] != body["quote_id"]:
                        raise ExperimentError("job_request_conflict", 409)
                    return job  # 双击、网络重发均返回同一次启动，绝不重复计费。
            record = self.quotes.get(body["quote_id"]) if isinstance(body["quote_id"], str) else None
            if record is None or record[2] != owner or record[3] <= time.monotonic():
                raise ExperimentError("quote_expired", 409)
            quote, settings, _, _ = record
            if (quote["network"] and not body["allow_network"]) or (quote["insecure_http"] and not body["allow_http"]):
                raise ExperimentError("network_confirmation_required")
            if len(records) >= 1000:
                raise ExperimentError("job_limit", 409)
            lease = self._lease()
            try:
                cached, source, dataset, fresh = self._inputs(quote["retrieval_id"])
                if any(fresh[key] != quote[key] for key in fresh):
                    raise ExperimentError("report_changed", 409)
                # 全局锁内再检查一次持久请求，覆盖不同控制台进程同时提交的竞态。
                for job in self._records():
                    if job["id"] == job_id or job["quote_id"] == quote["quote_id"]:
                        if job["quote_id"] != quote["quote_id"]:
                            raise ExperimentError("job_request_conflict", 409)
                        lease.close()
                        return job
                job = {"id": job_id, "quote_id": quote["quote_id"], "created_at": qa.now(),
                    "status": "queued", "model": quote["model"], "retrieval_id": quote["retrieval_id"],
                    "source_id": quote["source_id"], "frozen_sha256": quote["frozen_sha256"],
                    "context_chars": quote["context_chars"], "total": quote["total"],
                    "attempts": 0, "completed": 0, "failed": 0, "report_id": None, "error": None}
                self._save(job)
                self.stop_event.clear()
                self.active_id = job_id
                self.thread = threading.Thread(target=self._work,
                    args=(job, lease, cached, source, dataset, settings), daemon=True)
                self.thread.start()
                return dict(job)
            except BaseException:
                lease.close()
                raise

    def _work(self, job, lease, cached, source, dataset, settings):
        def progress(report_id, values):
            with self.lock:
                job.update(values, report_id=report_id)
                if self.stop_event.is_set() and job["status"] == "running":
                    job["status"] = "stopping"
                self._save(job)
        try:
            factory = qa.FakeAnswerGenerator if settings.provider == "fake" else lambda: qa.OpenAICompatibleAnswerGenerator(settings)
            qa.run_answers(cached, source, dataset, factory, output_root=self.backend.runs,
                model_config=job["model"], context_chars=job["context_chars"],
                on_progress=progress, should_stop=self.stop_event.is_set,
                expected_frozen_sha256=job["frozen_sha256"])
        except BaseException:
            with self.lock:
                job.update(status="failed", error="job_execution_failed")
        finally:
            with self.lock:
                job["finished_at"] = qa.now()
                try:
                    self._save(job)
                finally:
                    self.active_id = None
                    lease.close()

    def stop(self, job_id):
        with self.lock:
            self._path(job_id)
            if job_id != self.active_id:
                raise ExperimentError("job_not_owned_or_finished", 409)
            self.stop_event.set()
            return {"stop_requested": True}

    def close(self):
        # 清理时停止后续题；正在传输的一次请求可能完成/计费，不承诺撤销。
        with self.lock:
            self.closed = True
            self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=35)
