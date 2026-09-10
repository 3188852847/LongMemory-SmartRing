"""检查并同步小智 SileroVAD 灵敏度档位。

只替换私有 YAML 中三个已知数值，保留密钥、注释和其他配置原字节；
apply 前必须携带 check 得到的摘要，防止覆盖用户并发修改。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

from sync_role import commit_change


PROFILES = {
    "normal": {"threshold": 0.50, "threshold_low": 0.30, "min_silence_duration_ms": 600},
    "noisy": {"threshold": 0.70, "threshold_low": 0.45, "min_silence_duration_ms": 650},
    "close_talk": {"threshold": 0.82, "threshold_low": 0.55, "min_silence_duration_ms": 700},
}


def _mapping_value(node, key, yaml):
    if not isinstance(node, yaml.MappingNode):
        raise ValueError("ambiguous_config")
    matches = [value for candidate, value in node.value if candidate.value == key]
    if len(matches) != 1:
        raise ValueError("ambiguous_config")
    return matches[0]


def prepare(path: Path, profile: str):
    import yaml

    if profile not in PROFILES or path.is_symlink() or not path.is_file():
        raise ValueError("invalid_target")
    original = path.read_bytes()
    if len(original) > 1024 * 1024:
        raise ValueError("oversized_config")
    text = original.decode("utf-8")
    config = yaml.safe_load(text)
    if not isinstance(config, dict) or config.get("read_config_from_api", False):
        raise ValueError("unsupported_config")
    if any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for token in yaml.scan(text)):
        raise ValueError("unsupported_alias")

    root = yaml.compose(text)
    silero_node = _mapping_value(_mapping_value(root, "VAD", yaml), "SileroVAD", yaml)
    silero = config.get("VAD", {}).get("SileroVAD")
    if not isinstance(silero, dict) or silero.get("type") != "silero":
        raise ValueError("unsupported_vad")

    expected = copy.deepcopy(config)
    expected_silero = expected["VAD"]["SileroVAD"]
    replacements = []
    for key, value in PROFILES[profile].items():
        node = _mapping_value(silero_node, key, yaml)
        if not isinstance(node, yaml.ScalarNode):
            raise ValueError("ambiguous_config")
        replacements.append((node.start_mark.index, node.end_mark.index, str(value)))
        expected_silero[key] = value

    updated = text
    for start, end, replacement in sorted(replacements, reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    if yaml.safe_load(updated) != expected:
        raise ValueError("unexpected_config_change")
    return original, updated.encode("utf-8"), config == expected


def sync(server: Path, body: dict):
    profile = body.get("profile")
    if body.get("action") not in {"check", "apply"} or profile not in PROFILES:
        raise ValueError("invalid_request")
    path = server / "data/.config.yaml"
    original, updated, matches = prepare(path, profile)
    result = commit_change(path, body, original, updated, matches, backup_label="vad")
    return result | {"profile": profile}


if __name__ == "__main__":
    try:
        request = json.loads(sys.stdin.buffer.read(4096))
        print(json.dumps(sync(Path(sys.argv[1]).resolve(), request)))
    except Exception:
        print('{"error":"vad_config_sync_failed"}')
        raise SystemExit(3)
