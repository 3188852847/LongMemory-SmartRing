"""从现有 SQLite L1 中只读扩展明确的事实变化时间线。"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
import sqlite3

from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.application.memory_management.temporal_history import (
    TemporalHistoryError,
    build_temporal_fact_history,
)
from longmemory.application.temporal_recall import (
    TemporalRecallItem,
    TemporalRecallResult,
    classify_temporal_query,
)
from longmemory.core.common.identifiers import MemoryId
from longmemory.core.memory.retrieval.service import is_memory_effective


class SQLiteTemporalRecallProvider:
    """只有明确历史意图且已有当前 L1 锚点时，才读取退役变化链。"""

    def __init__(
        self, database: Path,
        *, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.database = database.resolve()
        self._clock = clock

    def recall(
        self, query: str, *, current_memory_ids: tuple[str, ...], limit: int = 10,
    ) -> TemporalRecallResult:
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("temporal_recall_limit_invalid")
        intent = classify_temporal_query(query)
        if intent is None or not current_memory_ids:
            return TemporalRecallResult("", (), intent)
        if len(current_memory_ids) > 10 or len(set(current_memory_ids)) != len(current_memory_ids):
            raise ValueError("temporal_recall_anchor_ids_invalid")

        connection = sqlite3.connect(
            self.database.as_uri() + "?mode=ro", uri=True, timeout=2,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only = ON")
            # 内容、变化边与来源必须来自同一快照；显式读事务避免两个
            # SELECT 之间的管理写入拼出“旧正文 + 新证据”的混合结果。
            connection.execute("BEGIN")
            store = SQLiteMemoryStore(connection)
            memories = store.list_all()
            by_id = {str(item.id): item for item in memories}
            now = self._clock()
            selected = []
            seen = set(current_memory_ids)
            for anchor_id in current_memory_ids:
                anchor = by_id.get(anchor_id)
                # 调用方给的是先前召回的 ID，不能当作永久有效的授权。
                # 已退役锚点若继续向后遍历，会把新的当前事实错标为历史。
                if (
                    anchor is None
                    or anchor.retired_at is not None
                    or anchor.superseded_by_id is not None
                    or not is_memory_effective(anchor, now)
                ):
                    continue
                try:
                    history = build_temporal_fact_history(
                        memories, MemoryId(anchor_id),
                    )
                except TemporalHistoryError:
                    # 一条损坏链不能放开为历史上下文；其他锚点仍可独立检查。
                    continue
                if not history.has_explicit_change:
                    continue
                for memory in history.entries:
                    key = str(memory.id)
                    if key in seen:
                        continue
                    selected.append((memory, anchor_id))
                    seen.add(key)
                    if len(selected) >= limit:
                        break
                if len(selected) >= limit:
                    break
            items = tuple(TemporalRecallItem(
                str(memory.id), memory.content,
                memory.valid_from.isoformat() if memory.valid_from else None,
                memory.valid_to.isoformat() if memory.valid_to else None,
                tuple(str(e.source_message_id) for e in store.list_evidence(memory.id)),
            ) for memory, _anchor_id in selected)
        finally:
            connection.close()
        if not items:
            return TemporalRecallResult("", (), intent)
        lines = "\n".join(
            f"- {item.content}（生效：{item.valid_from or '未记录'}；结束：{item.valid_to or '仍有效'}）"
            for item in items
        )
        context = (
            "以下仅是与当前已召回事实属于同一条明确变化链的历史 L1；"
            "它们不代表现在仍然成立。回答历史问题时必须区分生效区间，"
            "不要用旧事实回答普通当前状态：\n" + lines
        )
        return TemporalRecallResult(context, items, intent)

    def close(self) -> None:
        """每次调用使用短连接，不持有数据库资源。"""
