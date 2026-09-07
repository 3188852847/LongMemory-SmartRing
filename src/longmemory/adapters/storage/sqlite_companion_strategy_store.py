"""P5.3 陪伴策略候选 SQLite 存储；候选不会修改主动交流设置。"""

from datetime import datetime
from sqlite3 import Connection

from longmemory.core.companion import (
    CompanionStrategyCandidate,
    CompanionStrategyCandidateStatus,
    CompanionStrategyObservation,
)


class SQLiteCompanionStrategyCandidateStore:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def list_observations(self, subject_id: str, *, maximum_latency_seconds: int):
        rows = self._connection.execute(
            "SELECT i.id AS interaction_event_id,i.outreach_id,"
            "q.occurred_at AS queued_at,i.occurred_at AS observed_at,"
            "i.latency_seconds,CASE "
            "WHEN EXISTS (SELECT 1 FROM proactive_outreach_events p WHERE p.outreach_id=o.id AND p.new_state='played') THEN 'played' "
            "WHEN EXISTS (SELECT 1 FROM proactive_outreach_events p WHERE p.outreach_id=o.id AND p.new_state='device_acknowledged') THEN 'device_acknowledged' "
            "WHEN EXISTS (SELECT 1 FROM proactive_outreach_events p WHERE p.outreach_id=o.id AND p.new_state='transport_sent') THEN 'transport_sent' "
            "ELSE 'server_queued' END AS delivery_evidence_level "
            "FROM companion_interaction_events i "
            "JOIN proactive_outreach o ON o.id=i.outreach_id "
            "JOIN proactive_outreach_events q ON q.outreach_id=o.id "
            "AND q.sequence=(SELECT min(e.sequence) FROM proactive_outreach_events e "
            "WHERE e.outreach_id=o.id AND e.new_state='queued') "
            "WHERE i.subject_id=? AND i.latency_seconds<=? "
            "AND NOT EXISTS (SELECT 1 FROM companion_feedback_events f "
            "WHERE f.outreach_id=i.outreach_id) "
            "ORDER BY q.occurred_at,i.id",
            (subject_id, maximum_latency_seconds),
        ).fetchall()
        return tuple(CompanionStrategyObservation(
            interaction_event_id=row["interaction_event_id"],
            outreach_id=row["outreach_id"],
            queued_at=datetime.fromisoformat(row["queued_at"]),
            observed_at=datetime.fromisoformat(row["observed_at"]),
            latency_seconds=row["latency_seconds"],
            delivery_evidence_level=row["delivery_evidence_level"],
        ) for row in rows)

    def get_current(self, subject_id: str):
        row = self._connection.execute(
            "SELECT * FROM companion_strategy_candidates "
            "WHERE subject_id=? AND status='candidate' "
            "ORDER BY created_at DESC,id DESC LIMIT 1", (subject_id,),
        ).fetchone()
        return self._row(row) if row else None

    def get_by_fingerprint(self, subject_id: str, fingerprint: str):
        row = self._connection.execute(
            "SELECT * FROM companion_strategy_candidates "
            "WHERE subject_id=? AND evidence_fingerprint=? LIMIT 1",
            (subject_id, fingerprint),
        ).fetchone()
        return self._row(row) if row else None

    def list(self, subject_id: str):
        return tuple(self._row(row) for row in self._connection.execute(
            "SELECT * FROM companion_strategy_candidates WHERE subject_id=? "
            "ORDER BY created_at DESC,id DESC", (subject_id,),
        ).fetchall())

    def list_sources(self, candidate_id: str):
        return tuple(dict(row) for row in self._connection.execute(
            "SELECT s.interaction_event_id,s.outreach_id,s.queued_at,s.observed_at,"
            "s.latency_seconds,s.delivery_evidence_level "
            "FROM companion_strategy_candidate_sources s "
            "WHERE s.candidate_id=? ORDER BY s.queued_at,s.interaction_event_id",
            (candidate_id,),
        ).fetchall())

    def create(self, candidate, observations):
        self._connection.execute(
            "INSERT INTO companion_strategy_candidates "
            "(id,subject_id,status,suggested_minute,utc_offset_minutes,"
            "evidence_count,distinct_local_dates,evidence_fingerprint,"
            "rationale_code,generator_version,created_at,updated_at,revision) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (candidate.id, candidate.subject_id, candidate.status.value,
             candidate.suggested_minute, candidate.utc_offset_minutes,
             candidate.evidence_count, candidate.distinct_local_dates,
             candidate.evidence_fingerprint, candidate.rationale_code,
             candidate.generator_version, candidate.created_at.isoformat(),
             candidate.updated_at.isoformat(), candidate.revision),
        )
        self._connection.executemany(
            "INSERT INTO companion_strategy_candidate_sources "
            "(candidate_id,interaction_event_id,outreach_id,queued_at,observed_at,"
            "latency_seconds,delivery_evidence_level) VALUES (?,?,?,?,?,?,?)",
            [(candidate.id, item.interaction_event_id, item.outreach_id,
              item.queued_at.isoformat(), item.observed_at.isoformat(),
              item.latency_seconds, item.delivery_evidence_level)
             for item in observations],
        )
        self._connection.commit()
        return candidate

    def dismiss(self, candidate_id, *, subject_id, expected_revision, now):
        cursor = self._connection.execute(
            "UPDATE companion_strategy_candidates SET status='dismissed',"
            "updated_at=?,revision=revision+1 WHERE id=? AND subject_id=? "
            "AND status='candidate' AND revision=?",
            (now.isoformat(), candidate_id, subject_id, expected_revision),
        )
        if cursor.rowcount != 1:
            return None
        self._connection.commit()
        return self._row(self._connection.execute(
            "SELECT * FROM companion_strategy_candidates WHERE id=?", (candidate_id,),
        ).fetchone())

    @staticmethod
    def _row(row):
        return CompanionStrategyCandidate(
            id=row["id"], subject_id=row["subject_id"],
            status=CompanionStrategyCandidateStatus(row["status"]),
            suggested_minute=row["suggested_minute"],
            utc_offset_minutes=row["utc_offset_minutes"],
            evidence_count=row["evidence_count"],
            distinct_local_dates=row["distinct_local_dates"],
            evidence_fingerprint=row["evidence_fingerprint"],
            rationale_code=row["rationale_code"],
            generator_version=row["generator_version"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            revision=row["revision"],
        )
