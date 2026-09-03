"""单次本机 JSON 管道入口：Python 3.12 处理记忆，供小智 3.10 调用。

请求正文走 stdin，不放命令行；stdout 仅输出协议 JSON。每次独立打开/关闭
数据库，不共享跨线程连接，不启动网络服务，也不读取模型密钥。
"""

import argparse
import json
from pathlib import Path
import sys

from longmemory.bootstrap import open_memory_service
from longmemory.entrypoints.xiaozhi.mapping import extract_user_text
from longmemory.infrastructure.logging.setup import configure_file_logging, close_file_logging


def process_request(database: Path, request: dict) -> dict:
    if not isinstance(request, dict) or request.get("version") != 1:
        raise ValueError("不支持的协议版本")
    text = extract_user_text(request.get("query"))
    with open_memory_service(database) as memory:
        turn = memory.prepare(text)
    return {
        "version": 1,
        "context": turn.memory_context,
        "turn_id": str(turn.user_message.id),
        "added": sum(op.operation.value == "add" for op in turn.memory_operations),
        "retrieved": len(turn.retrieved_memories),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--audit-log", type=Path, required=True)
    args = parser.parse_args()
    handler = None
    try:
        # 原始消息长度已在适配层限制，管道入口仍独立验证，避免绕过边界。
        data = sys.stdin.buffer.read(65537)
        if len(data) > 65536:
            raise ValueError("请求过大")
        request = json.loads(data)
        handler = configure_file_logging(args.audit_log)
        result = process_request(args.database, request)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception as exc:
        # 不回显文本、数据库内容或第三方异常正文。
        print(json.dumps({"error": type(exc).__name__, "version": 1}))
        return 1
    finally:
        if handler is not None:
            close_file_logging(handler)


if __name__ == "__main__":
    raise SystemExit(main())
