"""只用合成临时库和本地替身；不访问校园模型或个人数据库。"""

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading

import pytest

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.adapters.llm.openai_compatible import OpenAICompatibleAnswerGenerator
from longmemory.application.chat.contracts import AnswerGenerationError
from longmemory.application.memory_runtime import MemoryRuntime
from longmemory.application.persona_recall import PersonaRecallItem, PersonaRecallResult
from longmemory.application.scenario_recall import ScenarioRecallItem, ScenarioRecallResult
from longmemory.bootstrap import build_memory_runtime
from longmemory.core.memory.retrieval.service import HybridMemoryRetriever
from longmemory.entrypoints.api.chat_backend import ChatBackend
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.contracts import MemoryEvent
from longmemory.methods.daily_llm.method import DailyLLMMemory
from longmemory.methods.longmemory_v1.method import LongMemoryV1
from datetime import UTC, datetime


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "synthetic.db"
    LongMemoryV1(path).close()
    return path


def test_web_and_other_method_share_memory_without_sharing_session_history(database):
    web = ChatBackend(database, FakeAnswerGenerator())
    first = web.run("我养了一只叫豆包的猫", ())
    assert first["status"] == "completed" and first["user_saved"] and first["assistant_saved"]
    assert first["writes"][0]["operation"] == "add"
    other = LongMemoryV1(database)
    assert "豆包" in other.recall("我的猫叫什么").context
    other.close()
    result = ChatBackend(database, FakeAnswerGenerator()).run("我的猫叫什么", ())
    assert result["writes"] == [] and result["history_messages"] == 0
    assert "豆包" in result["answer"]
    assert result["retrieved"][0]["source_event_ids"] == (first["event_id"],)
    assert result["memory_context"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == 4


def test_model_failure_preserves_actual_write_trace_but_not_assistant_fact(database):
    class Broken:
        def generate(self, **kwargs):
            raise AnswerGenerationError("secret-should-not-leak")
    result = ChatBackend(database, Broken()).run("我养了一只叫豆包的猫", ())
    assert result["status"] == "failed" and result["user_saved"]
    assert result["writes"][0]["operation"] == "add"
    assert result["answer"] is None and not result["assistant_saved"]
    assert "secret-should-not-leak" not in json.dumps(result)


def test_application_command_reply_does_not_depend_on_model_wording(database):
    class MustNotRun:
        def generate(self, **_kwargs):
            raise AssertionError("高精度操作回执不应交给模型改写")

    backend = ChatBackend(database, MustNotRun())
    try:
        result = backend.run("不要记住：我今天想喝茉莉花茶", ())
        assert result["status"] == "completed"
        assert result["answer_source"] == "application_command"
        assert result["answer"] == result["memory_command"]["notice"]
        assert result["writes"] == []
        assert result["assistant_saved"] is True
    finally:
        backend.close()


def test_next_turn_interaction_setting_is_an_application_reply(database):
    class MustNotRun:
        def generate(self, **_kwargs):
            raise AssertionError("下一轮互动设置不应交给模型自由改写")

    backend = ChatBackend(database, MustNotRun())
    try:
        result = backend.run("下一轮先问我要不要建议", ())
        assert result["status"] == "completed"
        assert result["answer_source"] == "application_command"
        assert result["memory_command"]["kind"] == "set_next_interaction"
        assert result["memory_command"]["status"] == "armed"
        assert result["answer"] == result["memory_command"]["notice"]
        assert result["writes"] == []
    finally:
        backend.close()


def test_model_health_records_safe_failure_and_explicit_probe_does_not_write_memory(database):
    class Broken:
        def with_role_prompt(self, _prompt):
            return self
        def generate(self, **_kwargs):
            raise AnswerGenerationError("private upstream body", code="model_authentication_failed")
        generate_turn = generate
    backend = ChatBackend(database, Broken(), provider="openai_compatible", model="synthetic")
    assert backend.info()["model_health"]["state"] == "unchecked"
    health = backend.check_model()
    assert health["state"] == "unavailable" and health["code"] == "model_authentication_failed"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == 0
    result = backend.run("我叫小林", ())
    assert result["error"] == "model_authentication_failed"
    assert "private upstream body" not in json.dumps(result)


def test_model_info_exposes_endpoint_but_never_credentials(database):
    backend = ChatBackend(database, FakeAnswerGenerator(), provider="openai_compatible",
                          model="synthetic", model_endpoint="http://model.invalid/tenant/v1",
                          insecure_model_transport=True)
    info = backend.info()
    assert info["model_endpoint"] == "http://model.invalid/tenant/v1"
    assert info["insecure_model_transport"] is True
    assert "api_key" not in json.dumps(info).lower()


def test_missing_and_old_database_not_created_or_migrated(tmp_path):
    missing = tmp_path / "missing.db"
    result = ChatBackend(missing, FakeAnswerGenerator()).run("你好", ())
    assert result["status"] == "failed" and not missing.exists()
    old = tmp_path / "old.db"
    with sqlite3.connect(old) as connection:
        connection.execute("PRAGMA user_version = 1")
    before = old.read_bytes()
    result = ChatBackend(old, FakeAnswerGenerator()).run("你好", ())
    assert result["status"] == "failed" and old.read_bytes() == before


def test_atomic_observe_rolls_back_l0_when_extraction_fails(database):
    method = LongMemoryV1(database)
    def fail(message):
        raise RuntimeError("synthetic extraction failure")
    method.extractor.extract = fail
    with pytest.raises(RuntimeError):
        method.observe(MemoryEvent("synthetic-event", "user", "我喜欢猫", datetime.now(UTC)))
    assert method.connection.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == 0
    method.close()


def test_two_connections_deduplicate_in_same_write_transaction(database):
    barrier = threading.Barrier(2)
    def write(index):
        method = LongMemoryV1(database, existing_only=True)
        try:
            barrier.wait(timeout=3)
            return method.observe(MemoryEvent(str(index), "user", "我养了一只叫豆包的猫", datetime.now(UTC)))
        finally:
            method.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, (1, 2)))
    assert sorted(item.writes[0].operation for item in results) == ["add", "noop"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM memory_evidence").fetchone()[0] == 2


def test_model_payload_preserves_roles_and_legacy_generate_protocol(database):
    payloads = []
    def transport(settings, body):
        payloads.append(json.loads(body))
        return 200, b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
    generator = OpenAICompatibleAnswerGenerator(
        ModelSettings(provider="openai_compatible", base_url="https://synthetic.invalid/v1", api_key="synthetic", model="test"),
        transport=transport, role_prompt="synthetic role",
    )
    history = ({"role": "user", "content": "上一句"}, {"role": "assistant", "content": "上个回答"})
    result = ChatBackend(database, generator, provider="openai_compatible").run("继续", history)
    assert result["status"] == "completed"
    assert payloads[0]["messages"][-3:] == [*history, {"role": "user", "content": "继续"}]
    assert payloads[0]["messages"][1]["content"] == "synthetic role"
    generator.generate(query="独立问题", memory_context="")
    assert "上一句" not in json.dumps(payloads[1], ensure_ascii=False)


def test_shared_runtime_serializes_two_entry_threads(database):
    backend = ChatBackend(database, FakeAnswerGenerator())
    barrier = threading.Barrier(2)

    def prepare(_index):
        barrier.wait(timeout=3)
        return backend.memory_runtime().prepare_user("我养了一只叫豆包的猫")

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            turns = list(pool.map(prepare, (1, 2)))
        operations = sorted(turn.observation.writes[0].operation for turn in turns)
        assert operations == ["add", "noop"]
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 1
            assert connection.execute("SELECT count(*) FROM memory_evidence").fetchone()[0] == 2
    finally:
        backend.close()


def test_daily_llm_failure_is_visible_but_chat_continues_from_archived_l0(database):
    class BrokenProducer:
        def propose(self, **_kwargs):
            raise OSError("private upstream detail")

    method = DailyLLMMemory(database, producer=BrokenProducer(), allow_cross_thread=True)
    backend = ChatBackend(database, FakeAnswerGenerator(), runtime=MemoryRuntime(database, method=method))
    try:
        result = backend.run("我叫小林", ())
        assert result["status"] == "completed" and result["user_saved"]
        assert result["method"] == "longmemory_daily_llm_v2"
        assert result["memory_processing"] == "source_only"
        assert result["memory_warning"] == "l1_extraction_failed"
        assert result["writes"] == []
        assert "private upstream detail" not in json.dumps(result)
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT count(*) FROM conversation_messages WHERE role='user'"
            ).fetchone()[0] == 1
            assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 0
    finally:
        backend.close()


