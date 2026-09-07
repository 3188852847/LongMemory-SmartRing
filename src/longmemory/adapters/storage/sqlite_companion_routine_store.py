"""用户主动出现时段候选的 SQLite 存储；不修改主动交流设置。"""

from datetime import datetime
from sqlite3 import Connection

from longmemory.core.companion import (
    CompanionRoutineCandidate,
    CompanionStrategyCandidateStatus,
    UserInitiatedInteractionEvent,
)


class SQLiteCompanionRoutineCandidateStore:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def list_observations(self, subject_id: str):
        rows = self._connection.execute(
            "SELECT * FROM companion_user_initiated_interactions "
            "WHERE subject_id=? ORDER BY occurred_at,id", (subject_id,),
        ).fetchall()
        return tuple(UserInitiatedInteractionEvent(
            id=row["id"], subject_id=row["subject_id"],
            source_message_id=row["source_message_id"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            previous_user_message_at=(
                datetime.fromisoformat(row["previous_user_message_at"])
                if row["previous_user_message_at"] else None
            ),
            silence_gap_seconds=row["silence_gap_seconds"],
            evidence_kind=row["evidence_kind"],
            detector_version=row["detector_version"],
        ) for row in rows)

    def get_current(self, subject_id: str):
        row = self._connection.execute(
            "SELECT * FROM companion_routine_candidates "
            "WHERE subject_id=? AND status='candidate' "
            "ORDER BY created_at DESC,id DESC LIMIT 1", (subject_id,),
        ).fetchone()
        return self._row(row) if row else None

    def get_by_fingerprint(self, subject_id: str, fingerprint: str):
        row = self._connection.execute(
            "SELECT * FROM companion_routine_candidates "
            "WHERE subject_id=? AND evidence_fingerprint=? LIMIT 1",
            (subject_id, fingerprint),
        ).fetchone()
        return self._row(row) if row else None

    def list(self, subject_id: str):
        return tuple(self._row(row) for row in self._connection.execute(
            "SELECT * FROM companion_routine_candidates WHERE subject_id=? "
            "ORDER BY created_at DESC,id DESC", (subject_id,),
        ).fetchall())

    def list_sources(self, candidate_id: str):
        return tuple(dict(row) for row in self._connection.execute(
            "SELECT user_initiated_event_id,occurred_at,silence_gap_seconds,"
            "evidence_kind FROM companion_routine_candidate_sources "
            "WHERE candidate_id=? ORDER BY occurred_at,user_initiated_event_id",
            (candidate_id,),
        ).fetchall())

    def create(self, candidate, observations):
        self._connection.execute(
            "INSERT INTO companion_routine_candidates "
            "(id,subject_id,status,expected_minute,utc_offset_minutes,"
            "observation_window_minutes,evidence_count,distinct_local_dates,"
            "evidence_fingerprint,rationale_code,generator_version,created_at,"
            "updated_at,revision) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (candidate.id, candidate.subject_id, candidate.status.value,
             candidate.expected_minute, candidate.utc_offset_minutes,
             candidate.observation_window_minutes, candidate.evidence_count,
             candidate.distinct_local_dates, candidate.evidence_fingerprint,
             candidate.rationale_code, candidate.generator_version,
             candidate.created_at.isoformat(), candidate.updated_at.isoformat(),
             candidate.revision),
        )
        self._connection.executemany(
            "INSERT INTO companion_routine_candidate_sources "
            "(candidate_id,user_initiated_event_id,occurred_at,"
            "silence_gap_seconds,evidence_kind) VALUES (?,?,?,?,?)",
            [(candidate.id, item.id, item.occurred_at.isoformat(),
              item.silence_gap_seconds, item.evidence_kind)
             for item in observations],
        )
        self._connection.commit()
        return candidate

    def dismiss(self, candidate_id, *, subject_id, expected_revision, now):
        cursor = self._connection.execute(
            "UPDATE companion_routine_candidates SET status='dismissed',"
            "updated_at=?,revision=revision+1 WHERE id=? AND subject_id=? "
            "AND status='candidate' AND revision=?",
            (now.isoformat(), candidate_id, subject_id, expected_revision),
        )
        if cursor.rowcount != 1:
            return None
        self._connection.commit()
        return self._row(self._connection.execute(
            "SELECT * FROM companion_routine_candidates WHERE id=?",
            (candidate_id,),
        ).fetchone())

    @staticmethod
    def _row(row):
        return CompanionRoutineCandidate(
            id=row["id"], subject_id=row["subject_id"],
            status=CompanionStrategyCandidateStatus(row["status"]),
            expected_minute=row["expected_minute"],
            utc_offset_minutes=row["utc_offset_minutes"],
            observation_window_minutes=row["observation_window_minutes"],
            evidence_count=row["evidence_count"],
            distinct_local_dates=row["distinct_local_dates"],
            evidence_fingerprint=row["evidence_fingerprint"],
            rationale_code=row["rationale_code"],
            generator_version=row["generator_version"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            revision=row["revision"],
        )
