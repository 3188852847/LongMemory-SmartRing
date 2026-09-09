"""网页文本闭环：复用方法接口；会话由路由/旁库隔离，不迁移个人库。"""

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from time import monotonic
import sqlite3

from longmemory.application.chat.contracts import AnswerGenerationError
from longmemory.application.memory_runtime import MemoryRuntime
from longmemory.application.natural_companion_commands import NaturalCompanionCommandResult
from longmemory.application.natural_memory_commands import NaturalMemoryCommandResult
from longmemory.adapters.storage.sqlite_round_screen_turn_store import (
    SQLiteRoundScreenTurnStore,
)
from longmemory.adapters.storage.sqlite_round_screen_memory_feedback_store import (
    RoundScreenMemoryFeedbackResult,
    SQLiteRoundScreenMemoryFeedbackStore,
)
from longmemory.application.round_screen_memory_feedback import (
    classify_explicit_round_screen_feedback,
)
from longmemory.bootstrap import build_memory_runtime
from .role_settings import RoleSettings


class ChatBackend:
    def __init__(self, database: Path, generator, *, provider="fake", model="fake",
                 role="plain_v1", runtime=None, model_endpoint=None, insecure_model_transport=False):
        self.database = database.resolve()
        self.generator = generator
        self.provider, self.model, self.role = provider, model, role
        # 只保留不含凭据的端点；供本机设置页辨认当前启动配置，绝不返回 API Key。
        self.model_endpoint = model_endpoint if provider != "fake" else None
        self.insecure_model_transport = bool(insecure_model_transport and provider != "fake")
        self.roles = RoleSettings(self.database, role)
        # 延迟打开让错误仍在一次请求的固定错误边界内返回；生产服务器和
        # 内部语音接口随后复用同一个实例，不再每轮重新装配记忆引擎。
        self._runtime = runtime
        self._runtime_creation_lock = Lock()
        self._model_health_lock = Lock()
        self._model_health = {"state": "not_applicable" if provider == "fake" else "unchecked",
                              "code": None, "checked_at": None}

    def _record_model_health(self, state, code=None):
        with self._model_health_lock:
            self._model_health = {"state": state, "code": code,
                                  "checked_at": datetime.now(UTC).isoformat()}

    def model_health(self):
        with self._model_health_lock:
            return dict(self._model_health)

    def check_model(self):
        """显式最小连通性检查：不读取或写入记忆，不发送个人对话，也不自动重试。"""
        if self.provider == "fake":
            return self.model_health()
        try:
            answer = self.generator.generate(query="请只回复：连接正常", memory_context="")
            if not isinstance(answer, str) or not answer.strip():
                raise AnswerGenerationError("模型未返回有效文本。", code="model_response_invalid")
        except AnswerGenerationError as error:
            self._record_model_health("unavailable", error.code)
        else:
            self._record_model_health("available")
        return self.model_health()

    def memory_runtime(self):
        if self._runtime is None:
            with self._runtime_creation_lock:
                if self._runtime is None:
                    self._runtime = build_memory_runtime(self.database)
        return self._runtime

    def complete_round_screen_turn(
        self, *, turn_id, answer, retrieved_counts, retrieval_evidence=None,
    ):
        """归档小智实际生成的回答；关联表与助手 L0 在同一事务提交。"""

        return SQLiteRoundScreenTurnStore(self.database).record(
            user_message_id=turn_id,
            answer=answer,
            retrieved_l1_count=retrieved_counts["l1"],
            retrieved_l2_count=retrieved_counts["l2"],
            retrieved_l3_count=retrieved_counts["l3"],
            retrieval_evidence=retrieval_evidence,
        )

    def prepare_round_screen_user(self, text):
        """准备圆屏输入，并尝试记录对上一轮的严格显式质量反馈。"""

        prepared = self.memory_runtime().prepare_user(text)
        try:
            feedback = SQLiteRoundScreenMemoryFeedbackStore(
                self.database,
            ).record_if_explicit(prepared.event)
        except sqlite3.Error:
            # 质量采集是旁路能力，短暂锁冲突不能让已经完成 L0/召回的
            # 正常语音请求失败；返回稳定状态供内部协议观察，不伪称已记录。
            kind = classify_explicit_round_screen_feedback(text)
            feedback = (
                RoundScreenMemoryFeedbackResult(
                    kind, False, None, "storage_unavailable",
                ) if kind is not None else None
            )
        return prepared, feedback

    def round_screen_memory_feedback(self):
        """读取圆屏反馈的无正文诊断索引。"""

        return SQLiteRoundScreenMemoryFeedbackStore(self.database).list_events()

    def info(self):
        role = self.roles.current()
        runtime = self.memory_runtime().status()
        return {"enabled": True, "method": runtime["method"], "retrieval": runtime["retrieval"],
                "subject": "user:self",
                "provider": self.provider, "model": self.model, "role": role['name'], "role_revision": role['revision'],
                "database": str(self.database), "history_persistent": True,
                "memory_write_enabled": runtime["write_enabled"],
                "memory_use_enabled": runtime["use_enabled"],
                "scenario_use_enabled": runtime["scenario_use_enabled"],
                "scenario_available": runtime["scenario_available"],
                "persona_use_enabled": runtime["persona_use_enabled"],
                "persona_available": runtime["persona_available"],
                "memory_mode_persistent": runtime["settings_persistent"],
                "model_health": self.model_health(),
                "model_endpoint": self.model_endpoint,
                "insecure_model_transport": self.insecure_model_transport,
                "speaks_on_device": False}

    def run(self, text, history):
        """在工作线程内复用常驻 Runtime；等待模型时不占记忆锁或写事务。

        返回实际阶段结果：模型失败不撤销已经记住的用户陈述，也不伪装
        为整轮成功。异常仅返回固定代码，不泄漏供应商正文或密钥。
        """
        started = monotonic()
        result = {"status": "failed", "input": text, "answer": None,
                  "answer_source": None,
                  "started_at": datetime.now(UTC).isoformat(), "method": None,
                  "model": self.model, "role": self.role, "writes": None, "retrieved": None,
                  "memory_context": None, "user_saved": False, "assistant_saved": False,
                  "history_messages": len(history), "memory_processing": None,
                  "memory_warning": None, "retrieval_strategy": None,
                  "retrieval_warning": None, "scenario_retrieved": None,
                  "scenario_use_enabled": False, "persona_retrieved": None,
                  "persona_use_enabled": False, "memory_command": None}
        try:
            runtime = self.memory_runtime()
            runtime_status = runtime.status()
            result["method"] = runtime_status["method"]
            result["memory_write_enabled"] = runtime_status["write_enabled"]
            result["memory_use_enabled"] = runtime_status["use_enabled"]
            result["scenario_use_enabled"] = runtime_status["scenario_use_enabled"]
            result["persona_use_enabled"] = runtime_status["persona_use_enabled"]
            # 开始处理时固定本轮角色。保存新版本不改变已经开始的回答。
            role = self.roles.current()
            result.update(role=role['name'], role_revision=role['revision'])
            generator = self.generator
            if role['revision'] and self.provider != 'fake':
                generator = generator.with_role_prompt(role['prompt'])
            prepared = runtime.prepare_user(text)
            event, observed, support = prepared.event, prepared.observation, prepared.support
            result["memory_write_enabled"] = prepared.write_enabled
            result["memory_use_enabled"] = prepared.use_enabled
            result["scenario_use_enabled"] = prepared.scenario_use_enabled
            result["scenario_retrieved"] = [asdict(item) for item in prepared.scenarios]
            result["persona_use_enabled"] = prepared.persona_use_enabled
            result["persona_retrieved"] = [asdict(item) for item in prepared.personas]
            result["memory_command"] = (asdict(prepared.memory_command)
                                        if prepared.memory_command is not None else None)
            result.update(user_saved=True, event_id=event.event_id,
                          writes=[asdict(item) for item in observed.writes],
                          memory_processing=observed.processing_status,
                          memory_warning=observed.warning_code)
            result.update(call_id=support.call_id, memory_context=support.context,
                          retrieved=[asdict(item) for item in support.retrieved],
                          retrieval_strategy=support.retrieval_strategy,
                          retrieval_warning=support.warning_code)
            # 高精度控制命令已经由应用层完成并生成真实回执。此处不再让
            # 模型改写成功/失败事实，避免网页用户被模型的口头承诺误导。
            # 圆屏的上游接口只能注入系统上下文，仍由独立适配器加强约束。
            if isinstance(prepared.memory_command, (
                NaturalMemoryCommandResult, NaturalCompanionCommandResult,
            )):
                answer = prepared.memory_command.notice
                result["answer_source"] = "application_command"
            # Fake 只验证工程闭环，页面明确标出它不模拟角色/多轮语义能力。
            elif self.provider == "fake":
                answer = generator.generate(query=text, memory_context=support.context)
                result["answer_source"] = "model"
            else:
                answer = generator.generate_turn(query=text, memory_context=support.context, history=history)
                result["answer_source"] = "model"
            if not isinstance(answer, str) or not answer.strip() or len(answer) > 16000:
                raise AnswerGenerationError("empty_answer", code="model_response_invalid")
            self._record_model_health("available")
            result["answer"] = answer
            assistant = runtime.record_assistant(answer)
            result.update(status="completed", assistant_saved=True, assistant_event_id=assistant.event_id)
        except AnswerGenerationError as error:
            result["error"] = error.code
            self._record_model_health("unavailable", error.code)
        except sqlite3.Error as error:
            code = getattr(error, "sqlite_errorcode", 0) & 0xFF
            result["error"] = "memory_busy" if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} else "chat_database_unavailable"
        except ValueError:
            result["error"] = "chat_database_or_configuration_invalid"
        except Exception:
            result["error"] = "chat_internal_error"
        result["duration_ms"] = round((monotonic() - started) * 1000)
        return result

    def close(self):
        """关闭自己拥有或被注入的运行时；不删除任何持久数据。"""
        if self._runtime is not None:
            self._runtime.close()
