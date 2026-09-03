"""网页作业只用合成输入和 Fake；真实 provider 路径也替换传输层。"""
import asyncio
import json
import shutil
import socket
import threading
from pathlib import Path
from uuid import uuid4

import pytest

from longmemory.entrypoints.api.experiment_backend import ExperimentBackend, ExperimentError
from longmemory.entrypoints.api.experiment_jobs import ExperimentJobs
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.evaluation.comparison import retrieval_answers as qa
from longmemory.evaluation.comparison.methods import state_digest
from tests.unit.evaluation.test_retrieval_answers import inputs  # 复用合成工厂，不复制真实报告。


@pytest.fixture
def jobs(inputs, tmp_path):
    cached, source, _ = inputs
    backend = ExperimentBackend(tmp_path / "experiments")
    backend.runs.mkdir(parents=True)
    for path in (cached.parent, source.parent):
        shutil.copytree(path, backend.runs / path.name)
    value = ExperimentJobs(backend, enabled=True)
    yield value
    value.close()


def prepare(jobs, **kwargs):
    source = jobs.options()["retrievals"][0]["id"]
    return jobs.prepare({"retrieval_id": source, "provider": "fake", "context_chars": 4000, **kwargs}, "owner")


def request(quote, **kwargs):
    return {"quote_id": quote["quote_id"], "request_id": str(uuid4()), "confirm": True,
            "allow_network": quote["network"], "allow_http": quote["insecure_http"], **kwargs}


def finish(jobs):
    jobs.thread.join(timeout=10)
    assert not jobs.thread.is_alive()
    return jobs.listing()["items"][0]


def test_prepare_offline_run_progress_preserves_sources_and_idempotence(jobs, monkeypatch):
    monkeypatch.setenv("LONGMEMORY_LLM_API_KEY", "SECRET_KEY")
    monkeypatch.setenv("LONGMEMORY_LLM_MODEL", "REAL_NOT_FAKE")
    before = {p.name: state_digest(p) for p in jobs.backend.runs.iterdir()}
    quote = prepare(jobs)
    assert quote["total"] == 32 and len(quote["groups"]) == 4 and quote["question_count"] == 8
    assert quote["model"]["model"] == "fake" and not quote["network"]
    assert not jobs.directory.exists()  # 预检不创建作业，也不调用模型。
    body = request(quote)
    first = jobs.start(body, "owner")
    assert jobs.start(body, "owner")["id"] == first["id"]
    final = finish(jobs)
    assert final["status"] == "completed" and final["attempts"] == final["completed"] == 32
    assert jobs.start(request(quote), "owner")["id"] == first["id"]
    assert len(jobs.listing()["items"]) == 1
    assert "SECRET_KEY" not in json.dumps(final) and "REAL_NOT_FAKE" not in json.dumps(final)
    assert all(state_digest(jobs.backend.runs / name) == digest for name, digest in before.items())
    restarted = ExperimentJobs(jobs.backend, enabled=True)
    assert restarted.start(body, "new_session")["id"] == first["id"]
    assert restarted.listing()["items"][0]["status"] == "completed"
    assert jobs.backend.detail(final["report_id"])["status"] == "completed"


def test_model_and_network_confirmation_are_required_before_calls(jobs, monkeypatch):
    jobs.settings = ModelSettings(provider="openai_compatible", base_url="http://campus.invalid/v1",
                                 api_key="PRIVATE_KEY", model="SyntheticModel", allow_http=True)
    quote = prepare(jobs, provider="openai_compatible")
    assert quote["network"] and quote["insecure_http"]
    assert "PRIVATE_KEY" not in json.dumps(quote)
    for change in ({"confirm": False}, {"allow_network": False}, {"allow_http": False}):
        with pytest.raises(ExperimentError):
            jobs.start(request(quote, **change), "owner")
    assert jobs.thread is None
    calls = []
    class MockModel:
        def __init__(self, settings):
            assert settings.api_key == "PRIVATE_KEY"
        def generate(self, **kwargs):
            calls.append(kwargs)
            return "合成回答"
    monkeypatch.setattr(qa, "OpenAICompatibleAnswerGenerator", MockModel)
    jobs.start(request(quote), "owner")
    final = finish(jobs)
    assert final["attempts"] == len(calls) == 32
    assert "PRIVATE_KEY" not in json.dumps(final)


