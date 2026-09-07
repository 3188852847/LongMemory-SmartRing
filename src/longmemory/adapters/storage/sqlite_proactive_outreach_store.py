"""主动交流当前投影与只追加事件的 SQLite 原子存储。"""

from datetime import datetime
from sqlite3 import Connection, IntegrityError, Row

from longmemory.core.proactive import (
    OutreachEvent,
    OutreachEvidence,
    OutreachState,
    OutreachTrigger,
    ProactiveOutreach,
)


class SQLiteProactiveOutreachStore:
    def __init__(self, connection: Connection, *, commit_changes: bool = True) -> None:
        self._connection = connection
        self._commit_changes = commit_changes

    def create(self, outreach: ProactiveOutreach, event: OutreachEvent) -> None:
        if (outreach.state != OutreachState.CANDIDATE or outreach.revision != 1
                or event.outreach_id != outreach.id or event.sequence != 1):
            raise ValueError("outreach_create_contract_invalid")
        try:
            self._connection.execute(
                "INSERT INTO proactive_outreach "
                "(id,subject_id,trigger_kind,trigger_reason_code,content,created_at,"
                "scheduled_for,expires_at,state,state_changed_at,idempotency_key,"
                "policy_version,revision,failure_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                self._outreach_values(outreach),
            )
            self._insert_event(event)
            if self._commit_changes:
                self._connection.commit()
        except IntegrityError as error:
            self._connection.rollback()
            if "proactive_outreach.subject_id" in str(error):
                raise ValueError("outreach_idempotency_conflict") from None
            raise
        except BaseException:
            self._connection.rollback()
            raise

    def transition(
        self,
        outreach: ProactiveOutreach,
        event: OutreachEvent,
        *,
        expected_revision: int,
    ) -> None:
        if (outreach.revision != expected_revision + 1
                or event.outreach_id != outreach.id
                or event.sequence != outreach.revision
                or event.previous_state is None
                or event.new_state != outreach.state
                or event.occurred_at != outreach.state_changed_at):
            raise ValueError("outreach_transition_contract_invalid")
        try:
            changed = self._connection.execute(
                "UPDATE proactive_outreach SET state=?,state_changed_at=?,revision=?,"
                "failure_reason=? WHERE id=? AND revision=? AND state=?",
                (
                    outreach.state.value,
                    outreach.state_changed_at.isoformat(),
                    outreach.revision,
                    outreach.failure_reason,
                    outreach.id,
                    expected_revision,
                    event.previous_state.value,
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("outreach_transition_conflict")
            self._insert_event(event)
            if self._commit_changes:
                self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def get(self, outreach_id: str) -> ProactiveOutreach | None:
        row = self._connection.execute(
            "SELECT * FROM proactive_outreach WHERE id=?", (outreach_id,)
        ).fetchone()
        return self._row_to_outreach(row) if row is not None else None

    def get_by_idempotency(
        self, subject_id: str, idempotency_key: str,
    ) -> ProactiveOutreach | None:
        row = self._connection.execute(
            "SELECT * FROM proactive_outreach "
            "WHERE subject_id=? AND idempotency_key=?",
            (subject_id, idempotency_key),
        ).fetchone()
        return self._row_to_outreach(row) if row is not None else None

    def list_events(self, outreach_id: str) -> tuple[OutreachEvent, ...]:
        rows = self._connection.execute(
            "SELECT * FROM proactive_outreach_events WHERE outreach_id=? "
            "ORDER BY sequence", (outreach_id,)
        ).fetchall()
        return tuple(self._row_to_event(row) for row in rows)

    def _insert_event(self, event: OutreachEvent) -> None:
        self._connection.execute(
            "INSERT INTO proactive_outreach_events "
            "(id,outreach_id,sequence,previous_state,new_state,reason_code,"
            "evidence_kind,occurred_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                event.id,
                event.outreach_id,
                event.sequence,
                event.previous_state.value if event.previous_state else None,
                event.new_state.value,
                event.reason_code,
                event.evidence.value,
                event.occurred_at.isoformat(),
            ),
        )

    @staticmethod
    def _outreach_values(outreach: ProactiveOutreach) -> tuple[object, ...]:
        return (
            outreach.id,
            outreach.subject_id,
            outreach.trigger.value,
            outreach.trigger_reason_code,
            outreach.content,
            outreach.created_at.isoformat(),
            outreach.scheduled_for.isoformat(),
            outreach.expires_at.isoformat(),
            outreach.state.value,
            (outreach.state_changed_at or outreach.created_at).isoformat(),
            outreach.idempotency_key,
            outreach.policy_version,
            outreach.revision,
            outreach.failure_reason,
        )

    @staticmethod
    def _row_to_outreach(row: Row) -> ProactiveOutreach:
        return ProactiveOutreach(
            id=row["id"],
            subject_id=row["subject_id"],
            trigger=OutreachTrigger(row["trigger_kind"]),
            trigger_reason_code=row["trigger_reason_code"],
            content=row["content"],
            created_at=datetime.fromisoformat(row["created_at"]),
            scheduled_for=datetime.fromisoformat(row["scheduled_for"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            state=OutreachState(row["state"]),
            state_changed_at=datetime.fromisoformat(row["state_changed_at"]),
            idempotency_key=row["idempotency_key"],
            policy_version=row["policy_version"],
            revision=row["revision"],
            failure_reason=row["failure_reason"],
        )

    @staticmethod
    def _row_to_event(row: Row) -> OutreachEvent:
        return OutreachEvent(
            id=row["id"],
            outreach_id=row["outreach_id"],
            sequence=row["sequence"],
            previous_state=(
                OutreachState(row["previous_state"])
                if row["previous_state"] is not None else None
            ),
            new_state=OutreachState(row["new_state"]),
            reason_code=row["reason_code"],
            evidence=OutreachEvidence(row["evidence_kind"]),
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
        )
