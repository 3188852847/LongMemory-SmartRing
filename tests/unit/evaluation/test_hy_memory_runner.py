from dataclasses import replace
import importlib.util
from pathlib import Path
import sqlite3

from longmemory.evaluation.comparison.dataset import load_dataset
from longmemory.evaluation.comparison.hy_memory_runner import PROTOCOL, run_hy_comparison
from longmemory.methods.hy_memory.assembly import assemble_hy_backend
from longmemory.methods.hy_memory.settings import HySettings


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("hy_runner_fake", ROOT / "tests/fixtures/hy_memory_fake_worker.py")
fake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fake)
SETTINGS = HySettings(user_id="v-synthetic-only")


def opener(directory, *, create_engine, create_sources):
    return assemble_hy_backend(settings=SETTINGS, state_directory=directory / "engine",
        source_path=directory / "sources.db", create=create_engine, create_sources=create_sources,
        client_factory=fake.PersistentFakeClient)


def dev_slice():
    dataset = load_dataset(ROOT / "datasets/synthetic/hy_memory_dev_v1.json")
    return replace(dataset, questions=dataset.questions[:2])


def test_per_question_copy_reuses_u_and_scoring_without_fake_freeze_claim(tmp_path):
    path, report = run_hy_comparison(dev_slice(), output_root=tmp_path, hy_opener=opener)
    assert report["manifest"]["protocol"] == PROTOCOL
    assert report["status"] == "completed"
    assert len(report["questions"]) == 4
    hy = [row for row in report["questions"] if row["method"] == "hy_memory_pro_chat"]
    assert all(row["sealed_source_unchanged"] for row in report["questions"])
    assert all(not row["clone_state_audit"]["byte_state_unchanged"] for row in hy)
    assert all(row["clone_state_audit"]["semantic_state_unchanged"] is None for row in hy)
    with sqlite3.connect(path / "sealed/h/sources.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversation_messages").fetchone()[0] == 12
    assert all(row["support"]["warning_code"] == "hy_recall_may_mutate_state" for row in hy)


def test_build_failure_keeps_all_questions_in_denominator(tmp_path):
    def factory(root, *, create):
        client = fake.PersistentFakeClient(root, create=create)
        client.fail_after = True
        return client
    def failed(directory, *, create_engine, create_sources):
        return assemble_hy_backend(settings=SETTINGS, state_directory=directory / "engine",
            source_path=directory / "sources.db", create=create_engine, create_sources=create_sources,
            client_factory=factory)
    _, report = run_hy_comparison(dev_slice(), output_root=tmp_path, hy_opener=failed)
    assert report["status"] == "completed_with_errors"
    assert report["summary"]["hy_memory_pro_chat"]["failed"] == 2
    assert report["summary"]["hy_memory_pro_chat"]["answer_denominator_all_questions"] == 2
