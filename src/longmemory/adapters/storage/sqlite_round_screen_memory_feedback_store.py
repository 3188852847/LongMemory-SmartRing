"""把圆屏明确反馈关联到最近一次已完成问答，不复制对话正文。"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4

from longmemory.application.round_screen_memory_feedback import (
    INTERPRETER_VERSION,
    classify_explicit_round_screen_feedback,
)
from longmemory.methods.contracts import MemoryEvent


@dataclass(frozen=True, slots=True)
class RoundScreenMemoryFeedbackResult:
    kind: str
    recorded: bool
    target_user_message_id: str | None
    reason: str | None


class SQLiteRoundScreenMemoryFeedbackStore:
    """保存十分钟内对最近一轮圆屏回答的明确质量反馈。"""

    _MAXIMUM_AGE = timedelta(minutes=10)

    def __init__(self, database: Path) -> None:
        self._database = database.resolve()

    def record_if_explicit(
        self, event: MemoryEvent,
    ) -> RoundScreenMemoryFeedbackResult | None:
        kind = classify_explicit_round_screen_feedback(event.content)
        if kind is None:
            return None
        connection = sqlite3.connect(
            self._database.as_uri() + "?mode=rw", uri=True, timeout=2,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT target_user_message_id,event_kind FROM "
                "round_screen_memory_feedback_events WHERE feedback_message_id=?",
                (event.event_id,),
            ).fetchone()
            if existing is not None:
                if existing["event_kind"] != kind:
                    raise ValueError("round_screen_feedback_conflict")
                connection.rollback()
                return RoundScreenMemoryFeedbackResult(
                    kind, True, existing["target_user_message_id"], None,
                )
            source = connection.execute(
                "SELECT role FROM conversation_messages WHERE id=?",
                (event.event_id,),
            ).fetchone()
            if source is None or source["role"] != "user":
                raise ValueError("round_screen_feedback_source_not_found")
            target = connection.execute(
                "SELECT user_message_id,completed_at FROM round_screen_turns "
                "WHERE completed_at<=? ORDER BY completed_at DESC,user_message_id DESC LIMIT 1",
                (event.occurred_at.isoformat(),),
            ).fetchone()
            if target is None:
                connection.rollback()
                return RoundScreenMemoryFeedbackResult(kind, False, None, "no_previous_turn")
            completed_at = datetime.fromisoformat(target["completed_at"])
            age = event.occurred_at - completed_at
            if age < timedelta(0) or age > self._MAXIMUM_AGE:
                connection.rollback()
                return RoundScreenMemoryFeedbackResult(kind, False, None, "previous_turn_too_old")
            connection.execute(
                "INSERT INTO round_screen_memory_feedback_events "
                "(id,target_user_message_id,feedback_message_id,event_kind,evidence_kind,"
                "interpreter_version,occurred_at) VALUES (?,?,?,?,?,?,?)",
                (
                    str(uuid4()), target["user_message_id"], event.event_id, kind,
                    "explicit_round_screen_statement", INTERPRETER_VERSION,
                    event.occurred_at.isoformat(),
                ),
            )
            connection.commit()
            return RoundScreenMemoryFeedbackResult(
                kind, True, target["user_message_id"], None,
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_events(self) -> tuple[dict, ...]:
        """返回控制台诊断所需的无正文元数据。"""

        connection = sqlite3.connect(
            self._database.as_uri() + "?mode=ro", uri=True, timeout=2,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        try:
            rows = connection.execute(
                "SELECT f.id AS feedback_event_id,f.target_user_message_id,"
                "f.feedback_message_id,f.event_kind,"
                "f.occurred_at,t.assistant_message_id,t.retrieved_l1_count,"
                "t.retrieved_l2_count,t.retrieved_l3_count,"
                "EXISTS(SELECT 1 FROM round_screen_retrieval_receipts r "
                "WHERE r.user_message_id=t.user_message_id) "
                "AS retrieval_evidence_recorded "
                "FROM round_screen_memory_feedback_events f "
                "JOIN round_screen_turns t ON t.user_message_id=f.target_user_message_id "
                "ORDER BY f.occurred_at DESC,f.id DESC"
            ).fetchall()
            evidence_rows = connection.execute(
                "SELECT e.user_message_id,e.layer,e.item_id,e.rank,e.content_sha256 "
                "FROM round_screen_retrieval_evidence e JOIN "
                "round_screen_memory_feedback_events f "
                "ON f.target_user_message_id=e.user_message_id "
                "ORDER BY e.user_message_id,e.layer,e.rank"
            ).fetchall()
            evidence_by_turn: dict[str, list[dict]] = {}
            for evidence in evidence_rows:
                item = dict(evidence)
                turn_id = item.pop("user_message_id")
                evidence_by_turn.setdefault(turn_id, []).append(item)
            result = []
            for row in rows:
                item = dict(row)
                item["retrieval_evidence"] = evidence_by_turn.get(
                    item["target_user_message_id"], [],
                )
                result.append(item)
            return tuple(result)
        finally:
            connection.close()

    def get_event(self, event_id: str) -> dict | None:
        """按需读取一条诊断样本；列表接口仍保持无正文。"""

        connection = sqlite3.connect(
            self._database.as_uri() + "?mode=ro", uri=True, timeout=2,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        try:
            row = connection.execute(
                "SELECT f.id,f.event_kind,f.evidence_kind,f.interpreter_version,"
                "f.occurred_at,f.target_user_message_id,f.feedback_message_id,"
                "t.assistant_message_id,q.content AS question,q.created_at AS question_at,"
                "a.content AS answer,a.created_at AS answer_at,"
                "m.content AS feedback,m.created_at AS feedback_at "
                "FROM round_screen_memory_feedback_events f "
                "JOIN round_screen_turns t ON t.user_message_id=f.target_user_message_id "
                "JOIN conversation_messages q ON q.id=f.target_user_message_id "
                "JOIN conversation_messages a ON a.id=t.assistant_message_id "
                "JOIN conversation_messages m ON m.id=f.feedback_message_id "
                "WHERE f.id=?",
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            evidence = []
            for item in connection.execute(
                "SELECT layer,item_id,rank,content_sha256 FROM "
                "round_screen_retrieval_evidence WHERE user_message_id=? "
                "ORDER BY layer,rank",
                (result["target_user_message_id"],),
            ).fetchall():
                evidence.append(self._resolve_evidence(connection, dict(item)))
            result["retrieval_evidence"] = evidence
            result["retrieval_evidence_recorded"] = connection.execute(
                "SELECT 1 FROM round_screen_retrieval_receipts WHERE user_message_id=?",
                (result["target_user_message_id"],),
            ).fetchone() is not None
            return result
        finally:
            connection.close()

    @staticmethod
    def _resolve_evidence(connection, item: dict) -> dict:
        """读取条目的当前版本并与回答时指纹比较，不猜测缺失正文。"""

        layer, item_id = item["layer"], item["item_id"]
        if layer == "l1":
            row = connection.execute(
                "SELECT content,retired_at FROM atomic_memories WHERE id=?", (item_id,),
            ).fetchone()
            content = row["content"] if row is not None else None
            state = "retired" if row is not None and row["retired_at"] else "available"
        elif layer == "l2":
            row = connection.execute(
                "SELECT title,summary,status FROM scenario_memories WHERE id=?", (item_id,),
            ).fetchone()
            content = (row["title"] + "\n" + row["summary"]) if row is not None else None
            state = row["status"] if row is not None else "missing"
        else:
            row = connection.execute(
                "SELECT label,statement,status FROM persona_memories WHERE id=?", (item_id,),
            ).fetchone()
            content = (row["label"] + "\n" + row["statement"]) if row is not None else None
            state = row["status"] if row is not None else "missing"
        if row is None:
            state = "missing"
        current_digest = sha256(content.encode("utf-8")).hexdigest() if content else None
        return {
            **item,
            "current_content": content,
            "current_state": state,
            "matches_receipt": current_digest == item["content_sha256"] if content else None,
        }