def test_round_screen_defers_llm_extraction_until_completion_without_locking_reads(database):
    started = threading.Event()
    release = threading.Event()

    class SlowProducer:
        def propose(self, **_kwargs):
            started.set()
            assert release.wait(timeout=3)
            return json.dumps({
                "schema_version": 1,
                "operation": "ADD",
                "facts": [{"content": "用户叫小林。", "quote": "我叫小林"}],
            }, ensure_ascii=False)

    method = DailyLLMMemory(
        database, producer=SlowProducer(), allow_cross_thread=True,
    )
    runtime = MemoryRuntime(database, method=method)
    backend = ChatBackend(
        database, FakeAnswerGenerator(), runtime=runtime,
    )
    try:
        prepared, _feedback = backend.prepare_round_screen_user("我叫小林")
        assert prepared.observation.warning_code == "l1_extraction_deferred"
        assert not started.is_set()
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT count(*) FROM conversation_messages WHERE role='user'"
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT count(*) FROM atomic_memories"
            ).fetchone()[0] == 0

        completed = backend.complete_round_screen_turn(
            turn_id=prepared.event.event_id,
            answer="好的，我记住了。",
            retrieved_counts={"l1": 0, "l2": 0, "l3": 0},
        )
        assert completed.created is True
        assert started.wait(timeout=1)
        # 尝试账本必须已经在 Runtime 互斥区提交；模型工作线程此刻只做计算。
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT phase FROM l1_extraction_events WHERE source_message_id=?",
                (prepared.event.event_id,),
            ).fetchone()[0] == "started"
        # 候选模型仍被阻塞时，Runtime 状态读取不应等待模型完成。
        status = runtime.status()
        assert status["deferred_observation"]["running_or_queued"] == 1

        release.set()
        runtime.wait_for_deferred_observations()
        # 这里验证补写是否可见，不把关键词基线尚不具备的语义改写能力
        # 混入延后执行测试，因此直接用实体词查询。
        assert "小林" in method.recall("小林").context
        assert runtime.complete_deferred_observation(
            prepared.event.event_id,
        ) is False
    finally:
        release.set()
        backend.close()


