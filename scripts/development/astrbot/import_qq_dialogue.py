"""一次性将已绑定的 QQ 私聊接入前的文本追加到时间线。旧对话只归档。"""
from datetime import UTC, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from contextlib import closing
from uuid import NAMESPACE_URL, uuid5

from longmemory.entrypoints.api.routes.qq_memory import confirmed_owner
from longmemory.infrastructure.config.hy_deployment import build_daily_hy_runtime, load_hy_deployment
from longmemory.methods.contracts import MemoryEvent


def legacy_rows(conversations, owner, session, cutoff, tz):
    for cid, content in conversations:
        messages = json.loads(content)
        turn_at = None
        for index, item in enumerate(messages):
            if not isinstance(item, dict):
                continue
            role, parts = item.get("role"), item.get("content")
            if role == "user":
                turn_at = None
            if role not in {"user", "assistant"} or not isinstance(parts, list) or not parts:
                continue
            # AstrBot 把真实输入放在第一段，另外附加系统时间、昵称等提示。
            first = parts[0]
            if not isinstance(first, dict) or first.get("type") != "text":
                continue
            text = first.get("text")
            if not isinstance(text, str) or not text.strip() or text.startswith("<system_reminder>"):
                continue
            if role == "user":
                for part in parts[1:]:
                    meta = part.get("text") if isinstance(part, dict) else None
                    if not isinstance(meta, str) or not meta.startswith("<system_reminder>"):
                        continue
                    stamp = re.search(r"Current datetime: (\d{4}-\d\d-\d\d \d\d:\d\d) \(([^)]+)\)", meta)
                    if stamp and stamp[2] in {"CST", "中国标准时间", "China Standard Time", "+08"}:
                        turn_at = datetime.strptime(stamp[1], "%Y-%m-%d %H:%M").replace(tzinfo=tz).astimezone(UTC)
                        break
            # 旧库只记录每轮的分钟，接入后的同分钟交给已有来源，避免重复。
            if turn_at is None or turn_at >= cutoff or item.get("tool_calls"):
                continue
            key = str(uuid5(NAMESPACE_URL, json.dumps([owner, cid, index, role, text])))
            yield MemoryEvent("qq-history:" + key, role, text, turn_at, session)


def main(root):
    directory = root / "local/runtime/companion"
    owner = confirmed_owner(directory)
    if not owner:
        raise ValueError("confirmed_qq_window_required")
    session = "qq-" + hashlib.sha256(json.dumps(owner).encode()).hexdigest()[:32]
    with closing(sqlite3.connect(load_hy_deployment(root).source_path.as_uri()+"?mode=ro", uri=True)) as source:
        first, = source.execute("""SELECT min(m.created_at) FROM conversation_messages m JOIN source_dispatch d
            ON m.id=d.event_id WHERE d.session_id=? AND m.id NOT LIKE 'qq-history:%'""", (session,)).fetchone()
    cutoff = datetime.fromisoformat(first).replace(second=0, microsecond=0) if first else datetime.now(UTC)
    with closing(sqlite3.connect((directory/"data/data_v4.db").as_uri()+"?mode=ro", uri=True)) as native:
        rows = native.execute("SELECT conversation_id,content FROM conversations WHERE user_id=? ORDER BY created_at",
                              (owner[0]+":FriendMessage:"+owner[1],))
        events = list(legacy_rows(rows, owner, session, cutoff, timezone(timedelta(hours=8))))
    runtime = build_daily_hy_runtime(root)
    try:
        print("Imported QQ history:", runtime.import_dialogue(events))
    finally:
        runtime.close()


if __name__ == "__main__":
    main(Path(__file__).resolve().parents[3])
