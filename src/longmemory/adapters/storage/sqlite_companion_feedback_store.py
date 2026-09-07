"""明确陪伴反馈的 SQLite 存储。"""

from datetime import datetime
from sqlite3 import Connection

from longmemory.core.companion import CompanionFeedbackEvent, ProactiveTopicFeedbackTarget


class SQLiteCompanionFeedbackStore:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def find_recent_topic(
        self, subject_id: str, *, before: datetime, not_before: datetime,
    ) -> ProactiveTopicFeedbackTarget | None:
        row = self._connection.execute(
            "SELECT o.id AS outreach_id,t.id AS topic_seed_id,t.revision "
            "FROM proactive_outreach o "
            "JOIN proactive_topic_seeds t ON t.id=o.topic_seed_id "
            "JOIN proactive_outreach_events q ON q.outreach_id=o.id "
            "AND q.sequence=(SELECT min(e.sequence) FROM proactive_outreach_events e "
            "WHERE e.outreach_id=o.id AND e.new_state='queued') "
            "WHERE o.subject_id=? AND o.trigger_kind!='manual_test' "
            "AND o.trigger_reason_code NOT GLOB 'development_*' "
            "AND o.state IN ('queued','transport_sent','device_acknowledged','played') "
            "AND t.status='active' AND q.occurred_at>=? AND q.occurred_at<? "
            "ORDER BY q.occurred_at DESC,o.id DESC LIMIT 1",
            (subject_id, not_before.isoformat(), before.isoformat()),
        ).fetchone()
        if row is None:
            return None
        return ProactiveTopicFeedbackTarget(
            row["outreach_id"], row["topic_seed_id"], row["revision"],
        )

    def reject_topic(
        self, event: CompanionFeedbackEvent, *, expected_topic_revision: int,
    ) -> None:
        changed = self._connection.execute(
            "UPDATE proactive_topic_seeds SET status='disabled',updated_at=?,"
            "revision=revision+1 WHERE id=? AND status='active' AND revision=?",
            (event.occurred_at.isoformat(), event.topic_seed_id, expected_topic_revision),
        ).rowcount
        if changed != 1:
            raise ValueError("companion_feedback_topic_conflict")
        self._connection.execute(
            "INSERT INTO companion_feedback_events "
            "(id,subject_id,outreach_id,topic_seed_id,source_message_id,occurred_at,"
            "feedback_kind,action_kind,evidence_kind,interpreter_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (event.id, event.subject_id, event.outreach_id, event.topic_seed_id,
             event.source_message_id, event.occurred_at.isoformat(),
             event.feedback_kind, event.action_kind, event.evidence_kind,
             event.interpreter_version),
        )

    def get_for_outreach(self, outreach_id: str) -> dict | None:
        row = self._connection.execute(
            "SELECT topic_seed_id,occurred_at,feedback_kind,action_kind,"
            "evidence_kind,interpreter_version FROM companion_feedback_events "
            "WHERE outreach_id=? ORDER BY occurred_at DESC,id DESC LIMIT 1",
            (outreach_id,),
        ).fetchone()
        return dict(row) if row is not None else None
