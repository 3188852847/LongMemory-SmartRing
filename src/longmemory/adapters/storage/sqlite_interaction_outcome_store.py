"""P5 最小互动结果 SQLite 记录器。"""

from collections.abc import Callable
from datetime import datetime
from sqlite3 import Connection
from uuid import uuid4

from longmemory.core.companion import (
    InteractionOutcomeEvent,
    InteractionOutcomeEvidence,
    InteractionOutcomeKind,
)
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.core.memory.l1_atomic.models import CURRENT_USER_SUBJECT_ID


RECORDER_VERSION = "interaction-outcome-recorder-v1"


class SQLiteInteractionOutcomeStore:
    """只关联时间上的后续消息，不声称用户回应了问候。"""

    def __init__(
        self,
        connection: Connection,
        *,
        commit_changes: bool = True,
        id_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        self._connection = connection
        self._commit_changes = commit_changes
        self._id_factory = id_factory

    def record_user_message(
        self, message: ConversationMessage,
    ) -> InteractionOutcomeEvent | None:
        if message.role != MessageRole.USER:
            return None

        # 只使用正式自动触发。manual_test 与 development_* 都是调试
        # 轨迹，若让它们进入学习样本，将会把开发者行为误当用户习惯。
        row = self._connection.execute(
            "SELECT o.id,o.subject_id,q.occurred_at AS observed_from "
            "FROM proactive_outreach o "
            "JOIN proactive_outreach_events q ON q.outreach_id=o.id "
            "AND q.sequence=(SELECT min(e.sequence) FROM proactive_outreach_events e "
            "WHERE e.outreach_id=o.id AND e.new_state='queued') "
            "WHERE o.subject_id=? "
            "AND o.trigger_kind IN "
            "('explicit_schedule','inactivity_rule','habit_candidate') "
            "AND o.trigger_reason_code NOT GLOB 'development_*' "
            "AND o.state IN "
            "('queued','transport_sent','device_acknowledged','played') "
            "AND q.occurred_at<? "
            "AND NOT EXISTS (SELECT 1 FROM companion_interaction_events e "
            "WHERE e.outreach_id=o.id "
            "AND e.event_kind='subsequent_user_message_observed') "
            "ORDER BY q.occurred_at DESC,o.id DESC LIMIT 1",
            (str(CURRENT_USER_SUBJECT_ID), message.created_at.isoformat()),
        ).fetchone()
        if row is None:
            return None

        outreach_time = datetime.fromisoformat(row["observed_from"])
        latency_seconds = max(0, int((message.created_at - outreach_time).total_seconds()))
        event = InteractionOutcomeEvent(
            id=self._id_factory(),
            subject_id=row["subject_id"],
            kind=InteractionOutcomeKind.SUBSEQUENT_USER_MESSAGE_OBSERVED,
            outreach_id=row["id"],
            source_message_id=str(message.id),
            occurred_at=message.created_at,
            latency_seconds=latency_seconds,
            evidence=InteractionOutcomeEvidence.TEMPORAL_ORDER,
            recorder_version=RECORDER_VERSION,
        )
        self._connection.execute(
            "INSERT INTO companion_interaction_events "
            "(id,subject_id,event_kind,outreach_id,source_message_id,occurred_at,"
            "latency_seconds,evidence_kind,recorder_version) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                event.id, event.subject_id, event.kind.value, event.outreach_id,
                event.source_message_id, event.occurred_at.isoformat(),
                event.latency_seconds, event.evidence.value,
                event.recorder_version,
            ),
        )
        if self._commit_changes:
            self._connection.commit()
        return event

    def get_for_outreach(self, outreach_id: str) -> InteractionOutcomeEvent | None:
        row = self._connection.execute(
            "SELECT * FROM companion_interaction_events WHERE outreach_id=? "
            "AND event_kind='subsequent_user_message_observed' LIMIT 1",
            (outreach_id,),
        ).fetchone()
        return self._row_to_event(row) if row is not None else None

    @staticmethod
    def _row_to_event(row) -> InteractionOutcomeEvent:
        return InteractionOutcomeEvent(
            id=row["id"], subject_id=row["subject_id"],
            kind=InteractionOutcomeKind(row["event_kind"]),
            outreach_id=row["outreach_id"],
            source_message_id=row["source_message_id"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            latency_seconds=row["latency_seconds"],
            evidence=InteractionOutcomeEvidence(row["evidence_kind"]),
            recorder_version=row["recorder_version"],
        )
