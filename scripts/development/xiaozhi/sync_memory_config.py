"""检查或同步 Xiaozhi 的圆屏记忆提供器；不读取、迁移或删除记忆数据。"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from sync_role import commit_change


PROFILES = {
    "longmemory": "LongMemory",
    "xiaozhi_local": "mem_local_short",
    "none": "nomem",
}


def _mapping_value(node, key, yaml):
    if not isinstance(node, yaml.MappingNode):
        raise ValueError("ambiguous_config")
    matches = [value for candidate, value in node.value if candidate.value == key]
    if len(matches) != 1:
        raise ValueError("ambiguous_config")
    return matches[0]


def prepare(server: Path, profile: str):
    import yaml

    if profile not in PROFILES:
        raise ValueError("unknown_profile")
    path = server / "data/.config.yaml"
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
    target_name = PROFILES[profile]
    existing = memories.get(target_name)
    expected_entry = ({"type": "mem_local_short", "llm": None}
                      if profile == "xiaozhi_local" else {"type": target_name.lower()})
    if existing is not None and (
            not isinstance(existing, dict) or existing.get("type") != expected_entry["type"]):
        raise ValueError("conflicting_provider")
    if any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for token in yaml.scan(text)):
        raise ValueError("unsupported_alias")
    root = yaml.compose(text)
    selected_node = _mapping_value(_mapping_value(root, "selected_module", yaml), "Memory", yaml)
    memory_node = _mapping_value(root, "Memory", yaml)
    if not isinstance(selected_node, yaml.ScalarNode) or not isinstance(memory_node, yaml.MappingNode):
        raise ValueError("ambiguous_config")
    replacements = [(selected_node.start_mark.index, selected_node.end_mark.index,
                     json.dumps(target_name, ensure_ascii=False))]
    if existing is None:
        insertion = (f"  {target_name}:\n    type: {expected_entry['type']}\n")
        if profile == "xiaozhi_local":
            insertion += "    llm: null\n"
        replacements.append((memory_node.end_mark.index, memory_node.end_mark.index, insertion))
    updated_text = text
    for start, end, replacement in sorted(replacements, reverse=True):
        updated_text = updated_text[:start] + replacement + updated_text[end:]
    expected = copy.deepcopy(config)
    expected["selected_module"]["Memory"] = target_name
    expected["Memory"].setdefault(target_name, expected_entry)
    if yaml.safe_load(updated_text) != expected:
        raise ValueError("unexpected_config_change")
    matches = selected.get("Memory") == target_name and existing is not None
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
    parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
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
