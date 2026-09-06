"""网页文本闭环：复用方法接口；会话由路由/旁库隔离，不迁移个人库。"""

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from time import monotonic
import sqlite3

from longmemory.application.chat.contracts import AnswerGenerationError
from longmemory.application.memory_runtime import MemoryRuntime
from .role_settings import RoleSettings


class ChatBackend:
    def __init__(self, database: Path, generator, *, provider="fake", model="fake",
                 role="plain_v1", runtime=None):
        self.database = database.resolve()
        self.generator = generator
        self.provider, self.model, self.role = provider, model, role
        self.roles = RoleSettings(self.database, role)
        # 延迟打开让错误仍在一次请求的固定错误边界内返回；生产服务器和
        # 内部语音接口随后复用同一个实例，不再每轮重新装配记忆引擎。
        self._runtime = runtime
        self._runtime_creation_lock = Lock()

    def memory_runtime(self):
        if self._runtime is None:
            with self._runtime_creation_lock:
                if self._runtime is None:
                    self._runtime = MemoryRuntime(self.database)
        return self._runtime

    def info(self):
        role = self.roles.current()
        runtime = self.memory_runtime().status()
        return {"enabled": True, "method": runtime["method"], "subject": "user:self",
                "provider": self.provider, "model": self.model, "role": role['name'], "role_revision": role['revision'],
                "database": str(self.database), "history_persistent": True,
                "speaks_on_device": False}

    def run(self, text, history):
        """在工作线程内复用常驻 Runtime；等待模型时不占记忆锁或写事务。

        返回实际阶段结果：模型失败不撤销已经记住的用户陈述，也不伪装
        为整轮成功。异常仅返回固定代码，不泄漏供应商正文或密钥。
        """
        started = monotonic()
        result = {"status": "failed", "input": text, "answer": None,
                  "started_at": datetime.now(UTC).isoformat(), "method": None,
                  "model": self.model, "role": self.role, "writes": None, "retrieved": None,
                  "memory_context": None, "user_saved": False, "assistant_saved": False,
                  "history_messages": len(history), "memory_processing": None,
                  "memory_warning": None}
        try:
            runtime = self.memory_runtime()
            runtime_status = runtime.status()
            result["method"] = runtime_status["method"]
            # 开始处理时固定本轮角色。保存新版本不改变已经开始的回答。
            role = self.roles.current()
            result.update(role=role['name'], role_revision=role['revision'])
            generator = self.generator
            if role['revision'] and self.provider != 'fake':
                generator = generator.with_role_prompt(role['prompt'])
            prepared = runtime.prepare_user(text)
            event, observed, support = prepared.event, prepared.observation, prepared.support
            result.update(user_saved=True, event_id=event.event_id,
                          writes=[asdict(item) for item in observed.writes],
                          memory_processing=observed.processing_status,
                          memory_warning=observed.warning_code)
            result.update(call_id=support.call_id, memory_context=support.context,
                          retrieved=[asdict(item) for item in support.retrieved])
            # Fake 只验证工程闭环，页面明确标出它不模拟角色/多轮语义能力。
            if self.provider == "fake":
                answer = generator.generate(query=text, memory_context=support.context)
            else:
                answer = generator.generate_turn(query=text, memory_context=support.context, history=history)
            if not isinstance(answer, str) or not answer.strip() or len(answer) > 16000:
                raise AnswerGenerationError("empty_answer")
            result["answer"] = answer
            assistant = runtime.record_assistant(answer)
            result.update(status="completed", assistant_saved=True, assistant_event_id=assistant.event_id)
        except AnswerGenerationError:
            result["error"] = "chat_model_failed"
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