def test_chat_reports_hybrid_retrieval_without_hiding_dense_fallback(database):
    class Encoder:
        identity = "synthetic-chat-encoder"

        def encode_documents(self, texts):
            return [[1.0, 0.0] for _ in texts]

        def encode_query(self, _text):
            return [1.0, 0.0]

    method = LongMemoryV1(
        database,
        existing_only=True,
        allow_cross_thread=True,
        retriever_factory=lambda store: HybridMemoryRetriever(store, Encoder()),
    )
    backend = ChatBackend(database, FakeAnswerGenerator(), runtime=MemoryRuntime(database, method=method))
    try:
        assert backend.info()["retrieval"] == "keyword_dense_rrf_v1"
        result = backend.run("我喜欢乌龙茶", ())
        assert result["retrieval_strategy"] == "keyword_dense_rrf_v1"
        assert result["retrieval_warning"] is None
    finally:
        backend.close()


def test_runtime_memory_modes_are_independent_and_keep_l0(database):
    """暂停派生记忆不等于停止审计；暂停召回也不影响独立的写入开关。"""

    backend = ChatBackend(database, FakeAnswerGenerator())
    runtime = backend.memory_runtime()
    try:
        assert runtime.status()["write_enabled"] is True
        assert runtime.status()["use_enabled"] is True
        assert runtime.status()["settings_persistent"] is False

        # 先建立一条已知长期记忆，再暂停新的 L1 写入。
        backend.run("我养了一只叫豆包的猫", ())
        runtime.configure(write_enabled=False, use_enabled=True)
        result = backend.run("我喜欢一种叫暮雪的合成饮料", ())
        assert result["status"] == "completed"
        assert result["memory_write_enabled"] is False
        assert result["memory_use_enabled"] is True
        assert result["writes"] == []

        # 已有记忆仍可召回；暂停期间的原文进 L0，但不会派生为 L1。
        recalled = backend.run("我的猫叫什么", ())
        assert "豆包" in recalled["answer"]
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT count(*) FROM conversation_messages WHERE content LIKE '%暮雪%'"
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT count(*) FROM atomic_memories WHERE content LIKE '%暮雪%'"
            ).fetchone()[0] == 0

        # 重新允许写入、关闭召回：本轮能产生 L1，但不会把旧证据注入回答。
        runtime.configure(write_enabled=True, use_enabled=False)
        no_context = backend.run("我喜欢青色", ())
        assert no_context["memory_write_enabled"] is True
        assert no_context["memory_use_enabled"] is False
        assert no_context["memory_context"] == ""
        assert no_context["retrieved"] == []
        assert no_context["retrieval_strategy"] == "disabled_by_user"
        assert no_context["writes"][0]["operation"] == "add"
    finally:
        backend.close()