def test_global_lock_busy_stop_progress_and_no_retry(jobs, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    class Blocked:
        def generate(self, **kwargs):
            entered.set()
            assert release.wait(5)
            return "合成回答"
    monkeypatch.setattr(qa, "FakeAnswerGenerator", Blocked)
    first, second = prepare(jobs), prepare(jobs)
    started = jobs.start(request(first), "owner")
    assert entered.wait(5)
    try:
        progress = jobs.listing()["items"][0]
        assert progress["attempts"] == 1 and progress["completed"] == 0 and progress["status"] == "running"
        with pytest.raises(ExperimentError, match="experiment_busy"):
            jobs.start(request(second), "owner")
        another = ExperimentJobs(jobs.backend, enabled=True)
        assert another.listing()["items"][0]["status"] == "running"
        with pytest.raises(ExperimentError, match="experiment_busy"):
            another._lease()
        jobs.stop(started["id"])
    finally:
        release.set()
    final = finish(jobs)
    assert final["status"] == "incomplete" and final["attempts"] == final["completed"] == 1
    report = jobs.backend._load(final["report_id"])[0]
    assert report["stop_requested"] and len(report["questions"]) == 32


def test_invalid_inputs_quote_expiry_session_and_source_change(jobs):
    for change in ({"context_chars": True}, {"context_chars": 16001}, {"retrieval_id": "../../.env"}, {"provider": "shell"}):
        with pytest.raises(ValueError):
            prepare(jobs, **change)
    quote = prepare(jobs)
    with pytest.raises(ExperimentError, match="quote_expired"):
        jobs.start(request(quote), "another_session")
    record = jobs.quotes[quote["quote_id"]]
    jobs.quotes[quote["quote_id"]] = (*record[:3], 0)
    with pytest.raises(ExperimentError, match="quote_expired"):
        jobs.start(request(quote), "owner")
    quote = prepare(jobs)
    path = jobs.backend.runs / quote["retrieval_id"] / "report.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ExperimentError, match="report_changed"):
        jobs.start(request(quote), "owner")
    assert jobs.thread is None


def test_disabled_and_unconfigured_are_explicit(jobs):
    with pytest.raises(ExperimentError, match="model_not_configured"):
        prepare(jobs, provider="openai_compatible")
    jobs.enabled = False
    assert not jobs.options()["enabled"]
    with pytest.raises(ExperimentError, match="experiment_runs_disabled"):
        prepare(jobs)


def test_nested_link_rejected_and_worker_revalidates_confirmed_snapshot(jobs, monkeypatch):
    source = jobs.options()["retrievals"][0]["id"]
    linked = jobs.backend.runs / source / "longmemory_v1-vectors.json"
    original = Path.is_junction
    with monkeypatch.context() as patch:
        patch.setattr(Path, "is_junction", lambda p: p == linked or original(p))
        with pytest.raises(ExperimentError, match="linked_experiment_path"):
            prepare(jobs)
    run = qa.run_answers
    def changed_after_start(cached, *args, **kwargs):
        cached.write_bytes(cached.read_bytes() + b" ")
        return run(cached, *args, **kwargs)
    monkeypatch.setattr(qa, "run_answers", changed_after_start)
    jobs.start(request(prepare(jobs)), "owner")
    final = finish(jobs)
    assert final["status"] == "failed" and final["attempts"] == 0
    assert final["report_id"] is None


def test_job_exception_is_sanitized_and_orphan_never_resumes(jobs, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("PRIVATE_MODEL_RESPONSE")
    monkeypatch.setattr(qa, "run_answers", broken)
    jobs.start(request(prepare(jobs)), "owner")
    failed = finish(jobs)
    assert failed["status"] == "failed" and failed["error"] == "job_execution_failed"
    assert "PRIVATE_MODEL_RESPONSE" not in json.dumps(failed)
    failed.update(status="running")
    jobs._save(failed)
    restarted = ExperimentJobs(jobs.backend, enabled=True)
    assert restarted.listing()["items"][0]["status"] == "interrupted"
    assert restarted.thread is None


def test_http_jobs_require_session_csrf_and_confirmation(jobs):
    aiohttp = pytest.importorskip("aiohttp")
    from aiohttp import web
    from longmemory.entrypoints.api.server import create_app
    class Bridge:
        async def close(self): pass
    async def run():
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        app = web.AppRunner(create_app(port=port, bridge=Bridge(), experiment_backend=jobs.backend, job_backend=jobs), access_log=None)
        await app.setup(); await web.SockSite(app, sock).start()
        base = f"http://127.0.0.1:{port}"
        try:
            async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as client:
                assert (await client.get(base+'/api/experiment-jobs')).status == 401
                login = await client.get(base+'/api/session', headers={"X-Console-Bootstrap":"1"})
                csrf = (await login.json())["csrf"]
                headers = {"Origin":base, "X-Console-CSRF":csrf}
                options = await (await client.get(base+'/api/experiment-jobs/options')).json()
                body = {"retrieval_id":options["retrievals"][0]["id"], "provider":"fake", "context_chars":4000}
                url = base+'/api/experiment-jobs/prepare'
                assert (await client.post(url, json=body)).status == 403
                assert (await client.post(url, json=body, headers={**headers,"Origin":"http://evil.invalid"})).status == 403
                response = await client.post(url, json=body, headers=headers)
                assert response.status == 200
                quote = await response.json()
                assert jobs.thread is None
                start = await client.post(base+'/api/experiment-jobs/start', json=request(quote), headers=headers)
                assert start.status == 200
                await asyncio.to_thread(finish, jobs)
                assert (await client.get(base+'/assets/experiment-jobs.mjs')).status == 200
        finally:
            await app.cleanup()
    asyncio.run(run())
