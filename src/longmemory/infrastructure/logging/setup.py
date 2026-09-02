"""只记录闭环元数据，禁止使用对话或供应商错误正文作为日志。"""

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOGGER = logging.getLogger("longmemory.audit")
LOGGER.addHandler(logging.NullHandler())
FIELDS = {"turn_id", "memory_id", "operation", "memory_ids", "count", "duration_ms", "assistant_id"}


def log_event(event: str, **fields: object) -> None:
    """白名单字段用于通过 ID 回查 SQLite，不复制原始敏感内容。"""

    if set(fields) - FIELDS:
        raise ValueError("审计事件包含非白名单字段。")
    LOGGER.info(json.dumps({
        "at": datetime.now(UTC).isoformat(), "event": event, **fields,
    }, ensure_ascii=False))


def configure_file_logging(path: Path) -> RotatingFileHandler:
    """最多保留当前文件及两个轮转文件；不修改全局 root logger。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    LOGGER.addHandler(handler)
    return handler


def close_file_logging(handler: RotatingFileHandler) -> None:
    LOGGER.removeHandler(handler)
    handler.close()