@pytest.mark.parametrize(
    "write_enabled,use_enabled",
    [(1, True), (True, 0), ("true", True), (True, None)],
)
def test_runtime_rejects_non_boolean_memory_modes(database, write_enabled, use_enabled):
    runtime = build_memory_runtime(database)
    try:
        with pytest.raises(ValueError, match="memory_mode_invalid"):
            runtime.configure(write_enabled=write_enabled, use_enabled=use_enabled)
        # 失败更新不能产生半配置状态。
        assert runtime.status()["write_enabled"] is True
        assert runtime.status()["use_enabled"] is True
    finally:
        runtime.close()


def test_runtime_memory_modes_reset_for_a_new_process_runtime(database):
    first = build_memory_runtime(database)
    first.configure(write_enabled=False, use_enabled=False)
    first.close()

    second = build_memory_runtime(database)
    try:
        assert second.status()["write_enabled"] is True
        assert second.status()["use_enabled"] is True
        assert second.status()["settings_persistent"] is False
    finally:
        second.close()


def test_runtime_l2_use_is_opt_in_shared_and_separately_traced(database):
    class ScenarioProvider:
        def recall(self, query, *, limit=3):
            assert query == "答辩准备得怎么样"
            return ScenarioRecallResult(
                "以下是与当前问题相关、已经用户复核的生活场景（L2）：\n- 准备答辩：用户周五答辩并在修改 PPT。",
                (ScenarioRecallItem("l2-a", "准备答辩", "用户周五答辩并在修改 PPT。",
                                    ("l1-a", "l1-b"), ("l0-a", "l0-b")),),
            )

        def close(self):
            pass

    runtime = MemoryRuntime(database, method=LongMemoryV1(database, existing_only=True),
                            scenario_provider=ScenarioProvider())
    backend = ChatBackend(database, FakeAnswerGenerator(), runtime=runtime)
    try:
        assert backend.run("答辩准备得怎么样", ())["scenario_retrieved"] == []
        runtime.configure(write_enabled=True, use_enabled=True, scenario_use_enabled=True)
        result = backend.run("答辩准备得怎么样", ())
        assert result["status"] == "completed"
        assert result["scenario_use_enabled"] is True
        assert result["scenario_retrieved"][0]["scenario_id"] == "l2-a"
        assert result["scenario_retrieved"][0]["source_memory_ids"] == ("l1-a", "l1-b")
        assert "用户复核" in result["memory_context"]
    finally:
        backend.close()


def test_l2_sufficiency_shadow_observes_candidates_without_injecting_them(database):
    class ScenarioProvider:
        def recall(self, query, *, limit=3):
            assert query == "我的猫是什么颜色"
            return ScenarioRecallResult(
                "[L2 private context]",
                (ScenarioRecallItem(
                    "scene-cat", "猫咪", "用户养了一只叫豆包的猫。",
                    ("l1-a",), ("l0-a",), keyword_score=2,
                ),),
            )

        def close(self):
            pass

    class Shadow:
        def __init__(self):
            self.calls = []

        def submit(self, **values):
            self.calls.append(values)
            return True

        def status(self):
            class Status:
                def to_dict(self):
                    return {"enabled": True, "state": "not_run"}
            return Status()

        def wait(self):
            pass

        def close(self):
            pass

    shadow = Shadow()
    runtime = MemoryRuntime(
        database,
        method=LongMemoryV1(database, existing_only=True),
        scenario_provider=ScenarioProvider(),
        l2_sufficiency_shadow=shadow,
    )
    backend = ChatBackend(database, FakeAnswerGenerator(), runtime=runtime)
    try:
        result = backend.run("我的猫是什么颜色", ())
        assert result["scenario_use_enabled"] is False
        assert result["scenario_retrieved"] == []
        assert "[L2 private context]" not in result["memory_context"]
        assert len(shadow.calls) == 1
        assert shadow.calls[0]["user_message_id"] == result["event_id"]
        assert shadow.calls[0]["candidates"].items[0].scenario_id == "scene-cat"
        assert runtime.status()["l2_sufficiency_shadow"]["enabled"] is True
    finally:
        backend.close()


