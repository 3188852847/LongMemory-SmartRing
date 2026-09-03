"""严格区分可见历史、测试问题和仅评分可见的标签。"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path

from longmemory.methods.contracts import MemoryEvent


@dataclass(frozen=True)
class Question:
    id: str
    split: str
    category: str
    query: str
    abstain: bool
    answer_contains: str | None
    evidence_sets: tuple[tuple[str, ...], ...]
    required_terms: tuple[str, ...]


@dataclass(frozen=True)
class Dataset:
    name: str
    version: str
    sha256: str
    history: tuple[MemoryEvent, ...]
    questions: tuple[Question, ...]


def text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("数据集文本字段必须是非空字符串。")
    return value


def load_dataset(path: Path) -> Dataset:
    raw = path.read_bytes()
    if len(raw) > 2_000_000:
        raise ValueError("最小比较协议暂不接受超过 2 MB 的数据文件。")
    data = json.loads(raw)
    if data.get("schema_version") != 1 or data.get("synthetic") is not True:
        raise ValueError("当前协议仅接受显式标注的合成 v1 数据集。")
    history, ids = [], set()
    for row in data["history"]:
        # 显式字段映射，任何参考答案/标签都不会随字典传给记忆方法。
        event = MemoryEvent(text(row["event_id"]), text(row["role"]), text(row["content"]),
                            datetime.fromisoformat(text(row["occurred_at"])), text(row["session_id"]))
        if event.event_id in ids or (history and event.occurred_at < history[-1].occurred_at):
            raise ValueError("历史 ID 必须唯一，并按带时区的时间顺序排列。")
        ids.add(event.event_id)
        history.append(event)
    if not history or len(history) > 10000:
        raise ValueError("历史条数必须在 1–10000 之间。")
    questions, question_ids = [], set()
    for row in data["questions"]:
        qid = text(row["id"])
        if qid in question_ids or row["split"] not in {"dev", "holdout"} or type(row["abstain"]) is not bool:
            raise ValueError("问题 ID、划分或拒答标签不合法。")
        reference = row["answer_contains"]
        if row["abstain"]:
            if reference is not None or row["evidence_sets"] != []:
                raise ValueError("未知信息题没有答案文本或充分证据集。")
        else:
            text(reference)
            if not row["evidence_sets"]:
                raise ValueError("可回答题需要至少一组充分证据。")
        evidence = []
        for group in row["evidence_sets"]:
            if not isinstance(group, list) or not group or any(item not in ids for item in group):
                raise ValueError("证据必须引用当前历史中的消息 ID。")
            evidence.append(tuple(group))
        required = row.get("required_terms", [] if row["abstain"] else [reference])
        if not isinstance(required, list) or any(not isinstance(term, str) or not term.strip() for term in required):
            raise ValueError("答案初筛词必须是字符串列表。")
        if (row["abstain"] and required) or (not row["abstain"] and not required):
            raise ValueError("答案初筛词与拒答标签不一致。")
        questions.append(Question(qid, row["split"], text(row["category"]), text(row["query"]),
                                  row["abstain"], reference, tuple(evidence), tuple(required)))
        question_ids.add(qid)
    if not questions or len(questions) > 1000:
        raise ValueError("问题数必须在 1–1000 之间。")
    return Dataset(text(data["name"]), text(data["version"]), hashlib.sha256(raw).hexdigest(),
                   tuple(history), tuple(questions))
