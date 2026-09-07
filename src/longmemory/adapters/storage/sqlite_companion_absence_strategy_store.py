"""缺席陪伴策略不可变版本的 SQLite 存储。"""

from datetime import datetime
from sqlite3 import Connection

from longmemory.core.companion import (
    CompanionAbsenceStrategySelection,
    CompanionAbsenceStrategySwitchAction,
    CompanionAbsenceStrategySwitchEvent,
    CompanionAbsenceStrategyVersion,
    CompanionRoutineCandidate,
    CompanionStrategyCandidateStatus,
)


def _weekdays(mask: int) -> tuple[int, ...]:
    return tuple(day for day in range(7) if mask & (1 << day))


def _mask(days: tuple[int, ...]) -> int:
    return sum(1 << day for day in days)


class SQLiteCompanionAbsenceStrategyVersionStore:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get_source_candidate(self, candidate_id, *, subject_id):
        row = self._connection.execute(
            "SELECT * FROM companion_routine_candidates WHERE id=? AND subject_id=?",
            (candidate_id, subject_id),
        ).fetchone()
        return self._candidate(row) if row else None

    def get_by_parameter_fingerprint(self, subject_id, parameter_fingerprint):
        row = self._connection.execute(
            "SELECT * FROM companion_absence_strategy_versions "
            "WHERE subject_id=? AND parameter_fingerprint=? LIMIT 1",
            (subject_id, parameter_fingerprint),
        ).fetchone()
        return self._version(row) if row else None

    def create(self, version):
        self._connection.execute(
            "INSERT INTO companion_absence_strategy_versions "
            "(id,subject_id,source_candidate_id,source_candidate_revision,"
            "expected_minute,grace_minutes,utc_offset_minutes,allowed_weekdays_mask,"
            "trigger_policy_version,replay_protocol,replay_dataset_name,"
            "replay_dataset_version,replay_dataset_sha256,parameter_fingerprint,replay_case_count,"
            "replay_matched_count,replay_unsafe_allow_count,replay_gate_passed,"
            "replayed_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (version.id, version.subject_id, version.source_candidate_id,
             version.source_candidate_revision, version.expected_minute,
             version.grace_minutes, version.utc_offset_minutes,
             _mask(version.allowed_weekdays), version.trigger_policy_version,
             version.replay_protocol, version.replay_dataset_name,
             version.replay_dataset_version, version.replay_dataset_sha256,
             version.parameter_fingerprint,
             version.replay_case_count, version.replay_matched_count,
             version.replay_unsafe_allow_count, int(version.replay_gate_passed),
             version.replayed_at.isoformat(), version.created_at.isoformat()),
        )
        self._connection.commit()
        return version

    def list(self, subject_id):
        return tuple(self._version(row) for row in self._connection.execute(
            "SELECT * FROM companion_absence_strategy_versions WHERE subject_id=? "
            "ORDER BY created_at DESC,id DESC", (subject_id,),
        ).fetchall())

    def get_version(self, version_id, *, subject_id):
        row = self._connection.execute(
            "SELECT * FROM companion_absence_strategy_versions WHERE id=? AND subject_id=?",
            (version_id, subject_id),
        ).fetchone()
        return self._version(row) if row else None

    def get_selection(self, subject_id):
        row = self._connection.execute(
            "SELECT * FROM companion_absence_strategy_selections WHERE subject_id=?",
            (subject_id,),
        ).fetchone()
        return self._selection(row) if row else None

    def switch_selection(self, *, subject_id, selected_version_id,
                         expected_revision, action, event_id, now):
        """用立即事务串行化指针检查、更新和审计，失败时不留下半条记录。"""
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT * FROM companion_absence_strategy_selections WHERE subject_id=?",
                (subject_id,),
            ).fetchone()
            current_revision = row["revision"] if row else 0
            if current_revision != expected_revision:
                self._connection.rollback()
                return None
            previous_version_id = row["current_version_id"] if row else None
            next_revision = current_revision + 1
            self._connection.execute(
                "INSERT INTO companion_absence_strategy_selections "
                "(subject_id,current_version_id,revision,updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(subject_id) DO UPDATE SET current_version_id=excluded.current_version_id,"
                "revision=excluded.revision,updated_at=excluded.updated_at",
                (subject_id, selected_version_id, next_revision, now.isoformat()),
            )
            self._connection.execute(
                "INSERT INTO companion_absence_strategy_switch_events "
                "(id,subject_id,previous_version_id,selected_version_id,action,"
                "pointer_revision,created_at) VALUES (?,?,?,?,?,?,?)",
                (event_id, subject_id, previous_version_id, selected_version_id,
                 action.value, next_revision, now.isoformat()),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        selection = CompanionAbsenceStrategySelection(
            subject_id=subject_id, version_id=selected_version_id,
            revision=next_revision, updated_at=now,
        )
        event = CompanionAbsenceStrategySwitchEvent(
            id=event_id, subject_id=subject_id,
            previous_version_id=previous_version_id,
            selected_version_id=selected_version_id, action=action,
            pointer_revision=next_revision, created_at=now,
        )
        return selection, event

    def list_switch_events(self, subject_id):
        rows = self._connection.execute(
            "SELECT * FROM companion_absence_strategy_switch_events WHERE subject_id=? "
            "ORDER BY pointer_revision DESC,id DESC", (subject_id,),
        ).fetchall()
        return tuple(self._switch_event(row) for row in rows)

    @staticmethod
    def _selection(row):
        return CompanionAbsenceStrategySelection(
            subject_id=row["subject_id"], version_id=row["current_version_id"],
            revision=row["revision"], updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _switch_event(row):
        return CompanionAbsenceStrategySwitchEvent(
            id=row["id"], subject_id=row["subject_id"],
            previous_version_id=row["previous_version_id"],
            selected_version_id=row["selected_version_id"],
            action=CompanionAbsenceStrategySwitchAction(row["action"]),
            pointer_revision=row["pointer_revision"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _candidate(row):
        return CompanionRoutineCandidate(
            id=row["id"], subject_id=row["subject_id"],
            status=CompanionStrategyCandidateStatus(row["status"]),
            expected_minute=row["expected_minute"],
            utc_offset_minutes=row["utc_offset_minutes"],
            observation_window_minutes=row["observation_window_minutes"],
            evidence_count=row["evidence_count"],
            distinct_local_dates=row["distinct_local_dates"],
            evidence_fingerprint=row["evidence_fingerprint"],
            rationale_code=row["rationale_code"], generator_version=row["generator_version"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]), revision=row["revision"],
        )

    @staticmethod
    def _version(row):
        return CompanionAbsenceStrategyVersion(
            id=row["id"], subject_id=row["subject_id"],
            source_candidate_id=row["source_candidate_id"],
            source_candidate_revision=row["source_candidate_revision"],
            expected_minute=row["expected_minute"], grace_minutes=row["grace_minutes"],
            utc_offset_minutes=row["utc_offset_minutes"],
            allowed_weekdays=_weekdays(row["allowed_weekdays_mask"]),
            trigger_policy_version=row["trigger_policy_version"],
            replay_protocol=row["replay_protocol"],
            replay_dataset_name=row["replay_dataset_name"],
            replay_dataset_version=row["replay_dataset_version"],
            replay_dataset_sha256=row["replay_dataset_sha256"],
            parameter_fingerprint=row["parameter_fingerprint"],
            replay_case_count=row["replay_case_count"],
            replay_matched_count=row["replay_matched_count"],
            replay_unsafe_allow_count=row["replay_unsafe_allow_count"],
            replay_gate_passed=bool(row["replay_gate_passed"]),
            replayed_at=datetime.fromisoformat(row["replayed_at"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
