"""跟进候选的 SQLite 存储；只接受仍为当前状态的 L1 来源。"""

import hashlib
from datetime import datetime
from sqlite3 import Connection

from longmemory.core.proactive import FollowUpCandidate


class SQLiteFollowUpCandidateStore:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create(self, candidate: FollowUpCandidate) -> FollowUpCandidate:
        source = self._connection.execute(
            "SELECT subject_id,content,retired_at FROM atomic_memories WHERE id=?",
            (candidate.source_memory_id,),
        ).fetchone()
        if source is None:
            raise ValueError("follow_up_source_not_found")
        if source["subject_id"] != candidate.subject_id:
            raise ValueError("follow_up_subject_mismatch")
        if source["retired_at"] is not None:
            raise ValueError("follow_up_source_not_current")
        digest = hashlib.sha256(source["content"].encode("utf-8")).hexdigest()
        if digest != candidate.source_content_sha256:
            raise ValueError("follow_up_source_conflict")
        self._connection.execute(
            "INSERT INTO companion_follow_up_candidates "
            "(id,subject_id,source_memory_id,source_content_sha256,prompt_text,"
            "follow_up_at,status,created_at,updated_at,revision) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                candidate.id, candidate.subject_id, candidate.source_memory_id,
                candidate.source_content_sha256, candidate.prompt_text,
                candidate.follow_up_at.isoformat(), candidate.status.value,
                candidate.created_at.isoformat(), candidate.updated_at.isoformat(),
                candidate.revision,
            ),
        )
        self._connection.commit()
        return candidate

    def list(self, subject_id: str) -> tuple[dict, ...]:
        rows = self._connection.execute(
            "SELECT f.*,m.content AS source_content,m.retired_at AS source_retired_at,"
            "m.superseded_by_id AS source_superseded_by_id "
            "FROM companion_follow_up_candidates f "
            "JOIN atomic_memories m ON m.id=f.source_memory_id "
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
        self._connection.commit()
        return changed == 1
