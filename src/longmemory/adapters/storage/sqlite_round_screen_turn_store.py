"""圆屏最终回答与既有用户 L0 的 SQLite 原子关联。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
import sqlite3
from uuid import uuid4


@dataclass(frozen=True)
class RoundScreenTurnResult:
    assistant_message_id: str
    created: bool


class SQLiteRoundScreenTurnStore:
    """保存实际助手文本，但不把服务端排队冒充圆屏已播放。"""

    def __init__(self, database: Path, clock=lambda: datetime.now(UTC)) -> None:
        self._database = database.resolve()
        self._clock = clock

    def record(self, *, user_message_id: str, answer: str,
               retrieved_l1_count: int, retrieved_l2_count: int,
               retrieved_l3_count: int,
               retrieval_evidence: tuple[dict, ...] | None = None) -> RoundScreenTurnResult:
        evidence = self._validate_evidence(
            retrieval_evidence,
            counts={
                "l1": retrieved_l1_count,
                "l2": retrieved_l2_count,
                "l3": retrieved_l3_count,
            },
        )
        connection = sqlite3.connect(
            self._database.as_uri() + "?mode=rw", uri=True, timeout=2,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT assistant_message_id,retrieved_l1_count,retrieved_l2_count,"
                "retrieved_l3_count FROM round_screen_turns "
                "WHERE user_message_id=?",
                (user_message_id,),
            ).fetchone()
            if existing is not None:
                saved = connection.execute(
                    "SELECT content FROM conversation_messages WHERE id=? AND role='assistant'",
                    (existing["assistant_message_id"],),
                ).fetchone()
                same = (
                    saved is not None and saved["content"] == answer
                    and existing["retrieved_l1_count"] == retrieved_l1_count
                    and existing["retrieved_l2_count"] == retrieved_l2_count
                    and existing["retrieved_l3_count"] == retrieved_l3_count
                )
                if same and evidence is not None:
                    receipt = connection.execute(
                        "SELECT 1 FROM round_screen_retrieval_receipts "
                        "WHERE user_message_id=?", (user_message_id,),
                    ).fetchone()
                    same = receipt is not None
                    saved_evidence = tuple(
                        tuple(row) for row in connection.execute(
                            "SELECT layer,item_id,rank,content_sha256 FROM "
                            "round_screen_retrieval_evidence WHERE user_message_id=? "
                            "ORDER BY layer,rank",
                            (user_message_id,),
                        ).fetchall()
                    )
                    same = same and saved_evidence == evidence
                if not same:
                    raise ValueError("round_screen_turn_conflict")
                connection.rollback()
                return RoundScreenTurnResult(existing["assistant_message_id"], False)
            source = connection.execute(
                "SELECT role FROM conversation_messages WHERE id=?",
                (user_message_id,),
            ).fetchone()
            if source is None or source["role"] != "user":
                raise ValueError("round_screen_user_turn_not_found")
            assistant_id = str(uuid4())
            completed_at = self._clock().isoformat()
            connection.execute(
                "INSERT INTO conversation_messages (id,role,content,created_at) "
                "VALUES (?,'assistant',?,?)",
                (assistant_id, answer, completed_at),
            )
            connection.execute(
                "INSERT INTO round_screen_turns "
                "(user_message_id,assistant_message_id,retrieved_l1_count,"
                "retrieved_l2_count,retrieved_l3_count,completed_at) "
                "VALUES (?,?,?,?,?,?)",
                (user_message_id, assistant_id, retrieved_l1_count,
                 retrieved_l2_count, retrieved_l3_count, completed_at),
            )
            if evidence is not None:
                connection.execute(
                    "INSERT INTO round_screen_retrieval_receipts (user_message_id) "
                    "VALUES (?)", (user_message_id,),
                )
            if evidence:
                connection.executemany(
                    "INSERT INTO round_screen_retrieval_evidence "
                    "(user_message_id,layer,item_id,rank,content_sha256) "
                    "VALUES (?,?,?,?,?)",
                    ((user_message_id, *item) for item in evidence),
                )
            connection.commit()
            return RoundScreenTurnResult(assistant_id, True)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _validate_evidence(
        value: tuple[dict, ...] | None, *, counts: dict[str, int],
    ) -> tuple[tuple[str, str, int, str], ...] | None:
        """验证协议证据；缺省表示兼容旧回执，空元组表示明确没有召回。"""

        if value is None:
            return None
        if not isinstance(value, tuple) or len(value) > 300:
            raise ValueError("round_screen_retrieval_evidence_invalid")
        normalized = []
        seen = set()
        for item in value:
            if not isinstance(item, dict) or set(item) != {
                "layer", "item_id", "rank", "content_sha256",
            }:
                raise ValueError("round_screen_retrieval_evidence_invalid")
            layer, item_id = item["layer"], item["item_id"]
            rank, digest = item["rank"], item["content_sha256"]
            if (layer not in counts or not isinstance(item_id, str)
                    or not 1 <= len(item_id.strip()) <= 200
                    or type(rank) is not int or rank < 1
                    or not isinstance(digest, str)
                    or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                    or (layer, item_id) in seen):
                raise ValueError("round_screen_retrieval_evidence_invalid")
            seen.add((layer, item_id))
            normalized.append((layer, item_id, rank, digest))
        normalized.sort(key=lambda item: (item[0], item[2]))
        for layer, count in counts.items():
            ranks = [item[2] for item in normalized if item[0] == layer]
            if ranks != list(range(1, count + 1)):
                raise ValueError("round_screen_retrieval_evidence_invalid")
        return tuple(normalized)
