"""在同一会话内按连续两条消息分块，保留原角色和时间，关键词召回。

复用原基线的词项提取，使第一轮比较主要观察记忆表示的差异。
这不是语义检索，也不保证优于原子事实；助手错误原文同样会进入块。
"""

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from longmemory.core.memory.retrieval.service import _extract_terms
from longmemory.methods.contracts import MemoryEvent, MemorySupport, MethodCapabilities, ObservationResult, RetrievedTrace, WriteTrace


def event_json(event):
    return {"event_id": event.event_id, "role": event.role, "content": event.content,
            "occurred_at": event.occurred_at.isoformat(), "session_id": event.session_id}


class DialogueChunks:
    name = "dialogue_chunks_v1"
    implementation_version = "1"
    capabilities = MethodCapabilities(source_trace=True, session_metadata=True)

    def __init__(self, state_path: Path, *, read_only=False):
        self.path, self.read_only, self.closed = state_path, read_only, False
        self.sealed = read_only or state_path.exists()
        self.events = []
        if state_path.exists():
            for row in json.loads(state_path.read_text(encoding="utf-8")):
                self.events.append(MemoryEvent(**{**row, "occurred_at": datetime.fromisoformat(row["occurred_at"])}))
        elif read_only:
            raise FileNotFoundError("没有冻结的分块状态。")

    def check(self):
        if self.closed:
            raise RuntimeError("方法已关闭。")

    def observe(self, event):
        self.check()
        if self.sealed:
            raise RuntimeError("当前分块状态已封存；本批处理基线不支持追加历史。")
        if any(item.event_id == event.event_id for item in self.events):
            raise ValueError("重复事件 ID。")
        self.events.append(event)
        return ObservationResult(event.event_id, (WriteTrace("append_message", event.event_id, (event.event_id,)),))

    def wait_until_ready(self):
        self.check()
        if not self.sealed:
            # 只用于运行器新建的独立状态；禁止覆盖已有实验产物。
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("x", encoding="utf-8") as stream:
                json.dump([event_json(event) for event in self.events], stream, ensure_ascii=False)
            self.sealed = True

    def recall(self, query):
        self.check()
        if not query.strip():
            raise ValueError("空查询。")
        groups = []
        for event in self.events:
            if not groups or len(groups[-1]) >= 2 or groups[-1][-1].session_id != event.session_id:
                groups.append([])
            groups[-1].append(event)
        candidates = []
        terms = _extract_terms(query)
        for group in groups:
            content = "\n".join(f"[{e.role} | {e.occurred_at.isoformat()} | session={e.session_id}] {e.content}" for e in group)
            # 日期、角色、会话 ID 不参与词项打分，避免元数据制造虚假命中。
            score = len(terms & _extract_terms("\n".join(e.content for e in group)))
            if score:
                candidates.append((score, RetrievedTrace(group[0].event_id, content, tuple(e.event_id for e in group))))
        candidates.sort(key=lambda item: item[0], reverse=True)
        retrieved = tuple(item[1] for item in candidates[:5])
        return MemorySupport(str(uuid4()), "\n\n".join(item.content for item in retrieved), retrieved)

    def close(self):
        self.closed = True
