import importlib.util
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/voice_prediction.py"
SPEC = importlib.util.spec_from_file_location("voice_prediction_test", SCRIPT)
prediction = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prediction)


def test_closed_question_only_accepts_bounded_yes_no_endings():
    assert prediction.closed_question("要不要继续聊一会儿？") is True
    assert prediction.closed_question("你需要我陪你梳理一下吗？") is True
    assert prediction.closed_question("你今天过得怎么样？") is False
    assert prediction.closed_question("要不要继续？我还可以介绍别的内容。") is False


def test_reply_branch_requires_complete_short_reply():
    assert prediction.reply_branch("好的！") == "affirmative"
    assert prediction.reply_branch("不用了。") == "negative"
    assert prediction.reply_branch("可以，不过我想先问另一件事") is None


def test_shadow_counts_pending_hit_and_miss_without_content():
    shadow = prediction.VoicePredictionShadow()
    assert shadow.observe_assistant("要不要继续？") is True
    assert shadow.observe_user("好") == "affirmative"
    assert shadow.observe_assistant("你愿意再试一次吗？") is True
    assert shadow.observe_user("我突然想聊别的") is None
    assert shadow.snapshot() == {
        "version": 1, "state": "observing", "opportunities": 2,
        "evaluated": 2, "hits": 1, "misses": 1, "last_result": "miss",
    }
    assert "继续" not in repr(shadow.snapshot())


def test_installed_shadow_observes_adjacent_top_level_turns():
    class Connection:
        def chat(self, query, depth=0):
            answer = "要不要继续聊？" if query == "开始" else "好，我们继续。"
            self.dialogue.dialogue.append(SimpleNamespace(role="assistant", content=answer))

    prediction.install_voice_prediction_shadow(Connection)
    connection = Connection()
    connection.dialogue = SimpleNamespace(dialogue=[])
    connection.chat("开始")
    connection.chat("好的")
    assert connection._longmemory_voice_prediction_shadow.snapshot()["hits"] == 1
