"""检查或同步 Xiaozhi 的圆屏记忆提供器；不读取、迁移或删除记忆数据。"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from config_paths import config_path

from sync_role import commit_change


def _mapping_value(node, key, yaml):
    if not isinstance(node, yaml.MappingNode):
        raise ValueError("ambiguous_config")
    matches = [value for candidate, value in node.value if candidate.value == key]
    if len(matches) != 1:
        raise ValueError("ambiguous_config")
    return matches[0]


def prepare(server: Path, profile: str):
    import yaml

    if profile != "hy_memory":
        raise ValueError("unknown_profile")
    path = config_path(server)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("unsafe_config")
    original = path.read_bytes()
    text = original.decode("utf-8")
    config = yaml.safe_load(text)
    if not isinstance(config, dict) or config.get("read_config_from_api", False):
        raise ValueError("unsupported_config")
    selected = config.get("selected_module")
    memories = config.get("Memory")
    if not isinstance(selected, dict) or not isinstance(memories, dict):
        raise ValueError("unsupported_config")
    # 设备控制身份继续来自已安装的 LongMemory 配置，与本次选择解耦。
    longmemory = memories.get("LongMemory")
    if not isinstance(longmemory, dict) or longmemory.get("type") != "longmemory" or not longmemory.get("allowed_device_id"):
        raise ValueError("missing_control_identity")
    target_name = "LongMemory"
    if any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for token in yaml.scan(text)):
        raise ValueError("unsupported_alias")
    root = yaml.compose(text)
    selected_node = _mapping_value(_mapping_value(root, "selected_module", yaml), "Memory", yaml)
    if not isinstance(selected_node, yaml.ScalarNode):
        raise ValueError("ambiguous_config")
    updated_text = text[:selected_node.start_mark.index] + json.dumps(target_name) + text[selected_node.end_mark.index:]
    expected = copy.deepcopy(config)
    expected["selected_module"]["Memory"] = target_name
    if yaml.safe_load(updated_text) != expected:
        raise ValueError("unexpected_config_change")
    matches = selected.get("Memory") == target_name
    return path, original, updated_text.encode("utf-8"), matches, {
        "profile": profile,
        "provider_name": target_name,
        "configured_provider": str(selected.get("Memory", "")),
    }


def action(server: Path, profile: str, *, apply=False, expected_digest=None) -> dict:
    path, original, updated, matches, summary = prepare(server, profile)
    body = {"action": "apply" if apply else "check"}
    if apply:
        body["expected_digest"] = expected_digest
    result = commit_change(path, body, original, updated, matches, backup_label="memory")
    if apply and result.get("config_matches"):
        summary["configured_provider"] = summary["provider_name"]
    return result | summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--profile", choices=("hy_memory",), required=True)
    parser.add_argument("--action", choices=("check", "apply"), default="check")
    parser.add_argument("--expected-digest")
    try:
        args = parser.parse_args()
        checked = action(args.server.resolve(), args.profile)
        result = (action(args.server.resolve(), args.profile, apply=True,
                         expected_digest=args.expected_digest or checked["digest"])
                  if args.action == "apply" else checked)
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        print('{"error":"memory_config_operation_failed"}')
        raise SystemExit(3)
