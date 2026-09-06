"""从现有数据库只读召回当前有效、与问题相关的 L3 用户画像。"""

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

from longmemory.application.persona_recall import PersonaRecallItem, PersonaRecallResult
from longmemory.core.memory.retrieval.service import keyword_overlap_score


class SQLitePersonaRecallProvider:
    """每次使用短只读快照；不缓存、迁移或修改个人画像。"""

    def __init__(self, database: Path) -> None:
        self.database = database.resolve()

    def recall(self, query: str, *, limit: int = 3, max_chars: int = 1200) -> PersonaRecallResult:
        if not 1 <= limit <= 10 or not 200 <= max_chars <= 4000:
            raise ValueError("persona_recall_budget_invalid")
        now = datetime.now(UTC).isoformat()
        connection = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only = ON")
            rows = connection.execute(
                "SELECT * FROM persona_memories WHERE status='active' "
                "AND (valid_from IS NULL OR valid_from <= ?) "
                "AND (valid_to IS NULL OR valid_to >= ?) "
                "ORDER BY generated_at DESC,id DESC", (now, now),
            ).fetchall()
            scored = []
            for order, row in enumerate(rows):
                score = keyword_overlap_score(query, row["label"] + " " + row["statement"])
                if score:
                    scored.append((score, -order, row))
            scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
            items = []
            used = len("以下是与当前问题相关、已有证据支持的用户画像（L3）：\n")
            for _score, _order, row in scored:
                line = f'- {row["label"]}：{row["statement"]}\n'
                if len(items) >= limit or used + len(line) > max_chars:
                    break
                sources = connection.execute(
                    "SELECT source_layer,source_id FROM persona_sources "
                    "WHERE persona_id=? ORDER BY source_layer,source_id", (row["id"],),
                ).fetchall()
                message_ids = []
                for source in sources:
                    if source["source_layer"] == "l1":
                        evidence = connection.execute(
                            "SELECT source_message_id FROM memory_evidence WHERE memory_id=? "
                            "ORDER BY source_message_id", (source["source_id"],),
                        ).fetchall()
                    else:
                        evidence = connection.execute(
                            "SELECT DISTINCT e.source_message_id FROM scenario_memory_sources s "
                            "JOIN memory_evidence e ON e.memory_id=s.memory_id "
                            "WHERE s.scenario_id=? ORDER BY e.source_message_id", (source["source_id"],),
                        ).fetchall()
                    message_ids.extend(item["source_message_id"] for item in evidence)
                items.append(PersonaRecallItem(
                    row["id"], row["kind"], row["basis"], row["label"], row["statement"],
                    tuple((item["source_layer"], item["source_id"]) for item in sources),
                    tuple(dict.fromkeys(message_ids)),
                ))
                used += len(line)
        finally:
            connection.close()
        if not items:
            return PersonaRecallResult("", ())
        context = "以下是与当前问题相关、已有证据支持的用户画像（L3）：\n" + "\n".join(
            f"- {item.label}：{item.statement}" for item in items
        )
        return PersonaRecallResult(context, tuple(items))

    def close(self) -> None:
        """当前实现不持有长期连接。"""
