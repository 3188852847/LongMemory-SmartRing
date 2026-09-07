"""记录长静默后由用户主动开启的交流；不保存消息正文。"""

from collections.abc import Callable
from datetime import datetime, timedelta
from sqlite3 import Connection
from uuid import uuid4

from longmemory.core.companion import UserInitiatedInteractionEvent
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.core.memory.l1_atomic.models import CURRENT_USER_SUBJECT_ID


SILENCE_GAP = timedelta(hours=4)
RECENT_OUTREACH_WINDOW = timedelta(minutes=30)
DETECTOR_VERSION = "user-initiated-interaction-v1"


class SQLiteUserInitiatedInteractionStore:
    """以保守时间启发式记录“用户主动出现”，不声称真实会话边界。"""

    def __init__(self, connection: Connection, *, commit_changes: bool = True,
                 id_factory: Callable[[], str] = lambda: uuid4().hex) -> None:
        self._connection = connection
        self._commit_changes = commit_changes
        self._id_factory = id_factory

    def record_user_message(
        self, message: ConversationMessage,
    ) -> UserInitiatedInteractionEvent | None:
        if message.role != MessageRole.USER:
            return None
        previous = self._connection.execute(
            "SELECT created_at FROM conversation_messages "
            "WHERE role='user' AND id<>? AND created_at<=? "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (str(message.id), message.created_at.isoformat()),
        ).fetchone()
        previous_at = (
            datetime.fromisoformat(previous["created_at"]) if previous else None
        )
        gap = (
            None if previous_at is None
            else max(0, int((message.created_at - previous_at).total_seconds()))
        )
        if gap is not None and gap < int(SILENCE_GAP.total_seconds()):
            return None

        recent_outreach = self._connection.execute(
            "SELECT 1 FROM proactive_outreach_events e "
            "JOIN proactive_outreach o ON o.id=e.outreach_id "
            "WHERE o.subject_id=? AND e.new_state='queued' "
            "AND e.occurred_at>=? AND e.occurred_at<? LIMIT 1",
            (str(CURRENT_USER_SUBJECT_ID),
             (message.created_at - RECENT_OUTREACH_WINDOW).isoformat(),
             message.created_at.isoformat()),
        ).fetchone()
        if recent_outreach is not None:
            return None

        event = UserInitiatedInteractionEvent(
            id=self._id_factory(), subject_id=str(CURRENT_USER_SUBJECT_ID),
            source_message_id=str(message.id), occurred_at=message.created_at,
            previous_user_message_at=previous_at, silence_gap_seconds=gap,
            detector_version=DETECTOR_VERSION,
        )
        self._connection.execute(
            "INSERT INTO companion_user_initiated_interactions "
            "(id,subject_id,source_message_id,occurred_at,"
            "previous_user_message_at,silence_gap_seconds,evidence_kind,"
            "detector_version) VALUES (?,?,?,?,?,?,?,?)",
            (event.id, event.subject_id, event.source_message_id,
             event.occurred_at.isoformat(),
             event.previous_user_message_at.isoformat()
             if event.previous_user_message_at else None,
             event.silence_gap_seconds, event.evidence_kind,
             event.detector_version),
        )
        if self._commit_changes:
            self._connection.commit()
        return event

    def list_recent(self, subject_id: str, *, limit: int = 30) -> tuple[dict, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("user_initiated_interaction_limit_invalid")
        return tuple(dict(row) for row in self._connection.execute(
            "SELECT id,subject_id,source_message_id,occurred_at,"
            "previous_user_message_at,silence_gap_seconds,evidence_kind,"
            "detector_version FROM companion_user_initiated_interactions "
            "WHERE subject_id=? ORDER BY occurred_at DESC,id DESC LIMIT ?",
            (subject_id, limit),
        ).fetchall())
