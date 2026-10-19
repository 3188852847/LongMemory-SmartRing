"""离线核验已安装分发与 API；不构造 client，不加载配置，不调用模型。"""

import argparse
from importlib import metadata
import inspect
import json

from .sdk_bridge import SDK_VERSION, SOURCE_COMMIT


def inspect_installation(*, check_api: bool = False) -> dict:
    result = {"expected_version": SDK_VERSION, "source_commit": SOURCE_COMMIT,
              "installed_version": None, "status": "missing", "client_constructed": False}
    try:
        result["installed_version"] = metadata.version("hy-memory")
    except metadata.PackageNotFoundError:
        return result
    if result["installed_version"] != SDK_VERSION:
        result["status"] = "version_mismatch"
        return result
    result["status"] = "metadata_only"
    if not check_api:
        return result
    # 只有独立 SDK 环境才执行该分支；第三方 import 的行为也需实测记录。
    try:
        from hy_memory import HyMemoryClient
        required = {"add": {"data", "user_id", "agent_id", "session_id", "source", "scene", "memory_at", "request_id", "meta"},
                    "search": {"query", "scene", "search_mode", "user_ids", "agent_ids", "include_sources", "schema_limit", "intention_limit"},
                    "get_user_profile": {"user_id"}, "close": set()}
        for name, parameters in required.items():
            if not parameters <= set(inspect.signature(getattr(HyMemoryClient, name)).parameters):
                result["status"] = "api_mismatch"
                return result
        result["status"] = "api_present_not_runtime_verified"
    except Exception:
        result["status"] = "import_or_api_failed"
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-api", action="store_true")
    args = parser.parse_args(argv)
    report = inspect_installation(check_api=args.check_api)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"metadata_only", "api_present_not_runtime_verified"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
