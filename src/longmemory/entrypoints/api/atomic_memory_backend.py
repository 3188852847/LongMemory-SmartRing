"""L0 来源与 L1 原子记忆的管理边界。

该协作者复用总装配器提供的数据库会话与能力守卫，不自行选择数据库，因而页面
无法借由拆分绕过只读、删除或纠正权限。L2/L3 仍由各自协作者管理。
"""

import secrets
from datetime import UTC, datetime, timedelta, timezone

from longmemory.adapters.storage.sqlite_consolidation_run_store import (
    SQLiteConsolidationRunStore,
)
from longmemory.adapters.storage.sqlite_l1_consolidation_source_reader import (
    SQLiteL1ConsolidationSourceReader,
)
from longmemory.adapters.storage.sqlite_l2_consolidation_source_reader import (
    SQLiteL2ConsolidationSourceReader,
)
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.application.consolidation.l2_to_l3_service import L3_TRIGGER_CONFIG
from longmemory.application.consolidation.status_service import (
    ConsolidationStatusService,
)
from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.memory.consolidation.trigger_policy import (
    ConsolidationTriggerConfig,
)
from longmemory.core.memory.l1_atomic.models import CURRENT_USER_SUBJECT_ID
from longmemory.core.memory.quality.l1_candidates import find_l1_quality_candidates
from longmemory.core.memory.retrieval.service import is_memory_effective

from .errors import MemoryAccessError
from .memory_presenters import details_json, memory_json, revision


