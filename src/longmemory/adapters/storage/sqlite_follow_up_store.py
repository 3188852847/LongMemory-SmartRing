"""跟进候选的 SQLite 存储；只接受仍为当前状态的 L1 来源。"""

import hashlib
from datetime import datetime
from sqlite3 import Connection

from longmemory.core.proactive import FollowUpCandidate


class SQLiteFollowUpCandidateStore:
    def __init__(self, connection: Connection, *, commit_changes: bool = True) -> None:
        self._connection = connection
        self._commit_changes = commit_changes

    def create(self, candidate: FollowUpCandidate) -> FollowUpCandidate:
        source = self._connection.execute(
            "SELECT subject_id,content,valid_from,valid_to,retired_at "
            "FROM atomic_memories WHERE id=?",
            (candidate.source_memory_id,),
        ).fetchone()
        if source is None:
            raise ValueError("follow_up_source_not_found")
        if source["subject_id"] != candidate.subject_id:
            raise ValueError("follow_up_subject_mismatch")
        if source["retired_at"] is not None:
            raise ValueError("follow_up_source_not_current")
        if (
            source["valid_from"] is not None
            and candidate.follow_up_at < datetime.fromisoformat(source["valid_from"])
        ) or (
            source["valid_to"] is not None
            and candidate.follow_up_at >= datetime.fromisoformat(source["valid_to"])
        ):
            raise ValueError("follow_up_source_not_current")
        digest = hashlib.sha256(source["content"].encode("utf-8")).hexdigest()
        if digest != candidate.source_content_sha256:
            raise ValueError("follow_up_source_conflict")
        self._connection.execute(
            "INSERT INTO companion_follow_up_candidates "
            "(id,subject_id,source_memory_id,source_content_sha256,prompt_text,"
            "follow_up_at,status,created_at,updated_at,revision,creation_kind,"
            "source_message_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                candidate.id, candidate.subject_id, candidate.source_memory_id,
                candidate.source_content_sha256, candidate.prompt_text,
                candidate.follow_up_at.isoformat(), candidate.status.value,
                candidate.created_at.isoformat(), candidate.updated_at.isoformat(),
                candidate.revision, candidate.creation_kind,
                candidate.source_message_id,
            ),
        )
        if self._commit_changes:
            self._connection.commit()
        return candidate

    def list(self, subject_id: str) -> tuple[dict, ...]:
        rows = self._connection.execute(
            "SELECT f.*,m.content AS source_content,m.retired_at AS source_retired_at,"
            "m.valid_from AS source_valid_from,m.valid_to AS source_valid_to,"
            "m.superseded_by_id AS source_superseded_by_id,"
            "o.id AS outreach_id,o.state AS outreach_state,o.revision AS outreach_revision,"
            "o.expires_at AS outreach_expires_at "
            "FROM companion_follow_up_candidates f "
            "JOIN atomic_memories m ON m.id=f.source_memory_id "
            "LEFT JOIN proactive_outreach o ON o.follow_up_candidate_id=f.id "
            "WHERE f.subject_id=? ORDER BY f.follow_up_at,f.created_at DESC,f.id DESC",
            (subject_id,),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def cancel(
        self, candidate_id: str, *, expected_revision: int, now: datetime,
    ) -> bool:
        changed = self._connection.execute(
            "UPDATE companion_follow_up_candidates SET status='cancelled',updated_at=?,"
            "revision=revision+1 WHERE id=? AND status='candidate' AND revision=?",
            (now.isoformat(), candidate_id, expected_revision),
        ).rowcount
        if self._commit_changes:
            self._connection.commit()
        return changed == 1
