"""从事件账本和 L0 用户消息读取主动联系历史事实。"""

from datetime import datetime, timedelta
from sqlite3 import Connection

from longmemory.core.proactive import OutreachPolicyState


class SQLiteProactiveHistoryReader:
    """单用户 V15 读取器；内容列从不进入查询结果。"""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def read(self, subject_id: str, *, now: datetime) -> OutreachPolicyState:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("proactive_history_now_timezone_required")
        if not subject_id or subject_id != subject_id.strip():
            raise ValueError("proactive_history_subject_invalid")

        # 策略的最大间隔为七天，多取一天覆盖固定偏移跨日边界。
        since = now - timedelta(days=8)
        attempt_rows = self._connection.execute(
            "SELECT e.occurred_at FROM proactive_outreach_events e "
            "JOIN proactive_outreach o ON o.id=e.outreach_id "
            "WHERE o.subject_id=? AND e.new_state='queued' "
            "AND julianday(e.occurred_at)>=julianday(?) "
            "ORDER BY julianday(e.occurred_at),e.id",
            (subject_id, since.isoformat()),
        ).fetchall()
        attempted_at = tuple(datetime.fromisoformat(row["occurred_at"]) for row in attempt_rows)

        latest_open = self._connection.execute(
            "SELECT e.occurred_at FROM proactive_outreach_events e "
            "JOIN proactive_outreach o ON o.id=e.outreach_id "
            "WHERE o.subject_id=? AND e.new_state='queued' "
            "AND o.state IN ('queued','transport_sent','device_acknowledged','played') "
            "ORDER BY julianday(e.occurred_at) DESC,e.id DESC LIMIT 1",
            (subject_id,),
        ).fetchone()
        latest_user = self._connection.execute(
            "SELECT created_at FROM conversation_messages WHERE role='user' "
            "ORDER BY julianday(created_at) DESC,id DESC LIMIT 1"
        ).fetchone()
        awaiting = False
        if latest_open is not None:
            attempt_time = datetime.fromisoformat(latest_open["occurred_at"])
            user_time = (
                datetime.fromisoformat(latest_user["created_at"])
                if latest_user is not None else None
            )
            awaiting = user_time is None or user_time <= attempt_time
        return OutreachPolicyState(
            attempted_at=attempted_at,
            awaiting_user_response=awaiting,
        )
