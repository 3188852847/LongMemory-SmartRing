"""在 EdgeTTS 与本机隔离 TTS 服务之间检查/切换小智私有配置。

脚本不启动服务、不读取或输出密钥；apply 前要求调用方提供配置摘要。
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from config_paths import config_path
import sys

from sync_role import commit_change

VOX_URL = "http://127.0.0.1:18768/v1/audio/speech"
SANO_URL = "http://127.0.0.1:18769/v1/audio/speech"
COSY_URL = "http://127.0.0.1:18770/v1/audio/speech"
CUSTOM_URLS = {"voxcpm2": VOX_URL, "sanotts": SANO_URL, "cosyvoice3": COSY_URL}
BACKENDS = {"edge", *CUSTOM_URLS}


def _mapping_value(node, key, yaml):
    if not isinstance(node, yaml.MappingNode):
        raise ValueError("ambiguous_config")
    matches = [value for candidate, value in node.value if candidate.value == key]
    if len(matches) != 1:
        raise ValueError("ambiguous_config")
    return matches[0]


def prepare(path: Path, backend: str):
    import yaml

    if backend not in BACKENDS or path.is_symlink() or not path.is_file():
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
    selected = _mapping_value(_mapping_value(root, "selected_module", yaml), "TTS", yaml)
    if not isinstance(selected, yaml.ScalarNode):
        raise ValueError("ambiguous_config")

    selected_name = "EdgeTTS" if backend == "edge" else "CustomTTS"
    replacements = [(selected.start_mark.index, selected.end_mark.index,
                     json.dumps(selected_name, ensure_ascii=False))]
    expected = copy.deepcopy(config)
    expected.setdefault("selected_module", {})["TTS"] = selected_name
    if backend in CUSTOM_URLS:
        tts_node = _mapping_value(root, "TTS", yaml)
        tts = expected.get("TTS")
        if not isinstance(tts, dict):
            raise ValueError("unsupported_tts")
        existing = tts.get("CustomTTS")
        if existing is not None and (not isinstance(existing, dict) or existing.get("type") != "custom"):
            raise ValueError("unsupported_custom_tts")
        custom = copy.deepcopy(existing) if existing is not None else {}
        params = custom.get("params")
        if params is not None and not isinstance(params, dict):
            raise ValueError("unsupported_custom_tts")
        params = copy.deepcopy(params) if params is not None else {}
        params.update(input="{prompt_text}", response_format="wav", stream=False)
        custom.update(type="custom", method="POST", url=CUSTOM_URLS[backend], params=params,
                      format="wav", output_dir=custom.get("output_dir", "tmp/"), tts_timeout=90)
        custom.setdefault("headers", {})
        tts["CustomTTS"] = custom

        # 私有配置可能只覆盖当前 EdgeTTS。新增或替换 CustomTTS 这一局部块，
        # 不重写包含 LLM 密钥、角色和记忆路径的整份 YAML。
        dumped = yaml.safe_dump(custom, allow_unicode=True, sort_keys=False).rstrip("\n")
        custom_value = dumped.replace("\n", "\n    ")
        custom_matches = [value for candidate, value in tts_node.value if candidate.value == "CustomTTS"]
        if len(custom_matches) > 1:
            raise ValueError("ambiguous_config")
        if custom_matches:
            node = custom_matches[0]
            replacements.append((node.start_mark.index, node.end_mark.index, custom_value + "\n"))
        else:
            insertion = "  CustomTTS:\n    " + custom_value + "\n"
            replacements.append((tts_node.end_mark.index, tts_node.end_mark.index, insertion))

    updated = text
    for start, end, replacement in sorted(replacements, reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    if yaml.safe_load(updated) != expected:
        raise ValueError("unexpected_config_change")
    return original, updated.encode("utf-8"), config == expected


def sync(server: Path, body: dict):
    if body.get("action") not in {"check", "apply"} or body.get("backend") not in BACKENDS:
        raise ValueError("invalid_request")
    path = config_path(server)
    original, updated, matches = prepare(path, body["backend"])
    result = commit_change(path, body, original, updated, matches, backup_label="tts")
    return result | {"backend": body["backend"], "service_url": CUSTOM_URLS.get(body["backend"])}


if __name__ == "__main__":
    try:
        request = json.loads(sys.stdin.buffer.read(4096))
        print(json.dumps(sync(Path(sys.argv[1]).resolve(), request)))
    except Exception:
        print('{"error":"tts_backend_sync_failed"}')
        raise SystemExit(3)