class AtomicMemoryBackend:
    """提供 L0/L1 管理用例，同时保持现有 HTTP 返回结构。"""

    def __init__(
        self,
        *,
        open_database,
        service_factory,
        clock,
        consolidation_background_enabled,
    ):
        self._open_database = open_database
        self._service_factory = service_factory
        self._clock = clock
        self._consolidation_background_enabled = consolidation_background_enabled


    def list_page(self, *, query="", state="active", limit=25, offset=0):
        with self._open_database() as connection:
            total, items = SQLiteMemoryStore(connection).list_page(query=query, state=state, limit=limit, offset=offset)
            summaries = []
            for item in items:
                row = memory_json(item)
                row["content"] = item.content[:240]
                row["truncated"] = len(item.content) > 240
                summaries.append(row)
            return {"items": summaries, "total": total, "limit": limit, "offset": offset}

    def quality_candidates(self):
        """只读发现疑似重复/矛盾 L1；不调用模型，也不改变个人记忆。"""

        maximum_memories = 500
        with self._open_database() as connection:
            now = self._clock()
            active = tuple(
                memory for memory in SQLiteMemoryStore(connection).list_active()
                if is_memory_effective(memory, now)
            )
            scanned = active[:maximum_memories]
            candidates = find_l1_quality_candidates(scanned)
            return {
                "items": [
                    {
                        "kind": item.kind,
                        "similarity": round(item.similarity, 4),
                        "reason": item.reason,
                        "left": memory_json(item.left),
                        "right": memory_json(item.right),
                    }
                    for item in candidates
                ],
                "total": len(candidates),
                "scanned_memory_count": len(scanned),
                "memory_scan_limited": len(active) > len(scanned),
                "candidate_limit": 100,
                "candidate_limit_reached": len(candidates) == 100,
                "lexical_threshold": 0.72,
                "generated_at": now.isoformat(),
            }

    @staticmethod
    def _local_day_window(local_date, utc_offset_minutes):
        """把浏览器自然日转换成半开 UTC 区间，供多个只读视图共用。"""
        try:
            day = datetime.strptime(local_date, "%Y-%m-%d").date()
            offset = timezone(timedelta(minutes=utc_offset_minutes))
            start = datetime.combine(day, datetime.min.time(), tzinfo=offset).astimezone(UTC)
        except (TypeError, ValueError, OverflowError):
            raise MemoryAccessError("invalid_daily_review_window", 400) from None
        return start, start + timedelta(days=1)

    def daily_review(self, *, local_date, utc_offset_minutes):
        """返回某个本地自然日写入的 L1；读取不触发整理、提取或迁移。"""
        start, end = self._local_day_window(local_date, utc_offset_minutes)
        with self._open_database() as connection:
            store = SQLiteMemoryStore(connection)
            items = store.list_recorded_between(start, end)
            summaries = []
            activity_counts = {"added": 0, "corrected": 0, "changed": 0, "deleted": 0}
            for item in items:
                row = memory_json(item)
                row["content"] = item.content[:240]
                row["truncated"] = len(item.content) > 240
                source_types = {
                    evidence.source_type.value for evidence in store.list_evidence(item.id)
                }
                # 当前数据模型只有“纠错”具备专门证据类型；事实变化则由新
                # L1 的 valid_from 表达。删除后 L1 已不存在，因此这里不伪造
                # 一条无法从现有数据库可靠还原的“删除活动”。
                if "user_corrected" in source_types:
                    activity = "corrected"
                elif item.valid_from is not None:
                    activity = "changed"
                else:
                    activity = "added"
                row["activity"] = activity
                activity_counts[activity] += 1
                summaries.append(row)
            deletion_total = connection.execute(
                "SELECT count(*) FROM l1_deletion_events "
                "WHERE deleted_at >= ? AND deleted_at < ?",
                (start.isoformat(), end.isoformat()),
            ).fetchone()[0]
            deletion_rows = connection.execute(
                "SELECT id,memory_id,subject_id,deleted_at FROM l1_deletion_events "
                "WHERE deleted_at >= ? AND deleted_at < ? "
                "ORDER BY deleted_at DESC,id DESC LIMIT 100",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
            activity_counts["deleted"] = deletion_total
            message_rows = connection.execute(
                "SELECT role,count(*) AS count FROM conversation_messages "
                "WHERE created_at >= ? AND created_at < ? GROUP BY role",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
            message_counts = {"user": 0, "assistant": 0, "total": 0, "unlinked_user": 0}
            for row in message_rows:
                message_counts[row["role"]] = row["count"]
                message_counts["total"] += row["count"]
            message_counts["unlinked_user"] = connection.execute(
                "SELECT count(*) FROM conversation_messages m "
                "WHERE m.role='user' AND m.created_at >= ? AND m.created_at < ? "
                "AND NOT EXISTS (SELECT 1 FROM memory_evidence e WHERE e.source_message_id=m.id)",
                (start.isoformat(), end.isoformat()),
            ).fetchone()[0]
            confirmed_missed = connection.execute(
                "SELECT count(*) FROM memory_quality_events "
                "WHERE event_kind='owner_confirmed_missed_extraction' "
                "AND occurred_at >= ? AND occurred_at < ?",
                (start.isoformat(), end.isoformat()),
            ).fetchone()[0]
            return {"local_date":local_date,"utc_offset_minutes":utc_offset_minutes,
                    "items":summaries,"total":len(summaries),"limited":len(summaries)==100,
                    "activity_counts":activity_counts,
                    "message_counts":message_counts,
                    "quality_counts":{"owner_confirmed_missed_extraction":confirmed_missed},
                    "deletions":[dict(row) for row in deletion_rows],
                    "deletions_limited":deletion_total > len(deletion_rows)}

    def consolidation_status(self):
        """只读呈现自动整理门槛和账本；不会借查询触发模型或迁移。"""

        with self._open_database() as connection:
            now = datetime.now(UTC)
            store = SQLiteConsolidationRunStore(connection, commit_changes=False)
            statuses = ConsolidationStatusService(
                run_store=store,
                l1_reader=SQLiteL1ConsolidationSourceReader(connection),
                l2_reader=SQLiteL2ConsolidationSourceReader(connection),
                l1_config=ConsolidationTriggerConfig(),
                l2_config=L3_TRIGGER_CONFIG,
            ).inspect(str(CURRENT_USER_SUBJECT_ID), now=now)
            return {
                "subject_id": str(CURRENT_USER_SUBJECT_ID),
                "observed_at": now.isoformat(),
                "background_enabled": self._consolidation_background_enabled,
                "stages": [self._consolidation_status_json(item) for item in statuses],
            }

    @staticmethod
    def _consolidation_status_json(item):
        cursor = item.cursor
        latest = item.latest_run
        return {
            "stage": item.stage.value,
            "pending_new_source_count": item.pending_new_source_count,
            "trigger_action": item.trigger_action,
            "trigger_reason": item.trigger_reason,
            "minimum_new_sources": item.minimum_new_sources,
            "maximum_sources_per_run": item.maximum_sources_per_run,
            "cooldown_seconds": item.cooldown_seconds,
            "daily_model_call_budget": item.daily_model_call_budget,
            "model_calls_today": item.model_calls_today,
            "remaining_model_calls_today": max(
                0, item.daily_model_call_budget - item.model_calls_today,
            ),
            "cursor": None if cursor is None else {
                "recorded_at": cursor.recorded_at.isoformat(),
                "source_id": cursor.source_id,
            },
            "latest_run": None if latest is None else {
                "id": latest.id,
                "trigger": latest.trigger.value,
                "status": latest.status.value,
                "started_at": latest.started_at.isoformat(),
                "finished_at": (
                    latest.finished_at.isoformat() if latest.finished_at else None
                ),
                "outcome_code": latest.outcome_code,
                "source_count": latest.source_count,
                "model_call_count": latest.model_call_count,
                "risk_reviewer_version": latest.risk_reviewer_version,
            },
        }

    def list_sources(self, *, query="", role="all", link_state="all", limit=25, offset=0,
                     local_date=None, utc_offset_minutes=None):
        """分页读取 L0，并明确它是否已经成为任意 L1 的证据。"""

        if (local_date is None) != (utc_offset_minutes is None):
            raise MemoryAccessError("invalid_daily_review_window", 400)
        day_window = (
            self._local_day_window(local_date, utc_offset_minutes)
            if local_date is not None else None
        )
        with self._open_database() as connection:
            clauses, parameters = [], []
            if query:
                clauses.append("instr(lower(m.content), lower(?)) > 0")
                parameters.append(query)
            if role != "all":
                clauses.append("m.role = ?")
                parameters.append(role)
            linked = "EXISTS (SELECT 1 FROM memory_evidence e WHERE e.source_message_id = m.id)"
            if link_state == "linked":
                clauses.append(linked)
            elif link_state == "unlinked":
                clauses.append("NOT " + linked)
            if day_window is not None:
                start, end = day_window
                clauses.extend(("m.created_at >= ?", "m.created_at < ?"))
                parameters.extend((start.isoformat(), end.isoformat()))
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            total = connection.execute(
                "SELECT count(*) FROM conversation_messages m" + where,
                parameters,
            ).fetchone()[0]
            rows = connection.execute(
                """
                SELECT m.id, m.role, m.content, m.created_at,
                       count(DISTINCT e.memory_id) AS linked_memory_count
                FROM conversation_messages m
                LEFT JOIN memory_evidence e ON e.source_message_id = m.id
                """ + where + """
                GROUP BY m.id, m.role, m.content, m.created_at
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            ).fetchall()
            items = [{
                "id": row["id"],
                "role": row["role"],
                "content": row["content"][:240],
                "truncated": len(row["content"]) > 240,
                "created_at": row["created_at"],
                "linked_memory_count": row["linked_memory_count"],
            } for row in rows]
            return {"items": items, "total": total, "limit": limit, "offset": offset}

    def get_source(self, source_id):
        """读取一条 L0 原文及其派生 L1；未关联也必须作为真实状态返回。"""

        with self._open_database() as connection:
            return self._source_json(connection, source_id)

    @staticmethod
    def _source_json(connection, source_id):
        source = connection.execute(
            "SELECT id, role, content, created_at FROM conversation_messages WHERE id = ?",
            (source_id,),
        ).fetchone()
        if source is None:
            raise MemoryAccessError("source_message_not_found", 404)
        rows = connection.execute(
            """
            SELECT a.*, e.source_type, e.linked_at
            FROM memory_evidence e
            JOIN atomic_memories a ON a.id = e.memory_id
            WHERE e.source_message_id = ?
            ORDER BY e.linked_at DESC, a.id DESC
            """,
            (source_id,),
        ).fetchall()
        derived = []
        for row in rows:
            item = {
                "id": row["id"], "subject_id": row["subject_id"], "content": row["content"],
                **{key: row[key] for key in ("recorded_at", "valid_from", "valid_to", "retired_at")},
                "superseded_by_id": row["superseded_by_id"],
                "state": "retired" if row["retired_at"] else "active",
            }
            item.update(source_type=row["source_type"], linked_at=row["linked_at"])
            derived.append(item)
        data = {
            "id": source["id"], "role": source["role"], "content": source["content"],
            "created_at": source["created_at"], "derived_memories": derived,
        }
        return {**data, "revision": revision(data)}

    def promote_source(self, source_id, content, expected_revision):
        """把已核对的用户 L0 补成 L1；同内容当前事实只增加证据。"""

        with self._open_database(write_capability="correction") as connection:
            current = self._source_json(connection, source_id)
            if not secrets.compare_digest(current["revision"], expected_revision):
                raise MemoryAccessError("source_message_changed")
            occurred_at = self._clock()
            try:
                result = self._service_factory(
                    connection, commit_changes=False,
                ).promote_source_to_memory(
                    MessageId(source_id), content, occurred_at=occurred_at,
                )
            except LookupError:
                raise MemoryAccessError("source_message_not_found", 404) from None
            except ValueError as error:
                code = str(error)
                status = 400 if code.startswith("promoted_content_") else 409
                raise MemoryAccessError(code, status) from None
            except RuntimeError as error:
                if str(error) == "source_promotion_race":
                    raise MemoryAccessError("source_message_changed") from None
                raise
            # 这是所有者显式确认的“漏记”质量信号，与 L1 写入同事务。
            # 只存身份、解决方式和时间，避免再复制一份个人正文。
            connection.execute(
                "INSERT INTO memory_quality_events "
                "(id,event_kind,source_message_id,memory_id,resolution,occurred_at) "
                "VALUES (lower(hex(randomblob(16))),?,?,?,?,?)",
                (
                    "owner_confirmed_missed_extraction",
                    str(result.source_message.id),
                    str(result.memory.id),
                    "created" if result.created_new_memory else "evidence_added",
                    occurred_at.isoformat(),
                ),
            )
            connection.commit()
            return {
                "promoted": True,
                "memory_id": str(result.memory.id),
                "source_message_id": str(result.source_message.id),
                "created_new_memory": result.created_new_memory,
            }

    def get(self, memory_id):
        with self._open_database() as connection:
            details = self._service_factory(connection).get_memory(MemoryId(memory_id))
            if details is None:
                raise MemoryAccessError("memory_not_found", 404)
            data = details_json(details)
            return {**data, "revision": revision(data)}

    def delete(self, memory_id, expected_revision):
        with self._open_database(write_capability="delete") as connection:
            service = self._service_factory(connection, commit_changes=False)
            details = service.get_memory(MemoryId(memory_id))
            if details is None:
                raise MemoryAccessError("memory_not_found", 404)
            if not secrets.compare_digest(revision(details_json(details)), expected_revision):
                raise MemoryAccessError("memory_changed")
            # 复用已经测试过的语义：删除 L1 + 来源关联，保留 L0 原始对话。
            # 外键还会解除其他记忆指向此条的取代链接，不冒充完整隐私擦除。
            if not service.delete_memory(MemoryId(memory_id)):
                raise MemoryAccessError("memory_not_found", 404)
            connection.commit()
            return {"deleted": True, "id": memory_id, "l0_preserved": True}

    @staticmethod
    def _clear_snapshot(connection):
        """生成不含正文的清空预检快照，并用身份列表防止过期页面误删。"""

        rows = connection.execute(
            "SELECT id, retired_at FROM atomic_memories ORDER BY id"
        ).fetchall()
        l1_identities = [
            {"id": row["id"], "retired_at": row["retired_at"]}
            for row in rows
        ]
        snapshot = {
            # 清空确认期间，即使只是某条 L1 的生命周期发生变化，也必须使
            # 旧预检失效，不能让页面拿着过期影响范围继续执行批量删除。
            "l1_identities": l1_identities,
            "l2_current": connection.execute(
                "SELECT count(*) FROM scenario_memories "
                "WHERE status IN ('candidate','active')"
            ).fetchone()[0],
            "l3_current": connection.execute(
                "SELECT count(*) FROM persona_memories "
                "WHERE status IN ('candidate','active')"
            ).fetchone()[0],
            "l0_preserved": connection.execute(
                "SELECT count(*) FROM conversation_messages"
            ).fetchone()[0],
        }
        return {
            "l1_total": len(l1_identities),
            "l1_active": sum(row["retired_at"] is None for row in rows),
            "l1_retired": sum(row["retired_at"] is not None for row in rows),
            "affected_l2_current": snapshot["l2_current"],
            "affected_l3_current": snapshot["l3_current"],
            "l0_preserved": snapshot["l0_preserved"],
            "revision": revision(snapshot),
        }

    def clear_preview(self):
        with self._open_database() as connection:
            return self._clear_snapshot(connection)

    def clear_memories(self, expected_revision):
        """原子删除全部 L1；L0 与审计保留，关联 L2/L3 由触发器失效。"""

        with self._open_database(write_capability="delete") as connection:
            before = self._clear_snapshot(connection)
            if not secrets.compare_digest(before["revision"], expected_revision):
                raise MemoryAccessError("memory_clear_changed", 409)
            deleted = connection.execute("DELETE FROM atomic_memories").rowcount
            connection.commit()
            return {
                "cleared": True,
                "deleted_l1": deleted,
                "l0_preserved": before["l0_preserved"],
                "affected_l2_current": before["affected_l2_current"],
                "affected_l3_current": before["affected_l3_current"],
            }

    # 这些表保存 L0–L3、回答证据或从个人互动派生的学习状态。产品设置表
    # proactive_policy_settings / proactive_schedule_overrides 不在其中；清除记忆
    # 不应偷偷重置音量、模型、主动联系时段等另一类配置。
    _WIPE_TABLES = (
        "memory_feedback_review_events", "round_screen_memory_feedback_events",
        "round_screen_retrieval_evidence", "round_screen_retrieval_receipts",
        "round_screen_turns", "companion_strategy_candidate_sources",
        "companion_routine_candidate_sources", "companion_feedback_events",
        "companion_interaction_events", "proactive_outreach_events",
        "proactive_outreach", "companion_absence_strategy_selections",
        "companion_absence_strategy_switch_events", "companion_absence_strategy_versions",
        "companion_strategy_candidates", "companion_routine_candidates",
        "companion_user_initiated_interactions", "proactive_topic_seeds",
        "companion_follow_up_candidates", "persona_replacements", "persona_reviews",
        "persona_sources", "persona_generation_audits", "persona_lifecycle_events",
        "persona_memories", "scenario_reviews", "scenario_memory_sources",
        "scenario_generation_audits", "scenario_lifecycle_events", "scenario_memories",
        "memory_evidence", "atomic_memories", "l1_deletion_events",
        "memory_quality_events", "memory_consolidation_runs", "conversation_messages",
    )

    @classmethod
    def _wipe_snapshot(cls, connection):
        """哈希全部待删除行，防止预检以后新增对话仍被旧确认误删。"""

        rows_by_table = {}
        counts = {}
        for table in cls._WIPE_TABLES:
            rows = [list(row) for row in connection.execute(
                f"SELECT * FROM [{table}] ORDER BY rowid"
            ).fetchall()]
            rows_by_table[table] = rows
            counts[table] = len(rows)
        current_l2 = connection.execute(
            "SELECT count(*) FROM scenario_memories WHERE status IN ('candidate','active')"
        ).fetchone()[0]
        current_l3 = connection.execute(
            "SELECT count(*) FROM persona_memories WHERE status IN ('candidate','active')"
        ).fetchone()[0]
        primary = {"l0": counts["conversation_messages"],
                   "l1": counts["atomic_memories"],
                   "l2": counts["scenario_memories"],
                   "l3": counts["persona_memories"]}
        return {
            "l0_total": primary["l0"], "l1_total": primary["l1"],
            "l2_total": primary["l2"], "l3_total": primary["l3"],
            "l2_current": current_l2, "l3_current": current_l3,
            "related_record_total": sum(counts.values()) - sum(primary.values()),
            "web_chat_archive_preserved": True,
            "existing_backups_preserved": True,
            "revision": revision({"tables": rows_by_table}),
        }

    def wipe_preview(self):
        with self._open_database() as connection:
            return self._wipe_snapshot(connection)

    def wipe_memories(self, expected_revision):
        """原子清除当前库中的 L0–L3 和派生账本，保留产品设置。"""

        with self._open_database(write_capability="delete") as connection:
            before = self._wipe_snapshot(connection)
            if not secrets.compare_digest(before["revision"], expected_revision):
                raise MemoryAccessError("memory_wipe_changed", 409)
            for table in self._WIPE_TABLES:
                connection.execute(f"DELETE FROM [{table}]")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise MemoryAccessError("memory_database_invalid", 503)
            connection.commit()
            return {**{key: before[key] for key in (
                "l0_total", "l1_total", "l2_total", "l3_total", "related_record_total",
                "web_chat_archive_preserved", "existing_backups_preserved",
            )}, "wiped": True}

    def correct(self, memory_id, corrected_content, expected_revision):
        """在一个 SQLite 事务中保存纠正来源、新事实和取代关系。"""

        with self._open_database(write_capability="correction") as connection:
            service = self._service_factory(connection, commit_changes=False)
            old_details = service.get_memory(MemoryId(memory_id))
            if old_details is None:
                raise MemoryAccessError("memory_not_found", 404)
            if not secrets.compare_digest(
                revision(details_json(old_details)), expected_revision
            ):
                raise MemoryAccessError("memory_changed")
            try:
                result = service.correct_memory(
                    MemoryId(memory_id), corrected_content
                )
            except LookupError:
                raise MemoryAccessError("memory_not_found", 404) from None
            except ValueError as error:
                code = str(error)
                status = 400 if code.startswith("corrected_content_") else 409
                raise MemoryAccessError(code, status) from None
            except RuntimeError as error:
                if str(error) == "memory_correction_race":
                    raise MemoryAccessError("memory_changed") from None
                raise
            connection.commit()
            return {
                "corrected": True,
                "old_memory_id": str(result.old_memory.id),
                "new_memory_id": str(result.new_memory.id),
                "source_message_id": str(result.source_message.id),
                "source_type": result.evidence.source_type.value,
                "old_l0_preserved": True,
            }

    def record_change(self, memory_id, new_content, effective_at, expected_revision):
        """在同一事务中记录事实变化及其双时间语义。"""

        with self._open_database(write_capability="correction") as connection:
            service = self._service_factory(connection, commit_changes=False)
            old_details = service.get_memory(MemoryId(memory_id))
            if old_details is None:
                raise MemoryAccessError("memory_not_found", 404)
            if not secrets.compare_digest(
                revision(details_json(old_details)), expected_revision
            ):
                raise MemoryAccessError("memory_changed")
            try:
                result = service.record_memory_change(
                    MemoryId(memory_id),
                    new_content,
                    effective_at=datetime.fromisoformat(effective_at),
                )
            except LookupError:
                raise MemoryAccessError("memory_not_found", 404) from None
            except ValueError as error:
                code = str(error)
                status = 400 if (
                    code.startswith("changed_content_")
                    or code.startswith("effective_at_")
                    or code == "occurred_at_timezone_required"
                ) else 409
                raise MemoryAccessError(code, status) from None
            except RuntimeError as error:
                if str(error) == "memory_change_race":
                    raise MemoryAccessError("memory_changed") from None
                raise
            connection.commit()
            return {
                "changed": True,
                "old_memory_id": str(result.old_memory.id),
                "new_memory_id": str(result.new_memory.id),
                "source_message_id": str(result.source_message.id),
                "source_type": result.evidence.source_type.value,
                "effective_at": result.effective_at.isoformat(),
                "old_l0_preserved": True,
            }
