"""网页记忆管理的装配边界：只打开显式指定的已有数据库，不运行建库/迁移。"""

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from longmemory.adapters.storage.sqlite_conversation_store import SQLiteConversationStore
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.application.memory_management.service import MemoryManagementService
from longmemory.infrastructure.database.schema import SCHEMA_VERSION
from .errors import MemoryAccessError
from .scenario_backend import ScenarioBackend
from .persona_backend import PersonaBackend
from .proactive_backend import ProactiveBackend
from .companion_learning_backend import CompanionLearningBackend
from .proactive_runtime_backend import ProactiveRuntimeBackend
from .atomic_memory_backend import AtomicMemoryBackend


class MemoryBackend:
    def __init__(self, database: Path | None, *, allow_delete=False, allow_correction=False,
                 allow_scenario_management=False, allow_persona_management=False,
                 scenario_producer=None,
                 scenario_model=None, persona_producer=None, persona_model=None,
                 consolidation_background_enabled=False, clock=None):
        # 路径只来自启动参数；任何 HTTP 请求都不能选文件或切换数据库。
        self.database = database.resolve() if database is not None else None
        self.allow_delete = allow_delete
        self.allow_correction = allow_correction
        self.allow_scenario_management = allow_scenario_management
        self.allow_persona_management = allow_persona_management
        self.scenario_producer = scenario_producer
        self.scenario_model = scenario_model
        self.persona_producer = persona_producer
        self.persona_model = persona_model
        self.consolidation_background_enabled = consolidation_background_enabled
        self.clock = clock or (lambda: datetime.now(UTC))
        self.scenarios = ScenarioBackend(
            open_database=self._open,
            allow_management=self.allow_scenario_management,
            producer=self.scenario_producer,
            model=self.scenario_model,
        )
        self.personas = PersonaBackend(
            open_database=self._open,
            allow_management=self.allow_persona_management,
            producer=self.persona_producer,
            model=self.persona_model,
        )
        self.proactive = ProactiveBackend(
            open_database=self._open,
            clock=self.clock,
            memory_service_factory=self._service,
        )
        self.companion_learning = CompanionLearningBackend(
            open_database=self._open,
            clock=self.clock,
        )
        self.proactive_runtime = ProactiveRuntimeBackend(
            open_database=self._open,
            clock=self.clock,
        )
        self.atomic_memories = AtomicMemoryBackend(
            open_database=self._open,
            service_factory=self._service,
            clock=self.clock,
            consolidation_background_enabled=self.consolidation_background_enabled,
        )

    def info(self):
        return {"configured": self.database is not None,
                "database": str(self.database) if self.database else None,
                "allow_delete": self.allow_delete and self.database is not None,
                "allow_clear": self.allow_delete and self.database is not None,
                "allow_correction": self.allow_correction and self.database is not None,
                # 当前两个操作共用同一个显式启动权限，但对前端公开独立能力名，
                # 以后拆分权限时不需要再改变页面语义。
                "allow_change": self.allow_correction and self.database is not None,
                "allow_promote_source": self.allow_correction and self.database is not None,
                "allow_l1_quality_review": self.allow_correction and self.database is not None,
                "allow_scenario_management": (
                    self.allow_scenario_management and self.database is not None
                ),
                "allow_persona_management": (
                    self.allow_persona_management and self.database is not None
                ),
                "scenario_model_preview_available": (
                    self.allow_scenario_management
                    and self.database is not None
                    and self.scenario_producer is not None
                ),
                "scenario_model": self.scenario_model if self.scenario_producer else None,
                "persona_model_preview_available": (
                    self.allow_persona_management
                    and self.database is not None
                    and self.persona_producer is not None
                ),
                "persona_model": self.persona_model if self.persona_producer else None}

    def proactive_policy(self):
        return self.proactive.policy()

    def proactive_schedule_status(self):
        """解释今天的定时触发条件；只读时间与状态，不读取对话正文。"""

        return self.proactive.schedule_status()

    def arm_proactive_schedule_override(self, request):
        """仅授权今天当前设置中的未来时刻；不立即投递。"""

        return self.proactive.arm_schedule_override(request)

    def cancel_proactive_schedule_override(
        self, override_id, *, expected_revision,
    ):
        return self.proactive.cancel_schedule_override(
            override_id, expected_revision=expected_revision,
        )

    def list_proactive_topic_seeds(self):
        return self.proactive.list_topic_seeds()

    def create_proactive_topic_seed(self, request):
        return self.proactive.create_topic_seed(request)

    def disable_proactive_topic_seed(self, seed_id, *, expected_revision):
        return self.proactive.disable_topic_seed(
            seed_id, expected_revision=expected_revision,
        )

    def list_follow_up_candidates(self):
        return self.proactive.list_follow_ups()

    def create_follow_up_candidate(self, request):
        return self.proactive.create_follow_up(request)

    def cancel_follow_up_candidate(self, candidate_id, *, expected_revision):
        return self.proactive.cancel_follow_up(
            candidate_id, expected_revision=expected_revision,
        )

    def arm_follow_up_candidate(
        self, candidate_id, *, expected_revision, expected_policy_revision,
    ):
        """显式建立未来账本；这里不探测设备，也不产生任何即时播报。"""

        return self.proactive.arm_follow_up(
            candidate_id,
            expected_revision=expected_revision,
            expected_policy_revision=expected_policy_revision,
        )

    def update_proactive_policy(self, request):
        return self.proactive.update_policy(request)

    async def proactive_test(self, request, client):
        """执行一次用户明确发起的短文本测试；同 request_id 绝不重播。"""

        return await self.proactive_runtime.manual_test(request, client)

    async def proactive_scheduled_tick(self, client):
        """评估当前当地分钟一次；不补发、不调用模型、不自动重试投递。"""

        return await self.proactive_runtime.scheduled_tick(client)
    def _current_absence_decision(self, connection, *, subject_id, now):
        """兼容测试入口；实际决策归主动交流运行期协作者。"""

        return self.proactive_runtime._current_absence_decision(
            connection, subject_id=subject_id, now=now,
        )

    async def proactive_absence_tick(self, client):
        """评估当前激活的缺席策略一次；不补发、不调用模型。"""

        return await self.proactive_runtime.absence_tick(client)
    async def proactive_follow_up_tick(self, client):
        """执行最早一条已到时间的已启用事项；终止后绝不补发。"""

        return await self.proactive_runtime.follow_up_tick(client)

    async def proactive_background_tick(self, client):
        """按明确事项、固定定时、习惯缺席的优先级组合三类来源。"""

        return await self.proactive_runtime.background_tick(client)
    def proactive_history(self, *, limit=20):
        """只读最近投影和最后事件原因，不暴露幂等键或内部连接数据。"""

        return self.proactive.history(limit=limit)

    def list_companion_strategy_candidates(self):
        return self.companion_learning.list_strategy_candidates()

    def list_user_initiated_interactions(self, *, limit=30):
        """只返回时间与来源 ID，不把私人消息正文复制到观察视图。"""

        return self.companion_learning.list_user_initiated_interactions(
            limit=limit,
        )

    def list_companion_routine_candidates(self):
        return self.companion_learning.list_routine_candidates()

    def generate_companion_routine_candidate(self):
        """分析用户主动出现时间；不把候选变成联系规则。"""

        return self.companion_learning.generate_routine_candidate()

    def dismiss_companion_routine_candidate(
        self, candidate_id, *, expected_revision,
    ):
        return self.companion_learning.dismiss_routine_candidate(
            candidate_id, expected_revision=expected_revision,
        )

    def list_companion_absence_strategy_versions(self):
        return self.companion_learning.list_absence_strategy_versions()

    def select_companion_absence_strategy_version(self, request, *, rollback=False):
        return self.companion_learning.select_absence_strategy_version(
            request, rollback=rollback,
        )

    def deactivate_companion_absence_strategy(self, request):
        return self.companion_learning.deactivate_absence_strategy(request)

    def create_companion_absence_strategy_version(self, request):
        """保存回放绑定草案；当前没有激活指针或调度接线。"""

        return self.companion_learning.create_absence_strategy_version(request)

    def generate_companion_strategy_candidate(self):
        """只生成未生效候选；不读取消息正文、不修改 P4 设置。"""

        return self.companion_learning.generate_strategy_candidate()

    def dismiss_companion_strategy_candidate(
        self, candidate_id, *, expected_revision,
    ):
        return self.companion_learning.dismiss_strategy_candidate(
            candidate_id, expected_revision=expected_revision,
        )

    def confirm_proactive_played(self, outreach_id, *, expected_revision):
        """把所有者亲耳观察追加为证据；不从设备状态反推播放成功。"""

        return self.proactive.confirm_played(
            outreach_id, expected_revision=expected_revision,
        )

    @contextmanager
    def _open(self, *, write_capability=None):
        if self.database is None:
            raise MemoryAccessError("memory_not_configured", 503)
        if not self.database.is_file():
            raise MemoryAccessError("memory_database_missing", 503)
        if write_capability == "delete" and not self.allow_delete:
            raise MemoryAccessError("memory_read_only", 403)
        if write_capability == "correction" and not self.allow_correction:
            raise MemoryAccessError("memory_correction_disabled", 403)
        if write_capability == "scenario" and not self.allow_scenario_management:
            raise MemoryAccessError("scenario_management_disabled", 403)
        if write_capability == "persona" and not self.allow_persona_management:
            raise MemoryAccessError("persona_management_disabled", 403)
        connection = None
        try:
            # mode=ro/rw 都不创建文件；不用 open_database 或 build_application，
            # 因为它们会初始化/迁移。连接在请求工作线程内创建并关闭。
            write = write_capability is not None
            mode = "rw" if write else "ro"
            connection = sqlite3.connect(self.database.as_uri() + "?mode=" + mode, uri=True, timeout=2)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            if not write:
                connection.execute("PRAGMA query_only = ON")
            # 删除先持有写锁，再检查快照和删除，避免核对后又被别的进程改动。
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise MemoryAccessError("memory_schema_unsupported")
            yield connection
        except sqlite3.OperationalError as error:
            primary_code = getattr(error, "sqlite_errorcode", 0) & 0xFF
            code = "memory_busy" if primary_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} else "memory_database_unavailable"
            raise MemoryAccessError(code, 503) from None
        except (sqlite3.DatabaseError, ValueError, KeyError, TypeError):
            raise MemoryAccessError("memory_database_invalid", 503) from None
        finally:
            if connection is not None:
                # 未提交的读事务、失败写事务均在关闭时回滚；成功删除沿用原用例提交。
                connection.close()

    @staticmethod
    def _service(connection, *, commit_changes=True):
        return MemoryManagementService(
            memory_store=SQLiteMemoryStore(connection, commit_changes=commit_changes),
            conversation_store=SQLiteConversationStore(connection, commit_changes=commit_changes),
        )

    def list_page(self, *, query="", state="active", limit=25, offset=0):
        return self.atomic_memories.list_page(
            query=query, state=state, limit=limit, offset=offset,
        )

    def quality_candidates(self):
        return self.atomic_memories.quality_candidates()

    def review_quality_candidate(self, **kwargs):
        return self.atomic_memories.review_quality_candidate(**kwargs)

    @staticmethod
    def _local_day_window(local_date, utc_offset_minutes):
        return AtomicMemoryBackend._local_day_window(
            local_date, utc_offset_minutes,
        )

    def daily_review(self, *, local_date, utc_offset_minutes):
        return self.atomic_memories.daily_review(
            local_date=local_date,
            utc_offset_minutes=utc_offset_minutes,
        )

    def consolidation_status(self):
        return self.atomic_memories.consolidation_status()

    @staticmethod
    def _consolidation_status_json(item):
        return AtomicMemoryBackend._consolidation_status_json(item)

    def list_sources(
        self, *, query="", role="all", link_state="all", limit=25, offset=0,
        local_date=None, utc_offset_minutes=None,
    ):
        return self.atomic_memories.list_sources(
            query=query, role=role, link_state=link_state,
            limit=limit, offset=offset, local_date=local_date,
            utc_offset_minutes=utc_offset_minutes,
        )

    def get_source(self, source_id):
        return self.atomic_memories.get_source(source_id)

    @staticmethod
    def _source_json(connection, source_id):
        return AtomicMemoryBackend._source_json(connection, source_id)

    def promote_source(self, source_id, content, expected_revision):
        return self.atomic_memories.promote_source(
            source_id, content, expected_revision,
        )

    def get(self, memory_id):
        return self.atomic_memories.get(memory_id)

    def wipe_preview(self):
        return self.atomic_memories.wipe_preview()

    def _backup_before_wipe(self):
        """创建当前 SQLite 的一致性恢复点；不覆盖、删除任何既有备份。"""

        if not self.allow_delete or self.database is None:
            raise MemoryAccessError("memory_read_only", 403)
        backup_root = (self.database.parent.parent / "backups"
                       if self.database.parent.name == "databases"
                       else self.database.parent / "backups")
        backup_root.mkdir(parents=True, exist_ok=True)
        stamp = self.clock().astimezone(UTC).strftime("%Y%m%d-%H%M%S")
        backup = backup_root / f"{self.database.stem}-pre-memory-wipe-{stamp}-{uuid4().hex[:8]}.db"
        source = destination = None
        try:
            source = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=2)
            destination = sqlite3.connect(backup)
            source.backup(destination)
            if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("backup check failed")
            destination.close(); destination = None
            source.close(); source = None
            digest = hashlib.sha256(backup.read_bytes()).hexdigest()
            return {"path": str(backup), "sha256": digest}
        except (OSError, sqlite3.DatabaseError):
            raise MemoryAccessError("memory_backup_failed", 503) from None
        finally:
            if destination is not None:
                destination.close()
            if source is not None:
                source.close()

    def wipe_memories(self, expected_revision):
        backup = self._backup_before_wipe()
        result = self.atomic_memories.wipe_memories(expected_revision)
        return {**result, "backup": backup}

    def delete(self, memory_id, expected_revision):
        return self.atomic_memories.delete(memory_id, expected_revision)

    @staticmethod
    def _clear_snapshot(connection):
        return AtomicMemoryBackend._clear_snapshot(connection)

    def clear_preview(self):
        return self.atomic_memories.clear_preview()

    def clear_memories(self, expected_revision):
        return self.atomic_memories.clear_memories(expected_revision)

    def correct(self, memory_id, corrected_content, expected_revision):
        return self.atomic_memories.correct(
            memory_id, corrected_content, expected_revision,
        )

    def record_change(
        self, memory_id, new_content, effective_at, expected_revision,
    ):
        return self.atomic_memories.record_change(
            memory_id, new_content, effective_at, expected_revision,
        )
    def list_scenarios(self, *, state="all", limit=25, offset=0):
        return self.scenarios.list(state=state, limit=limit, offset=offset)

    def list_scenario_source_inbox(self):
        return self.scenarios.list_source_inbox()

    def get_scenario(self, scenario_id):
        return self.scenarios.get(scenario_id)

    def preview_scenario(self, *, source_memory_ids):
        return self.scenarios.preview(source_memory_ids=source_memory_ids)

    def create_scenario(self, *, title, summary, source_memory_ids, creation_kind="manual",
                        valid_from=None, valid_to=None):
        return self.scenarios.create(
            title=title,
            summary=summary,
            source_memory_ids=source_memory_ids,
            creation_kind=creation_kind,
            valid_from=valid_from,
            valid_to=valid_to,
        )

    def review_scenario(self, scenario_id, *, decision, expected_revision):
        return self.scenarios.review(
            scenario_id, decision=decision, expected_revision=expected_revision,
        )

    def end_scenario(self, scenario_id, *, expected_revision):
        return self.scenarios.end(scenario_id, expected_revision=expected_revision)

    def list_personas(self, *, state="all", limit=25, offset=0):
        return self.personas.list(state=state, limit=limit, offset=offset)

    def get_persona_profile(self):
        return self.personas.profile()

    def list_persona_source_options(self):
        return self.personas.list_source_options()

    def get_persona(self, persona_id):
        return self.personas.get(persona_id)

    def create_persona(self, *, kind, basis, label, statement, sources,
                       valid_from=None, valid_to=None, creation_kind="manual",
                       replaces=()):
        return self.personas.create(
            kind=kind,
            basis=basis,
            label=label,
            statement=statement,
            sources=sources,
            valid_from=valid_from,
            valid_to=valid_to,
            creation_kind=creation_kind,
            replaces=replaces,
        )

    def preview_persona(self, *, basis, sources):
        return self.personas.preview(basis=basis, sources=sources)

    def preview_persona_consolidation(self, *, basis, sources):
        return self.personas.preview_consolidation(basis=basis, sources=sources)

    def review_persona(self, persona_id, *, decision, expected_revision):
        return self.personas.review(
            persona_id, decision=decision, expected_revision=expected_revision,
        )
