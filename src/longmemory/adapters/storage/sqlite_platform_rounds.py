"""平台来源侧的圆屏轮次账本；不依赖任何记忆引擎的内部层级。

助手来源和完成关联在来源库的同一事务提交。准备与引擎之间仍没有跨库
事务：准备中断明确保留 uncertain，绝不靠重发请求隐式重跑模型。
"""

from datetime import UTC, datetime, timedelta
import json
from hashlib import sha256
from uuid import uuid4, uuid5, NAMESPACE_URL

from longmemory.adapters.storage.sqlite_source_journal import SQLiteSourceJournal


class SQLitePlatformRounds:
    def __init__(self, journal: SQLiteSourceJournal, *, clock=None):
        self.journal = journal
        self.clock = clock or (lambda: datetime.now(UTC))
        with journal._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS platform_rounds (
                    event_id TEXT PRIMARY KEY, client_round_id TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL, prepare_request_id TEXT,
                    state TEXT NOT NULL, expires_at TEXT NOT NULL,
                    prepared TEXT, assistant_id TEXT, completion TEXT,
                    complete_request_id TEXT, ended_reason TEXT,
                    dispatch_claimed INTEGER NOT NULL DEFAULT 0,
                    voice_round_id TEXT, cancel_request_id TEXT);
                CREATE TABLE IF NOT EXISTS platform_round_feedback (
                    event_id TEXT PRIMARY KEY, target_event_id TEXT,
                    kind TEXT NOT NULL, recorded_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS platform_round_deadline ON platform_rounds(state,expires_at);
            """)
            # 兼容本轮首接口提交生成的合成来源库；只向已验明身份的来源库
            # 增补平台元数据列，不触旧算法/个人主库或重放消息。
            columns = {row[1] for row in connection.execute("PRAGMA table_info(platform_rounds)")}
            for name in ("voice_round_id", "cancel_request_id"):
                if name not in columns:
                    connection.execute(f"ALTER TABLE platform_rounds ADD COLUMN {name} TEXT")
            # 首接口候选把完整完成载荷存在此列；转为等价摘要即可保持回放，
            # 原助手正文仍在来源表，避免账本重复保留一份正文。
            for row in connection.execute("SELECT event_id,completion FROM platform_rounds WHERE completion LIKE '{%'").fetchall():
                connection.execute("UPDATE platform_rounds SET completion=? WHERE event_id=?",
                    (sha256(row[1].encode()).hexdigest(), row[0]))
            connection.execute("UPDATE platform_rounds SET state='uncertain' WHERE state='preparing'")

    def expire(self):
        with self.journal._connect() as connection:
            rows = connection.execute("UPDATE platform_rounds SET state='timed_out',ended_reason='completion_timeout' "
                "WHERE state='prepared' AND expires_at<? RETURNING event_id", (self.clock().isoformat(),)).fetchall()
            return tuple(row[0] for row in rows)

    def reserve(self, *, client_round_id, session_id, request_id, voice_round_id=None):
        with self.journal._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM platform_rounds WHERE client_round_id=?",
                                  (client_round_id,)).fetchone():
                raise ValueError("round_screen_prepare_already_recorded")
            event_id = str(uuid4())
            connection.execute("INSERT INTO platform_rounds "
                "(event_id,client_round_id,session_id,prepare_request_id,state,expires_at,voice_round_id) "
                "VALUES (?,?,?,?,'preparing',?,?)", (event_id, client_round_id, session_id,
                    request_id, (self.clock() + timedelta(minutes=5)).isoformat(), voice_round_id))
            return event_id

    def prepared(self, event_id, receipt):
        with self.journal._connect() as connection:
            connection.execute("UPDATE platform_rounds SET state='prepared',prepared=? "
                "WHERE event_id=? AND state='preparing'", (json.dumps(receipt), event_id))

    def failed(self, event_id):
        with self.journal._connect() as connection:
            connection.execute("UPDATE platform_rounds SET state='preparation_failed' "
                               "WHERE event_id=? AND state='preparing'", (event_id,))

    def _row(self, connection, event_id):
        row = connection.execute("SELECT * FROM platform_rounds WHERE event_id=?", (event_id,)).fetchone()
        if row is None:
            raise ValueError("round_screen_user_turn_not_found")
        return row

    def status(self, event_id):
        with self.journal._connect() as connection:
            connection.execute("UPDATE platform_rounds SET state='timed_out',ended_reason='completion_timeout' "
                "WHERE event_id=? AND state='prepared' AND expires_at<?", (event_id, self.clock().isoformat()))
            row = self._row(connection, event_id)
            return {key: row[key] for key in ("event_id", "client_round_id", "session_id",
                "prepare_request_id", "state", "assistant_id", "complete_request_id", "ended_reason",
                "voice_round_id", "cancel_request_id")}

    def claim_dispatch(self, event_id):
        with self.journal._connect() as connection:
            return connection.execute("UPDATE platform_rounds SET dispatch_claimed=1 "
                "WHERE event_id=? AND state='completed' AND dispatch_claimed=0", (event_id,)).rowcount == 1

    def complete(self, *, event_id, answer, receipt, request_id=None, client_round_id=None):
        # 幂等比较只存摘要；助手原文只在 conversation_messages 归档一次。
        payload = sha256(json.dumps({"answer": answer, "receipt": receipt}, sort_keys=True).encode()).hexdigest()
        with self.journal._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._row(connection, event_id)
            if client_round_id is not None and row["client_round_id"] != client_round_id:
                raise ValueError("round_screen_round_mismatch")
            if row["completion"] is not None:
                if row["completion"] != payload:
                    raise ValueError("round_screen_turn_conflict")
                return row["assistant_id"], False
            if row["state"] != "prepared":
                raise ValueError("round_screen_turn_" + row["state"])
            if datetime.fromisoformat(row["expires_at"]) < self.clock():
                # 持久化超时不能被随后的异常回滚。
                connection.execute("UPDATE platform_rounds SET state='timed_out',ended_reason='completion_timeout' WHERE event_id=?", (event_id,))
                connection.commit()
                raise ValueError("round_screen_turn_timed_out")
            if json.loads(row["prepared"]) != receipt:
                raise ValueError("round_screen_retrieval_receipt_mismatch")
            source = connection.execute("SELECT role FROM conversation_messages WHERE id=?", (event_id,)).fetchone()
            if source is None or source[0] != "user":
                raise ValueError("round_screen_user_turn_not_found")
            assistant_id = str(uuid5(NAMESPACE_URL, "platform-round-assistant:" + event_id))
            connection.execute("INSERT INTO conversation_messages VALUES (?,'assistant',?,?)",
                               (assistant_id, answer, self.clock().isoformat()))
            connection.execute("INSERT INTO source_dispatch VALUES (?,?,'archived',NULL,NULL)",
                               (assistant_id, row["session_id"]))
            connection.execute("UPDATE platform_rounds SET state='completed',assistant_id=?,completion=?,complete_request_id=? WHERE event_id=?",
                               (assistant_id, payload, request_id, event_id))
            return assistant_id, True

    def cancel(self, event_id, *, reason, client_round_id=None, request_id=None):
        if reason not in {"cancelled", "superseded", "chat_failed", "completion_timeout"}:
            raise ValueError("round_screen_cancel_reason_invalid")
        with self.journal._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._row(connection, event_id)
            if client_round_id is not None and row["client_round_id"] != client_round_id:
                raise ValueError("round_screen_round_mismatch")
            # 已生成的助手档案不因后来插话消失；ended_reason 仅说明取消观察。
            if row["state"] == "completed":
                connection.execute("UPDATE platform_rounds SET ended_reason=? WHERE event_id=?", (reason, event_id))
            elif row["state"] in {"preparing", "prepared"}:
                connection.execute("UPDATE platform_rounds SET state=?,ended_reason=? WHERE event_id=?",
                    ("timed_out" if reason == "completion_timeout" else "cancelled", reason, event_id))
            connection.execute("UPDATE platform_rounds SET cancel_request_id=? WHERE event_id=?", (request_id, event_id))
        return self.status(event_id)

    def feedback(self, event, kind):
        if kind is None:
            return None
        with self.journal._connect() as connection:
            own = self._row(connection, event.event_id)
            target = connection.execute("SELECT r.event_id,m.created_at FROM platform_rounds r "
                "JOIN conversation_messages m ON m.id=r.assistant_id WHERE r.session_id=? "
                "AND r.state='completed' AND r.rowid < (SELECT rowid FROM platform_rounds WHERE event_id=?) "
                "ORDER BY r.rowid DESC LIMIT 1", (own["session_id"], event.event_id)).fetchone()
            if target is None:
                return {"kind": kind, "recorded": False, "target_user_message_id": None,
                        "reason": "previous_completed_turn_missing"}
            age = event.occurred_at - datetime.fromisoformat(target[1])
            if age < timedelta(0) or age > timedelta(minutes=10):
                return {"kind": kind, "recorded": False, "target_user_message_id": None,
                        "reason": "previous_turn_too_old"}
            connection.execute("INSERT OR IGNORE INTO platform_round_feedback VALUES (?,?,?,?)",
                (event.event_id, target[0], kind, self.clock().isoformat()))
            return {"kind": kind, "recorded": True, "target_user_message_id": target[0], "reason": None}
