"""从已有 V5 数据库只读召回已接受且当前有效的 L2 场景。"""

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

from longmemory.application.scenario_recall import (
    ScenarioRecallItem,
    ScenarioRecallResult,
)
from longmemory.core.memory.retrieval.service import keyword_overlap_score


class SQLiteScenarioRecallProvider:
    """每次召回使用短只读快照；不缓存个人场景，不执行迁移。"""

    def __init__(self, database: Path) -> None:
        self.database = database.resolve()

    def recall(self, query: str, *, limit: int = 3) -> ScenarioRecallResult:
        if not 1 <= limit <= 10:
            raise ValueError("scenario_recall_limit_invalid")
        now = datetime.now(UTC).isoformat()
        connection = sqlite3.connect(
            self.database.as_uri() + "?mode=ro", uri=True, timeout=2
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only = ON")
            rows = connection.execute(
                "SELECT * FROM scenario_memories WHERE status='active' "
                "AND (valid_from IS NULL OR valid_from <= ?) "
                "AND (valid_to IS NULL OR valid_to >= ?) "
                "ORDER BY generated_at DESC, id DESC",
                (now, now),
            ).fetchall()
            scored = []
            for order, row in enumerate(rows):
                score = keyword_overlap_score(query, row["title"] + " " + row["summary"])
                if score:
                    scored.append((score, -order, row))
            scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
            items = []
            for _score, _order, row in scored[:limit]:
                sources = connection.execute(
                    "SELECT s.memory_id, e.source_message_id FROM scenario_memory_sources s "
                    "LEFT JOIN memory_evidence e ON e.memory_id=s.memory_id "
                    "WHERE s.scenario_id=? ORDER BY s.memory_id, e.source_message_id",
                    (row["id"],),
                ).fetchall()
                items.append(ScenarioRecallItem(
                    row["id"], row["title"], row["summary"],
                    tuple(dict.fromkeys(source["memory_id"] for source in sources)),
                    tuple(dict.fromkeys(source["source_message_id"] for source in sources
                                        if source["source_message_id"] is not None)),
                ))
        finally:
            connection.close()
        context = ""
        if items:
            lines = "\n".join(
                f"- {item.title}：{item.summary}" for item in items
            )
            context = "以下是与当前问题相关、已经用户复核的生活场景（L2）：\n" + lines
        return ScenarioRecallResult(context, tuple(items))

    def close(self) -> None:
        """当前实现不持有长期连接，保留统一生命周期接口。"""
