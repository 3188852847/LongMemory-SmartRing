"""隔离合成实验；不使用个人对话、学校模型或圆屏。"""

from dataclasses import replace
import json
import sqlite3

import pytest

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.application.chat.contracts import AnswerGenerationError
from longmemory.evaluation.comparison.dataset import load_dataset
from longmemory.evaluation.comparison import runner
from longmemory.evaluation.comparison.methods import open_method, state_digest
from longmemory.methods.contracts import MemoryEvent, MemorySupport, RetrievedTrace
from longmemory.evaluation.comparison.scoring import score_evidence


@pytest.fixture
def dataset():
    return load_dataset(runner.DEFAULT_DATASET)


def run(tmp_path, dataset, factory=FakeAnswerGenerator, **kwargs):
    return runner.run_comparison(dataset, factory, output_root=tmp_path,
                                 model_config={"provider": "fake", "model": "synthetic"}, **kwargs)


def test_two_methods_frozen_restart_and_metadata_preserved(tmp_path, dataset):
    directory, report = run(tmp_path, dataset)
    assert report["status"] == "completed"
    assert len(report["questions"]) == 16
    assert all(row["state_unchanged"] for row in report["questions"])
    assert not any(row["question_id"].startswith("holdout") for row in report["questions"])
    assert json.loads((directory / "report.json").read_text(encoding="utf-8")) == json.loads(json.dumps(report))
    history = json.loads((directory / "history.json").read_text(encoding="utf-8"))
    assert history[0]["session_id"] == "s01" and history[1]["role"] == "assistant"
    assert history[0]["occurred_at"] == dataset.history[0].occurred_at.isoformat()
    with sqlite3.connect(directory / "longmemory_v1/memory.db") as connection:
        assert connection.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == len(dataset.history)
        assert connection.execute("SELECT created_at FROM conversation_messages WHERE id='e01'").fetchone()[0] == history[0]["occurred_at"]
    rows = {(r["method"], r["question_id"]): r for r in report["questions"]}
    assert rows["longmemory_v1", "dev-name"]["evidence_complete"] is False
    assert rows["longmemory_v1", "dev-research"]["evidence_complete"] is False
    assert rows["dialogue_chunks_v1", "dev-research"]["evidence_complete"] is True
    # 表示不同，不要求两种方法输出相同 L1 文本。
    assert rows["longmemory_v1", "dev-cat"]["injected_context"] != rows["dialogue_chunks_v1", "dev-cat"]["injected_context"]


def test_each_question_has_fresh_answerer_no_labels_or_previous_answer(tmp_path, dataset):
    calls, instances = [], []
    class Spy:
        def __init__(self):
            instances.append(self)
            self.used = False
        def generate(self, **kwargs):
            assert not self.used
            self.used = True
            calls.append(kwargs)
            assert set(kwargs) == {"query", "memory_context"}
            assert "LABEL_ONLY_SENTINEL" not in json.dumps(kwargs)
            assert "PREVIOUS_ANSWER_SENTINEL" not in json.dumps(kwargs)
            return "PREVIOUS_ANSWER_SENTINEL"
    changed = replace(dataset, questions=tuple(replace(q, answer_contains="LABEL_ONLY_SENTINEL", required_terms=("LABEL_ONLY_SENTINEL",)) for q in dataset.questions))
    _, report = run(tmp_path, changed, Spy, context_chars=12)
    assert report["status"] == "completed"
    assert len(calls) == len(instances) == 16
    assert all(len(call["memory_context"]) <= 12 for call in calls)
    assert any(row["context_truncated"] for row in report["questions"])


def test_failures_not_dropped_or_retried_and_error_redacted(tmp_path, dataset):
    calls = []
    class Broken:
        def generate(self, **kwargs):
            calls.append(kwargs)
            raise AnswerGenerationError("PRIVATE_SENTINEL")
    _, report = run(tmp_path, dataset, Broken)
    assert report["status"] == "completed_with_errors" and len(calls) == 16
    assert all(row["status"] == "failed" and row["error"] == "answer_failed" for row in report["questions"])
    assert "PRIVATE_SENTINEL" not in json.dumps(report)
    assert report["summary"]["longmemory_v1"]["answer_denominator_all_questions"] == 8
    assert report["summary"]["longmemory_v1"]["evidence_evaluable_questions"] == 6


def test_sqlite_and_chunks_reject_frozen_writes(tmp_path, dataset):
    directory, _ = run(tmp_path, dataset)
    for name in runner.METHODS:
        state = directory / name
        before = state_digest(state)
        method = open_method(name, state, frozen=True)
        try:
            event = replace(dataset.history[0], event_id="forbidden", session_id=None)
            with pytest.raises((sqlite3.OperationalError, RuntimeError)):
                method.observe(event)
        finally:
            method.close()
        assert state_digest(state) == before


