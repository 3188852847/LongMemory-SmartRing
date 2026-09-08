"""安全检查或同步 Xiaozhi 的 OpenAI 兼容模型配置。

档案来自项目内被 Git 忽略的 env 文件。读取结果只返回地址、模型名和匹配
状态，永远不返回 API Key；写入前要求配置摘要，且先在原目录制作备份。
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

from sync_role import commit_change


PROFILE_FILES = {"campus": ".env", "official": ".env.deepseek.local"}


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def profile_values(project: Path, profile: str) -> dict[str, str]:
    if profile not in PROFILE_FILES:
        raise ValueError("unknown_profile")
    source = read_env(project / PROFILE_FILES[profile])
    required = ("LONGMEMORY_LLM_BASE_URL", "LONGMEMORY_LLM_MODEL", "LONGMEMORY_LLM_API_KEY")
    if any(not source.get(key, "").strip() for key in required):
        raise ValueError("missing_private_model_setting")
    base_url = source["LONGMEMORY_LLM_BASE_URL"].strip().rstrip("/")
    parsed = urlparse(base_url)
    allow_http = source.get("LONGMEMORY_LLM_ALLOW_HTTP", "false").lower() == "true"
    if (parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query
            or parsed.fragment or base_url.endswith("/chat/completions")
            or (parsed.scheme == "http" and not allow_http)):
        raise ValueError("invalid_base_url")
    # LongMemory 客户端接受官方文档给出的域名根地址；当前 Xiaozhi 启动
    # 契约统一要求 /v1。这里只做协议等价的适配，不反向改写 env 档案。
    if parsed.path.rstrip("/") in {"", "/"}:
        base_url += "/v1"
    elif not parsed.path.rstrip("/").endswith("/v1"):
        raise ValueError("invalid_base_url")
    return {"base_url": base_url, "model_name": source["LONGMEMORY_LLM_MODEL"].strip(),
            "api_key": source["LONGMEMORY_LLM_API_KEY"].strip()}


def _mapping_value(node, key, yaml):
    if not isinstance(node, yaml.MappingNode):
        raise ValueError("ambiguous_config")
    matches = [value for candidate, value in node.value if candidate.value == key]
    if len(matches) != 1:
        raise ValueError("ambiguous_config")
    return matches[0]


def prepare(project: Path, server: Path, profile: str):
    import yaml

    values = profile_values(project, profile)
    path = server / "data/.config.yaml"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("unsafe_config")
    original = path.read_bytes()
    text = original.decode("utf-8")
    config = yaml.safe_load(text)
    if not isinstance(config, dict) or config.get("read_config_from_api", False):
        raise ValueError("unsupported_config")
    selected_name = (config.get("selected_module") or {}).get("LLM")
    target = (config.get("LLM") or {}).get(selected_name)
    if not isinstance(selected_name, str) or not isinstance(target, dict) or target.get("type") != "openai":
        raise ValueError("unsupported_provider")
    if any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for token in yaml.scan(text)):
        raise ValueError("unsupported_alias")
    root = yaml.compose(text)
    selected_node = _mapping_value(_mapping_value(root, "selected_module", yaml), "LLM", yaml)
    provider_node = _mapping_value(_mapping_value(root, "LLM", yaml), selected_name, yaml)
    if not isinstance(selected_node, yaml.ScalarNode):
        raise ValueError("ambiguous_config")
    replacements = []
    for key, value in values.items():
        node = _mapping_value(provider_node, key, yaml)
        if not isinstance(node, yaml.ScalarNode):
            raise ValueError("ambiguous_config")
        replacements.append((node.start_mark.index, node.end_mark.index, json.dumps(value, ensure_ascii=False)))
    updated_text = text
    for start, end, replacement in sorted(replacements, reverse=True):
        updated_text = updated_text[:start] + replacement + updated_text[end:]
    expected = copy.deepcopy(config)
    expected["LLM"][selected_name].update(values)
    if yaml.safe_load(updated_text) != expected:
        raise ValueError("unexpected_config_change")
    matches = all(target.get(key) == value for key, value in values.items())
    return path, original, updated_text.encode("utf-8"), matches, {
        "profile": profile, "provider_name": selected_name,
        "base_url": values["base_url"], "model": values["model_name"],
        "configured_base_url": str(target.get("base_url", "")),
        "configured_model": str(target.get("model_name", "")),
        "transport": urlparse(values["base_url"]).scheme, "api_key_configured": True,
    }


def action(project: Path, server: Path, profile: str, *, apply: bool = False,
           expected_digest: str | None = None) -> dict:
    path, original, updated, matches, summary = prepare(project, server, profile)
    body = {"action": "apply" if apply else "check"}
    if apply:
        body["expected_digest"] = expected_digest
    result = commit_change(path, body, original, updated, matches, backup_label="model")
    if apply and result.get("config_matches"):
        # apply 回执描述写入后的磁盘目标，避免页面把成功结果与写入前字段并列。
        summary["configured_base_url"] = summary["base_url"]
        summary["configured_model"] = summary["model"]
    return result | summary


def update(project: Path, server: Path, profile: str = "campus") -> dict:
    """兼容旧命令：一次性预检后以摘要作为并发写入门槛。"""
    checked = action(project, server, profile)
    return action(project, server, profile, apply=True, expected_digest=checked["digest"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--profile", choices=tuple(PROFILE_FILES), default="campus")
    parser.add_argument("--action", choices=("check", "apply"), default="apply")
    parser.add_argument("--expected-digest")
    try:
        args = parser.parse_args()
        if args.action == "apply" and args.expected_digest:
            result = action(args.project.resolve(), args.server.resolve(), args.profile,
                            apply=True, expected_digest=args.expected_digest)
        elif args.action == "apply":
            result = update(args.project.resolve(), args.server.resolve(), args.profile)
        else:
            result = action(args.project.resolve(), args.server.resolve(), args.profile)
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        print('{"error":"model_config_operation_failed"}')
        raise SystemExit(3)
