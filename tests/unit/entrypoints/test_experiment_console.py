"""实验档案 API 使用临时合成报告；不会对用户的真实复核执行写入。"""
import asyncio
import hashlib
import json
from pathlib import Path
import socket
from uuid import uuid4

import pytest

from longmemory.entrypoints.api.experiment_backend import ExperimentBackend, ExperimentError

RUN = "comparison-" + "a" * 32


@pytest.fixture
def backend(tmp_path):
    root = tmp_path / "experiments"
    path = root / "runs" / RUN
    path.mkdir(parents=True)
    report = {"manifest": {"protocol": "history-replay-frozen-qa-v1", "started_at": "2026-09-03T10:00:00Z",
        "dataset": {"name": "synthetic", "version": "1", "sha256": "a"*64, "api_key": "DO_NOT_EXPOSE"},
        "answer_model": {"provider": "fake", "model": "fake", "api_key": "DO_NOT_EXPOSE"}, "split": "dev"},
        "status": "completed", "questions": []}
    for qid in ("q1", "q2"):
        report["questions"].append({"method": "longmemory_v1", "question_id": qid,
            "query": "合成问题", "status": "completed", "answer": '<script>合成回答</script>',
            "answer_proxy_pass": qid == "q1", "evidence_complete": qid == "q1", "state_unchanged": True,
            "injected_context": "证据", "support": {"context": "证据", "retrieved": [
                {"item_id": "i1", "content": "合成事实", "source_event_ids": ["e01"]}]}})
    (path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (path / "history.json").write_text(json.dumps([{"event_id": "e01", "role": "user", "content": "原始合成文本"}]), encoding="utf-8")
    return ExperimentBackend(root)


def body(backend, **changes):
    result = {"report_sha256": backend.detail(RUN)["report_sha256"], "reviewer": "测试者", "revision": None,
              "method": "longmemory_v1", "question_id": "q1", "verdict": "pass", "rationale": "依据原始合成事实",
              "request_id": str(uuid4())}
    result.update(changes)
    return result


def test_list_details_sources_whitelist_and_unknown_files(backend):
    (backend.runs / "not-a-run").mkdir()
    broken = backend.runs / ("comparison-" + "b" * 32)
    broken.mkdir(); (broken / "report.json").write_text("{")
    listing = backend.listing()
    assert len(listing["items"]) == 1 and listing["skipped"] == 1
    detail = backend.detail(RUN)
    assert detail["groups"][0]["total"] == 2 and detail["groups"][0]["answer_pass"] == 1
    assert "DO_NOT_EXPOSE" not in repr(detail) + repr(listing)
    question = backend.question(RUN, "q1")
    assert question["rows"][0]["sources"][0]["role"] == "user"
    assert question["rows"][0]["answer"].startswith("<script>")  # 由前端作为纯文本渲染。
    assert not backend.results.exists()  # 查看不隐式创建目录。


def test_append_review_restart_idempotence_and_conflicts(backend):
    source = backend.runs / RUN / "report.json"
    original = source.read_bytes()
    request = body(backend)
    first = backend.save_review(RUN, request)
    assert backend.save_review(RUN, request)["replayed"]
    with pytest.raises(ExperimentError, match="request_conflict"):
        backend.save_review(RUN, {**request, "rationale": "修改了"})
    backend = ExperimentBackend(backend.root)
    current = backend.detail(RUN)["reviews"][0]
    assert current["revision"] == first["revision"]
    assert current["summary"]["longmemory_v1"]["pending"] == 1
    with pytest.raises(ExperimentError, match="review_changed"):
        backend.save_review(RUN, body(backend, question_id="q2"))
    backend.save_review(RUN, body(backend, question_id="q2", revision=first["revision"], verdict="fail"))
    assert len(list(backend.results.glob("*.json"))) == 2
    assert source.read_bytes() == original
    assert backend.detail(RUN)["reviews"][0]["summary"]["longmemory_v1"]["fail"] == 1


def test_assistant_is_not_overwritten_and_stale_report_refused(backend):
    backend.save_review(RUN, body(backend))
    path = next(backend.results.glob("*.json"))
    saved = json.loads(path.read_text(encoding="utf-8")); saved["reviewer_kind"] = "assistant"
    path.write_text(json.dumps(saved), encoding="utf-8")
    backend.save_review(RUN, body(backend))
    assert {r["reviewer_kind"] for r in backend.detail(RUN)["reviews"]} == {"human", "assistant"}
    old = body(backend)
    report = backend.runs / RUN / "report.json"
    report.write_text(report.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ExperimentError, match="report_changed"):
        backend.save_review(RUN, old)
    assert backend.detail(RUN)["ignored_reviews"] == 2


@pytest.mark.parametrize("changes", [{"rationale": ""}, {"rationale":"a"*1001}, {"reviewer":" "},
    {"verdict":"invented"}, {"request_id":"../bad"}, {"method":"unknown"}, {"question_id":"missing"}, {"extra":"field"}])
def test_invalid_reviews_do_not_write(backend, changes):
    with pytest.raises(ValueError):
        backend.save_review(RUN, body(backend, **changes))
    assert not backend.results.exists()


def test_path_traversal_and_links_rejected(backend, monkeypatch):
    for run_id in ("../report", "/absolute", "comparison-../../secret"):
        with pytest.raises(ExperimentError): backend.detail(run_id)
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda p: p == backend.runs / RUN or original(p))
    with pytest.raises(ExperimentError, match="linked_experiment_path"): backend.detail(RUN)