def test_l1_sufficiency_shadow_observes_only_atomic_recall_without_filtering(database):
    seed = ChatBackend(database, FakeAnswerGenerator())
    seeded = seed.run("我养了一只叫豆包的猫", ())
    seed.close()

    class Shadow:
        def __init__(self):
            self.calls = []

        def submit(self, **values):
            self.calls.append(values)
            return True

        def status(self):
            class Status:
                def to_dict(self):
                    return {"enabled": True, "state": "not_run"}
            return Status()

        def wait(self):
            pass

        def close(self):
            pass

    shadow = Shadow()
    runtime = MemoryRuntime(
        database, method=LongMemoryV1(database, existing_only=True),
        l1_sufficiency_shadow=shadow,
    )
    backend = ChatBackend(database, FakeAnswerGenerator(), runtime=runtime)
    try:
        result = backend.run("我的猫叫什么", ())
        assert result["status"] == "completed"
        assert "豆包" in result["memory_context"]  # 影子复核没有过滤正式上下文。
        assert len(shadow.calls) == 1
        call = shadow.calls[0]
        assert call["user_message_id"] == result["event_id"]
        assert call["candidates"][0].item_id == seeded["writes"][0]["item_id"]
        assert call["retrieval_strategy"]
        assert runtime.status()["l1_sufficiency_shadow"]["enabled"] is True
    finally:
        backend.close()


def test_l2_sufficiency_shadow_read_failure_does_not_fail_chat(database):
    class BrokenScenarioProvider:
        def recall(self, _query, *, limit=3):
            raise sqlite3.OperationalError("synthetic shadow read failure")

        def close(self):
            pass

    class Shadow:
        def submit(self, **_values):
            raise AssertionError("读取失败后不应提交不真实的空候选")

        def status(self):
            class Status:
                def to_dict(self):
                    return {"enabled": True, "state": "not_run"}
            return Status()

        def wait(self):
            pass

        def close(self):
            pass

    runtime = MemoryRuntime(
        database,
        method=LongMemoryV1(database, existing_only=True),
        scenario_provider=BrokenScenarioProvider(),
        l2_sufficiency_shadow=Shadow(),
    )
    backend = ChatBackend(database, FakeAnswerGenerator(), runtime=runtime)
    try:
        result = backend.run("正常聊天", ())
        assert result["status"] == "completed"
        assert result["scenario_retrieved"] == []
    finally:
        backend.close()


def test_runtime_rejects_unavailable_l2_without_partial_mode_change(database):
    runtime = MemoryRuntime(database, method=LongMemoryV1(database, existing_only=True))
    try:
        with pytest.raises(ValueError, match="scenario_memory_unavailable"):
            runtime.configure(write_enabled=False, use_enabled=False, scenario_use_enabled=True)
        assert runtime.status()["write_enabled"] is True
        assert runtime.status()["use_enabled"] is True
        assert runtime.status()["scenario_use_enabled"] is False
    finally:
        runtime.close()


def test_runtime_l3_use_is_opt_in_shared_and_separately_traced(database):
    class PersonaProvider:
        def recall(self, query, *, limit=3, max_chars=1200):
            assert query == "我平时喜欢喝什么"
            return PersonaRecallResult(
                "以下是与当前问题相关、已有证据支持的用户画像（L3）：\n- 饮品偏好：用户喜欢喝乌龙茶。",
                (PersonaRecallItem(
                    "l3-a", "preference", "user_declared", "饮品偏好",
                    "用户喜欢喝乌龙茶。", (("l1", "l1-a"),), ("l0-a",),
                ),),
            )

        def close(self):
            pass

    runtime = MemoryRuntime(
        database,
        method=LongMemoryV1(database, existing_only=True),
        persona_provider=PersonaProvider(),
    )
    backend = ChatBackend(database, FakeAnswerGenerator(), runtime=runtime)
    try:
        assert backend.run("我平时喜欢喝什么", ())["persona_retrieved"] == []
        runtime.configure(
            write_enabled=True, use_enabled=True, persona_use_enabled=True,
        )
        result = backend.run("我平时喜欢喝什么", ())
        assert result["persona_use_enabled"] is True
        assert result["persona_retrieved"][0]["persona_id"] == "l3-a"
        assert result["persona_retrieved"][0]["source_message_ids"] == ("l0-a",)
        assert "已有证据支持" in result["memory_context"]
    finally:
        backend.close()


def test_paused_write_skips_daily_llm_extraction_but_archives_source(database):
    class MustNotRunProducer:
        def propose(self, **_kwargs):
            raise AssertionError("暂停 L1 写入后不应调用提取模型")

    method = DailyLLMMemory(database, producer=MustNotRunProducer(), allow_cross_thread=True)
    runtime = MemoryRuntime(database, method=method)
    try:
        runtime.configure(write_enabled=False, use_enabled=True)
        prepared = runtime.prepare_user("我喜欢暮雪饮料")
        assert prepared.observation.processing_status == "completed"
        assert prepared.observation.writes == ()
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT count(*) FROM conversation_messages WHERE id=?",
                (prepared.event.event_id,),
            ).fetchone()[0] == 1
            assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 0
    finally:
        runtime.close()
