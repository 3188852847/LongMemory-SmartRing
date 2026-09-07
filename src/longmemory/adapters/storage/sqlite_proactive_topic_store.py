"""主动话题素材的 SQLite 存储与来源有效性检查。"""

from datetime import datetime
from sqlite3 import Connection

from longmemory.core.proactive import ProactiveTopicSeed, TopicSeedStatus


class SQLiteProactiveTopicStore:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create(
        self, seed: ProactiveTopicSeed, *, expected_scenario_revision: int,
    ) -> ProactiveTopicSeed:
        scenario = self._connection.execute(
            "SELECT subject_id,status,valid_from,valid_to,revision "
            "FROM scenario_memories WHERE id=?",
            (seed.scenario_id,),
        ).fetchone()
        if scenario is None:
            raise ValueError("topic_seed_scenario_not_found")
        if scenario["subject_id"] != seed.subject_id:
            raise ValueError("topic_seed_subject_mismatch")
        if scenario["status"] != "active":
            raise ValueError("topic_seed_scenario_not_active")
        if scenario["revision"] != expected_scenario_revision:
            raise ValueError("topic_seed_scenario_conflict")
        if scenario["valid_from"] is not None and datetime.fromisoformat(
            scenario["valid_from"]
        ) > seed.created_at:
            raise ValueError("topic_seed_scenario_not_current")
        if scenario["valid_to"] is not None and datetime.fromisoformat(
            scenario["valid_to"]
        ) <= seed.created_at:
            raise ValueError("topic_seed_scenario_not_current")
        self._connection.execute(
            "INSERT INTO proactive_topic_seeds "
            "(id,subject_id,scenario_id,prompt_text,status,created_at,updated_at,revision) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (seed.id, seed.subject_id, seed.scenario_id, seed.prompt_text,
             seed.status.value, seed.created_at.isoformat(), seed.updated_at.isoformat(),
             seed.revision),
        )
        self._connection.commit()
        return seed

    def list(self, subject_id: str) -> tuple[dict, ...]:
        rows = self._connection.execute(
            "SELECT t.*,s.title AS scenario_title,s.summary AS scenario_summary,"
            "s.status AS scenario_status,s.valid_from AS scenario_valid_from,"
            "s.valid_to AS scenario_valid_to "
            "FROM proactive_topic_seeds t JOIN scenario_memories s ON s.id=t.scenario_id "
            "WHERE t.subject_id=? ORDER BY t.created_at DESC,t.id DESC",
            (subject_id,),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def disable(self, seed_id: str, *, expected_revision: int, now: datetime) -> bool:
        changed = self._connection.execute(
            "UPDATE proactive_topic_seeds SET status='disabled',updated_at=?,revision=revision+1 "
            "WHERE id=? AND status='active' AND revision=?",
            (now.isoformat(), seed_id, expected_revision),
        ).rowcount
        self._connection.commit()
        return changed == 1
