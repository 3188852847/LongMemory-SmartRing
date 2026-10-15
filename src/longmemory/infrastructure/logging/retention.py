"""固定日志目录的元数据预算与只读保留计划；本工具没有删除/搬迁入口。"""

from collections import defaultdict
import argparse
import json
import os
from pathlib import Path
import re
import stat
import time


BUDGET_BYTES = 64 * 1024 * 1024
MIN_AGE_DAYS = 7
MAX_ENTRIES = 4096
STREAM = re.compile(r"(api-[1-9][0-9]*-[0-9a-f]{16}\.jsonl)(?:\.([12]))?")
FIXED = (
    ("launcher", "data/logs/launcher-events.jsonl", "launcher_singleton"),
    ("memory", "data/logs/xiaozhi-demo-v1.jsonl", "memory_audit"),
    ("xiaozhi", "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/tmp/server.log", "vendor"),
)


def _safe(base, path):
    """不跟随任何 symlink/junction，包括仍指向项目内的重解析点。"""
    try:
        path.relative_to(base)
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            try:
                info = current.lstat()
            except FileNotFoundError:
                return "missing"
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
                return "protected_link"
        return "safe"
    except (OSError, ValueError):
        return "unavailable"


def retention_plan(root, *, active_stream=None, inactive_streams=(), budget_bytes=BUDGET_BYTES,
                   min_age_days=MIN_AGE_DAYS, now=None):
    if type(budget_bytes) is not int or budget_bytes < 0 or type(min_age_days) is not int or min_age_days < 1:
        raise ValueError("invalid_retention_budget")
    inactive = set(inactive_streams)
    if any(not isinstance(name, str) or not STREAM.fullmatch(name) or name.endswith((".1", ".2")) for name in inactive):
        raise ValueError("invalid_inactive_stream")
    result = {"mode": "dry_run", "budget_bytes": budget_bytes, "min_age_days": min_age_days,
              "total_bytes": 0, "managed_bytes": 0, "vendor_bytes": 0,
              "owners": {}, "files": [], "candidate_streams": [], "candidate_bytes": 0,
              "state": "unconfigured", "complete": root is not None, "deletion_available": False,
              "scan_limit": MAX_ENTRIES}
    if root is None:
        return result
    base = Path(os.path.abspath(root))
    active_name = Path(active_stream).name if active_stream is not None else None
    timestamp = time.time() if now is None else now
    groups = defaultdict(list)

    def add(path, identity, owner, stream=None):
        state = _safe(base, path)
        row = {"id": identity, "owner": owner, "state": state, "bytes": None,
               "protection": "unknown_writer"}
        if state == "safe":
            try:
                info = path.lstat()
                if stat.S_ISREG(info.st_mode):
                    row.update(state="present", bytes=info.st_size)
                    result["total_bytes"] += info.st_size
                    bucket = "vendor_bytes" if owner == "vendor" else "managed_bytes"
                    result[bucket] += info.st_size
                    result["owners"][owner] = result["owners"].get(owner, 0) + info.st_size
                    if stream is not None:
                        groups[stream].append((row, info.st_mtime))
                else:
                    row["state"] = "not_a_file"
            except OSError:
                row["state"] = "unavailable"
        if owner == "vendor":
            row["protection"] = "vendor_managed"
        if row["state"] not in {"present", "missing"}:
            result["complete"] = False
        result["files"].append(row)

    for name, relative, owner in FIXED:
        for suffix in ("", ".1", ".2"):
            add(base / (relative + suffix), name + suffix, owner)
    directory = base / "data/logs/diagnostics"
    directory_state = _safe(base, directory)
    result["state"] = directory_state
    if directory_state == "safe":
        try:
            with os.scandir(directory) as entries:
                for index, entry in enumerate(entries):
                    if index >= MAX_ENTRIES:
                        result.update(complete=False, state="scan_limit_reached")
                        break
                    match = STREAM.fullmatch(entry.name)
                    add(directory / entry.name, entry.name if match else f"unknown-{index}",
                        "api_diagnostics" if match else "unknown", match[1] if match else None)
        except OSError:
            result.update(complete=False, state="unavailable")
    elif directory_state not in {"missing"}:
        result["complete"] = False
    managed_excess = max(0, result["managed_bytes"] - budget_bytes)
    possible = []
    for stream, files in groups.items():
        protection = ("active_writer" if stream == active_name else "unknown_writer" if stream not in inactive
                      else "minimum_age" if any(timestamp - modified < min_age_days * 86400 for _, modified in files)
                      else "declared_inactive")
        for row, _ in files:
            row["protection"] = protection
        if protection == "declared_inactive":
            possible.append((max(modified for _, modified in files), stream, files))
    if result["complete"]:
        for _, stream, files in sorted(possible):
            if result["candidate_bytes"] >= managed_excess:
                break
            result["candidate_streams"].append(stream)
            result["candidate_bytes"] += sum(row["bytes"] for row, _ in files)
    result["over_budget_bytes"] = managed_excess
    result["unresolved_bytes"] = max(0, managed_excess - result["candidate_bytes"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget-mib", type=int, default=64)
    parser.add_argument("--min-age-days", type=int, default=MIN_AGE_DAYS)
    parser.add_argument("--inactive-stream", action="append", default=[], help="只接受准确 api-PID-owner.jsonl 名称；须先独立核实已停止")
    args = parser.parse_args()
    # 根目录由本文件归属决定，无任意路径扫描参数，也没有 apply/delete 开关。
    print(json.dumps(retention_plan(Path(__file__).absolute().parents[4],
                                   inactive_streams=args.inactive_stream,
                                   budget_bytes=args.budget_mib * 1024 * 1024,
                                   min_age_days=args.min_age_days), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