def test_freeze_violation_stops_remaining_questions(tmp_path, dataset, monkeypatch):
    original = runner.open_method
    def open_corrupt(name, directory, *, frozen):
        method = original(name, directory, frozen=frozen)
        if frozen:
            recall = method.recall
            def corrupt(query):
                (directory / "unauthorized-write").write_text("synthetic", encoding="utf-8")
                return recall(query)
            method.recall = corrupt
        return method
    monkeypatch.setattr(runner, "open_method", open_corrupt)
    _, report = run(tmp_path, dataset)
    assert report["status"] == "completed_with_errors"
    for name in runner.METHODS:
        rows = [row for row in report["questions"] if row["method"] == name]
        assert rows[0]["error"] == "frozen_state_changed"
        assert all(row["status"] == "interrupted" for row in rows[1:])


def test_interrupt_checkpoint_keeps_all_denominators(tmp_path, dataset):
    class Stop:
        def generate(self, **kwargs):
            raise KeyboardInterrupt
    directory, report = run(tmp_path, dataset, Stop)
    assert report["status"] == "interrupted"
    assert report["questions"][0]["status"] == "interrupted"
    saved = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    assert len(saved["questions"]) == 16
    assert saved["summary"]["dialogue_chunks_v1"]["interrupted"] == 8


@pytest.mark.parametrize("mutation", ["duplicate", "time", "timezone", "source", "role", "split"])
def test_invalid_dataset_rejected(tmp_path, mutation):
    data = json.loads(runner.DEFAULT_DATASET.read_text(encoding="utf-8"))
    if mutation == "duplicate": data["history"][1]["event_id"] = data["history"][0]["event_id"]
    if mutation == "time": data["history"][1]["occurred_at"] = "2025-01-01T09:00:00+00:00"
    if mutation == "timezone": data["history"][0]["occurred_at"] = "2026-01-01T09:00:00"
    if mutation == "source": data["questions"][0]["evidence_sets"] = [["missing"]]
    if mutation == "role": data["history"][0]["role"] = "system"
    if mutation == "split": data["questions"][0]["split"] = "arbitrary"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_dataset(path)


def test_repeat_runs_are_isolated_and_bad_config_does_not_create_output(tmp_path, dataset):
    first, _ = run(tmp_path, dataset)
    before = (first / "report.json").read_bytes()
    second, _ = run(tmp_path, dataset)
    assert first != second and (first / "report.json").read_bytes() == before
    bad = tmp_path / "not-created"
    with pytest.raises(ValueError):
        run(bad, dataset, methods=("unknown",))
    assert not bad.exists()
    with pytest.raises(ValueError):
        runner.run_comparison(dataset, FakeAnswerGenerator, output_root=bad, model_config={"api_key":"never-save"})
    assert not bad.exists()


def test_evidence_alternatives_and_unknown_information(dataset):
    cat = next(q for q in dataset.questions if q.id == "dev-cat")
    support = MemorySupport("x", "synthetic", (RetrievedTrace("c", "synthetic", ("e11",)),))
    assert score_evidence(cat, support)["evidence_complete"] is True
    unknown = next(q for q in dataset.questions if q.id == "dev-color")
    assert score_evidence(unknown, support)["evidence_complete"] is None
    assert score_evidence(cat, MemorySupport("x", "", None))["evidence_complete"] is None


def test_build_failure_preserves_rows_and_does_not_skip_other_method(tmp_path, dataset, monkeypatch):
    original = runner.open_method
    def broken(name, directory, *, frozen):
        if name == "longmemory_v1":
            raise RuntimeError("PRIVATE_BUILD_SENTINEL")
        return original(name, directory, frozen=frozen)
    monkeypatch.setattr(runner, "open_method", broken)
    _, report = run(tmp_path, dataset)
    assert report["summary"]["longmemory_v1"]["failed"] == 8
    assert report["summary"]["dialogue_chunks_v1"]["completed"] == 8
    assert "PRIVATE_BUILD_SENTINEL" not in json.dumps(report)


def test_chunk_batches_respect_session_and_role_and_ready_is_idempotent(tmp_path, dataset):
    from longmemory.methods.factory import create_method
    path = tmp_path / "nested/chunks.json"
    method = create_method(name="dialogue_chunks_v1", state_path=path)
    first = replace(dataset.history[0], content="共同词甲", session_id="one")
    second = replace(dataset.history[1], content="共同词乙", session_id="two")
    method.observe(first)
    method.observe(second)
    method.wait_until_ready()
    method.wait_until_ready()
    result = method.recall("共同词")
    assert len(result.retrieved) == 2
    assert result.retrieved[1].source_event_ids == (second.event_id,)
    assert "assistant" in result.retrieved[1].content
    with pytest.raises(RuntimeError):
        method.observe(replace(first, event_id="append-after-seal"))
    method.close()
    reopened = create_method(name="dialogue_chunks_v1", state_path=path)
    assert reopened.recall("共同词").context == result.context
    reopened.close()