def test_retrieval_groups_and_replay_parent_history(backend):
    source = json.loads((backend.runs / RUN / "report.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256((backend.runs / RUN / "report.json").read_bytes()).hexdigest()
    manifest = {"protocol":"frozen-l1-retrieval-ablation-v1", "source_manifest":source["manifest"],
                "source_report_sha256":digest, "split":"dev"}
    rows = [dict(r, strategy="dense_cosine") for r in source["questions"]]
    run_id = "retrieval-" + "c"*32
    folder = backend.runs / run_id; folder.mkdir()
    (folder / "report.json").write_text(json.dumps({"manifest":manifest,"questions":rows,"status":"completed"}),encoding="utf-8")
    detail = backend.detail(run_id)
    assert not detail["review_enabled"] and detail["groups"][0]["id"].endswith("/dense_cosine")
    assert backend.question(run_id,"q1")["rows"][0]["sources"][0]["content"] == "原始合成文本"
    with pytest.raises(ExperimentError, match="answers_required"): backend.save_review(run_id,body(backend))


def _l1_sufficiency_source(backend, suffix="d"):
    run_id = "l1-sufficiency-rescore-" + suffix * 32
    folder = backend.runs / run_id
    folder.mkdir()
    report = {
        "manifest": {
            "protocol": "l1-evidence-sufficiency-rescore-v1",
            "created_at": "2026-09-13T12:00:00Z",
            "target_dataset_id": "l1-synthetic-v2",
            "target_dataset_sha256": "e" * 64,
            "model": {"provider": "synthetic"},
        },
        "status": "completed",
        "rows": [{
            "case_id": "cat-color", "category": "missing_attribute",
            "status": "completed",
            "candidates": [{"id": "cat-name", "content": "用户的猫叫豆包。"}],
            "expected_supported_ids": [], "predicted_supported_ids": [],
        }],
    }
    (folder / "report.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8",
    )
    return run_id


def test_l1_policy_replay_is_local_idempotent_and_path_bounded(backend):
    source_id = _l1_sufficiency_source(backend)
    options = backend.l1_policy_replay_options()
    assert options["sources"][0]["id"] == source_id
    request_id = str(uuid4())
    first = backend.run_l1_policy_replay({
        "source_id": source_id, "request_id": request_id,
    })
    second = backend.run_l1_policy_replay({
        "source_id": source_id, "request_id": request_id,
    })
    assert first["status"] == "completed" and not first["replayed"]
    assert second["id"] == first["id"] and second["replayed"]
    assert first["summary"]["false_block_cases"] == 0
    assert first["summary"]["unsupported_pass_cases"] == 0
    assert backend.l1_policy_replay_options()["replays"][0]["id"] == first["id"]
    for bad in ("../source", RUN, "l1-sufficiency-rescore-short"):
        with pytest.raises(ExperimentError, match="invalid_l1_policy_replay"):
            backend.run_l1_policy_replay({"source_id": bad, "request_id": str(uuid4())})


def test_http_session_csrf_static_no_arbitrary_files_or_execution(backend):
    aiohttp = pytest.importorskip("aiohttp")
    from aiohttp import web
    from longmemory.entrypoints.api.server import create_app
    l1_source = _l1_sufficiency_source(backend)
    class Bridge:
        async def close(self): pass
    async def run():
        sock = socket.socket();sock.bind(("127.0.0.1",0)); port=sock.getsockname()[1]
        app = web.AppRunner(create_app(port=port,bridge=Bridge(),experiment_backend=backend),access_log=None)
        await app.setup();await web.SockSite(app,sock).start()
        base=f"http://127.0.0.1:{port}"
        try:
            async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as client:
                for url in ("/experiments","/assets/experiments.js","/assets/experiment-view.mjs","/assets/experiments.css"):
                    response=await client.get(base+url);assert response.status==200
                    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
                assert (await client.get(base+'/api/experiments')).status==401
                assert (await client.get(base+'/api/l1-policy-replay')).status==401
                login=await client.get(base+'/api/session',headers={"X-Console-Bootstrap":"1"})
                csrf=(await login.json())["csrf"]
                headers={"Origin":base,"X-Console-CSRF":csrf}
                assert (await client.get(base+'/api/experiments')).status==200
                replay_options = await (await client.get(base+'/api/l1-policy-replay')).json()
                assert replay_options["sources"][0]["id"] == l1_source
                replay_body = {"source_id": l1_source, "request_id": str(uuid4())}
                assert (await client.post(base+'/api/l1-policy-replay',json=replay_body)).status==403
                replay_response = await client.post(
                    base+'/api/l1-policy-replay', json=replay_body, headers=headers,
                )
                assert replay_response.status == 200
                assert (await replay_response.json())["status"] == "completed"
                path=base+f'/api/experiments/{RUN}/reviews'
                assert (await client.post(path,json=body(backend))).status==403
                assert (await client.post(path,json=body(backend),headers={**headers,"Origin":"http://hostile.test"})).status==403
                result=await client.post(path,json=body(backend),headers=headers); assert result.status==200
                assert (await client.get(base+f'/api/experiments/{RUN}/question?id=q1')).status==200
                for url in ('/experiments/runs/'+RUN+'/report.json','/.env','/api/experiments/run'):
                    assert (await client.post(base+url,headers=headers)).status in (404,405)
        finally: await app.cleanup()
    asyncio.run(run())
