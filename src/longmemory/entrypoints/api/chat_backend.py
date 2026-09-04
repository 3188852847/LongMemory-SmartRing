"""网页文本闭环：复用方法接口；会话由路由/旁库隔离，不迁移个人库。"""

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import uuid4
import sqlite3

from longmemory.application.chat.contracts import AnswerGenerationError
from longmemory.methods.contracts import MemoryEvent
from longmemory.methods.longmemory_v1.method import LongMemoryV1


class ChatBackend:
    def __init__(self, database: Path, generator, *, provider="fake", model="fake", role="plain_v1"):
        self.database = database.resolve()
        self.generator = generator
        self.provider, self.model, self.role = provider, model, role

    def info(self):
        return {"enabled": True, "method": "longmemory_v1", "subject": "user:self",
                "provider": self.provider, "model": self.model, "role": self.role,
                "database": str(self.database), "history_persistent": True,
                "speaks_on_device": False}

    def run(self, text, history):
        """在工作线程内创建、使用和关闭 SQLite；等待模型时不占写事务。

        返回实际阶段结果：模型失败不撤销已经记住的用户陈述，也不伪装
        为整轮成功。异常仅返回固定代码，不泄漏供应商正文或密钥。
        """
        started = monotonic()
        result = {"status": "failed", "input": text, "answer": None,
                  "started_at": datetime.now(UTC).isoformat(), "method": "longmemory_v1",
                  "model": self.model, "role": self.role, "writes": None, "retrieved": None,
                  "memory_context": None, "user_saved": False, "assistant_saved": False,
                  "history_messages": len(history)}
        method = None
        try:
            method = LongMemoryV1(self.database, existing_only=True)
            event = MemoryEvent(str(uuid4()), "user", text, datetime.now(UTC))
            observed = method.observe(event)
            result.update(user_saved=True, event_id=event.event_id,
                          writes=[asdict(item) for item in observed.writes])
            support = method.recall(text)
            result.update(call_id=support.call_id, memory_context=support.context,
                          retrieved=[asdict(item) for item in support.retrieved])
            # Fake 只验证工程闭环，页面明确标出它不模拟角色/多轮语义能力。
            if self.provider == "fake":
                answer = self.generator.generate(query=text, memory_context=support.context)
            else:
                answer = self.generator.generate_turn(query=text, memory_context=support.context, history=history)
            if not isinstance(answer, str) or not answer.strip() or len(answer) > 16000:
                raise AnswerGenerationError("empty_answer")
            result["answer"] = answer
            assistant = MemoryEvent(str(uuid4()), "assistant", answer, datetime.now(UTC))
            method.observe(assistant)  # 只归档助手角色，绝不提取成用户事实。
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
        finally:
            if method is not None:
                method.close()
        result["duration_ms"] = round((monotonic() - started) * 1000)
        return result
