"""验证故障、审计日志与真实提供者选择，不触发外网请求。"""

import json

from longmemory.bootstrap import build_application
from longmemory.application.chat.contracts import AnswerGenerationError
from longmemory.entrypoints.cli.app import main, run_chat_session
from longmemory.infrastructure.logging.setup import configure_file_logging, close_file_logging


def test_model_failure_preserves_user_and_memory_but_not_assistant(tmp_path):
    class Failure:
        def generate(self, **kwargs):
            raise AnswerGenerationError("模型连接失败。")

    path = tmp_path / "audit.jsonl"
    handler = configure_file_logging(path)
    app = build_application(database_path=tmp_path / "test.db", answer_generator=Failure())
    inputs = iter(["我养了一只叫秘密猫的猫。", "/exit"])
    outputs = []
    try:
        run_chat_session(app, input_fn=lambda _: next(inputs), output_fn=outputs.append, provider_label="test")
        assert len(app.list_memories()) == 1
    finally:
        app.close()
        close_file_logging(handler)
    text = path.read_text(encoding="utf-8")
    assert "秘密猫" not in text
    events = [json.loads(line) for line in text.splitlines()]
    assert "answer_failed" in [event["event"] for event in events]
    assert "assistant_saved" not in [event["event"] for event in events]
    assert len({event["turn_id"] for event in events}) == 1
    assert any("回答失败" in output for output in outputs)


def test_check_model_cannot_pass_using_fake(capsys):
    assert main(["--provider", "fake", "--check-model"]) == 2
    assert "不能用 Fake" in capsys.readouterr().out


def test_check_model_uses_mock_and_creates_no_database(tmp_path, monkeypatch):
    monkeypatch.setenv("LONGMEMORY_LLM_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("LONGMEMORY_LLM_API_KEY", "synthetic-secret")
    monkeypatch.setenv("LONGMEMORY_LLM_MODEL", "test-model")
    monkeypatch.setattr("longmemory.entrypoints.cli.app.OpenAICompatibleAnswerGenerator.generate", lambda *a, **kw: "OK")
    path = tmp_path / "should-not-exist.db"
    assert main(["--provider", "openai_compatible", "--check-model", "--database", str(path)]) == 0
    assert not path.exists()
