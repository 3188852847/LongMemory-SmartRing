"""AB 后台任务契约：真实持久账本，模型/SDK为受控替身。"""

from dataclasses import replace
import json
import sqlite3
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

import pytest

from longmemory.methods.hy_memory.semantic import SemanticCoordinator, SemanticBusy
from longmemory.methods.hy_memory.settings import HySettings
from longmemory.methods.hy_memory.assembly import assemble_hy_backend, management_primitives_identity


SETTINGS = HySettings(user_id="ab-unit", semantic_layers_enabled=True)


def eventually(function):
    until = monotonic() + 3
    while monotonic() < until:
        value = function()
        if value:
            return value
        sleep(0.01)
    raise AssertionError("synthetic task timeout")


def test_task_replay_conflict_cancel_pause_and_restart_no_native_replay(tmp_path):
    calls = []
    client = SimpleNamespace(evolve=lambda **kw: calls.append(kw) or {"success": True})
    owner = SemanticCoordinator(client, SETTINGS, tmp_path)
    try:
        owner.pause(True)
        assert owner.enqueue("paused")["state"] == "pending"
        assert owner.cancel("paused")["cancellation_effect"] == "prevented_start"
        owner.enqueue("resume", max_batches=2)
        owner.pause(False)
        eventually(lambda: owner.task("resume")["state"] == "completed")
        assert owner.status()["schema_state"] == "ready"
        owner.enqueue("resume", max_batches=2)
        with pytest.raises(ValueError, match="conflict"):
            owner.enqueue("resume", max_batches=1)
        assert len(calls) == 1
    finally:
        owner.close()
    with sqlite3.connect(owner.path) as db:
        db.execute("UPDATE tasks SET state='running' WHERE id='resume'")
    reopened = SemanticCoordinator(client, SETTINGS, tmp_path)
    try:
        assert reopened.task("resume")["state"] == "uncertain"
        assert reopened.status()["schema_state"] == "isolated"
        assert reopened.enqueue("resume", max_batches=2)["state"] == "uncertain"
        assert len(calls) == 1
    finally:
        reopened.close()


def test_concurrent_source_change_isolates_result_and_running_cancel_has_no_rollback(tmp_path):
    started, release = Event(), Event()
    def evolve(**kw):
        started.set()
        assert release.wait(3)
        return {"success": True}
    owner = SemanticCoordinator(SimpleNamespace(evolve=evolve), SETTINGS, tmp_path)
    try:
        owner.enqueue("active")
        assert started.wait(2)
        assert owner.cancel("active")["cancellation_effect"] == "already_claimed_no_rollback"
        with pytest.raises(SemanticBusy):
            owner.begin_management({})
        owner.dirty()
        assert owner.status()["schema_state"] == "isolated"
        release.set()
        eventually(lambda: owner.task("active")["state"] == "partial")
        assert owner.task("active")["reason_code"] == "source_changed_during_evolve"
    finally:
        release.set()
        owner.close()


@pytest.mark.parametrize("response,state", [({"success": True, "should_continue": True}, "partial"), ({"success": False}, "uncertain")])
def test_partial_and_failed_native_cycles_never_become_ready(tmp_path, response, state):
    owner = SemanticCoordinator(SimpleNamespace(evolve=lambda **kw: response), SETTINGS, tmp_path)
    try:
        owner.enqueue("bounded")
        eventually(lambda: owner.task("bounded")["state"] == state)
        assert owner.status()["schema_state"] == "isolated"
    finally:
        owner.close()


def test_legacy_disabled_background_proof_cannot_enable_semantic_layers(tmp_path):
    proof = {"sdk_version": "2.0.3", "rpc_source_sha256": management_primitives_identity(),
        "real_sdk_rpc_verified": True, "semantic_background_writes_disabled": True}
    with pytest.raises(ValueError, match="verification"):
        assemble_hy_backend(settings=SETTINGS, state_directory=tmp_path/"engine", source_path=tmp_path/"source.db",
            create=True, client_factory=lambda *a, **k: None, management_verification=proof)
    assert not (tmp_path/"engine").exists()
    assert SETTINGS.identity() == replace(SETTINGS, semantic_layers_enabled=False).identity()


def test_task_options_are_bounded_and_do_not_store_text_or_errors(tmp_path):
    owner = SemanticCoordinator(SimpleNamespace(), SETTINGS, tmp_path, start=False)
    try:
        for options in ({"kind": "contact_user"}, {"max_batches": 0}, {"max_batches": 5}, {"max_batches": True}):
            with pytest.raises(ValueError):
                owner.enqueue("bad", **options)
        with pytest.raises(ValueError):
            owner.enqueue("bad\0id")
        assert "user_id" not in json.dumps(owner.status())
    finally:
        owner.close()


def test_candidate_token_revision_expiry_owner_and_model_denial(monkeypatch):
    import asyncio
    from longmemory.methods.hy_memory import candidate_snapshot as module
    from longmemory.methods.hy_memory.worker import RequestBudget
    client = SimpleNamespace(_search_loop_thread=SimpleNamespace(run=asyncio.run))
    settings = HySettings(user_id="ab-candidate")
    budget = RequestBudget(settings)
    owner = module.CandidateSnapshots(client,settings,budget)
    async def read(embedding, limit):
        return [],40
    owner._read = read
    monkeypatch.setattr(module,"time",lambda:10)
    snapshot = owner.snapshot(query_embedding=[1.0]+[0.0]*7)
    token = snapshot["snapshot_token"]
    assert owner.validate(snapshot_token=token)["valid"]
    assert not owner.validate(snapshot_token=token+"tampered")["valid"]
    assert not module.CandidateSnapshots(client,settings,budget).validate(snapshot_token=token)["valid"]
    owner.changed()
    assert owner.validate(snapshot_token=token)["reason_code"] == "memory_changed_or_busy"
    monkeypatch.setattr(module,"time",lambda:41)
    assert owner.validate(snapshot_token=token)["reason_code"] == "expired"
    for name in ("candidate_snapshot","candidate_validate"):
        budget.operation = name
        with pytest.raises(RuntimeError,match="candidate_model_denied"):
            budget.check_management_request("https://blocked.invalid/v1/embeddings")


def test_graph_partial_edges_cannot_claim_full_sources_or_skip_fact_overlays():
    import asyncio
    from longmemory.methods.hy_memory.semantic import graph_evidence
    from longmemory.methods.hy_memory.sdk_bridge import SOURCE_NAMESPACE
    evidence = SimpleNamespace(user_id=SETTINGS.user_id,agent_id=SETTINGS.agent_id,source=SOURCE_NAMESPACE,
        custom={"source_raw_memory_ids":["raw-1"],"meta":[{"namespace":SOURCE_NAMESPACE,"source_event_ids":["source-1"]}]},
        source_raw_memory_id=None)
    async def get(identifier):
        return evidence
    async def run(query, params):
        return [["fact-1"]] if "VdbRef" in query else []
    client = SimpleNamespace(_graph_store=SimpleNamespace(_run=run),_vector_store=SimpleNamespace(get_by_id=get))
    node = SimpleNamespace(node_id="partial",custom={"evidence_raw_source_ids":["raw-1","raw-2"]})
    assert asyncio.run(graph_evidence(client,SETTINGS,node)) == (None,None)
    node.custom["evidence_raw_source_ids"] = ["raw-1"]
    assert asyncio.run(graph_evidence(client,SETTINGS,node))[1] == ["fact-1"]
    async def orphan(query, params):
        return []
    client._graph_store._run = orphan
    assert asyncio.run(graph_evidence(client,SETTINGS,node)) == (None,None)


@pytest.mark.parametrize("channel",["profile","schema","proactive","normal"])
def test_answer_projection_is_shared_and_idempotent(channel):
    from longmemory.methods.hy_memory.sdk_bridge import project_answer_content
    content = project_answer_content(channel,"合成内容")
    assert project_answer_content(channel,content) == content
