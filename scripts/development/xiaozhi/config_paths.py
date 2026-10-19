"""小智配置归属与运行副本；只依赖标准库，兼容小智 Python 3.10。

受管源码目录由厂家维护，人工配置保存在项目 local/config 中。显式指定的
其他服务实例仍使用自己的 data 配置，避免把测试或另一实例绑定到个人配置。
"""
from pathlib import Path
import hashlib
import json
import os
import uuid
import argparse
import tempfile

SERVER_PARTS = ("local", "runtime", "xiaozhi-esp32-server", "main", "xiaozhi-server")


def managed_project(server: Path):
    server = Path(server).absolute()
    if tuple(server.parts[-5:]) == SERVER_PARTS:
        return server.parents[4]
    return None


def config_path(server: Path) -> Path:
    project = managed_project(server)
    path = project / "local/config/xiaozhi.yaml" if project else Path(server) / "data/.config.yaml"
    if project:
        _safe(path, project)
    return path


def backup_path(path: Path, name: str) -> Path:
    if path.name == "xiaozhi.yaml" and path.parent.parts[-2:] == ("local", "config"):
        project = path.parents[2]
        target = project / "local/archive/config-backups" / name
        _safe(target, project)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target
    return path.with_name(name)


def _safe(path: Path, root: Path):
    # resolve 会跟随联接；逐级拒绝重解析目录及软链接，且核对最终边界。
    root = root.absolute()
    path = path.absolute()
    try:
        path.relative_to(root)
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError("unsafe_config_path") from None
    for candidate in (path, *path.parents):
        if candidate == root.parent:
            break
        if candidate.is_symlink() or (candidate.exists() and getattr(candidate.stat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("unsafe_config_path")


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        # 深工作树中的目标本身可合法打开；重复目标长名再加UUID会超过
        # Windows原生路径上限。短随机独占临时名仍在同目录原子替换。
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".c-", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def render_runtime_config(server: Path, *, model_override=None):
    """启动前生成字节相同的厂家消费副本；拒绝覆盖手工变动的副本。

回执仅包含摘要及相对路径，绝不包含 YAML、密钥或角色正文。副本和来源
回执的写入可重复；任一步失败都必须让启动失败，不能假定新配置已生效。
"""
    project = managed_project(server)
    if project is None:
        if model_override is not None:
            raise ValueError("owned_gateway_requires_managed_project")
        return {"managed": False}
    source = config_path(server)
    target = Path(server) / "data/.config.yaml"
    marker = target.with_name(".config.source.json")
    for path in (source, target, marker):
        _safe(path, project)
    original_source = source.read_bytes()
    content = original_source
    if not content or len(content) > 1024 * 1024:
        raise ValueError("invalid_canonical_config")
    if model_override is not None:
        from voice_budget import validate_configuration
        import yaml
        model_override = validate_configuration(model_override)
        config = yaml.safe_load(content)
        name = config["selected_module"]["LLM"]
        if name != "CampusLLM" or config["LLM"][name].get("type") != "openai":
            raise ValueError("owned_gateway_provider_mismatch")
        config["LLM"][name].update({key: model_override[key] for key in
            ("base_url", "api_key", "model_name", "max_tokens", "timeout")})
        content = yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode("utf-8")
    digest = _digest(content)
    if target.exists() and (not target.is_file() or target.stat().st_size > 1024 * 1024):
        raise ValueError("invalid_runtime_config")
    old = target.read_bytes() if target.exists() else None
    if old is not None and old != content:
        try:
            previous = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError("unmanaged_runtime_config") from None
        if previous.get("source") != "local/config/xiaozhi.yaml" or previous.get("sha256") != _digest(old):
            raise ValueError("runtime_config_changed")
        archive = project / "local/archive/config-generated" / ("xiaozhi-" + uuid.uuid4().hex + ".yaml")
        _safe(archive, project)
        archive.parent.mkdir(parents=True, exist_ok=True)
        with archive.open("xb") as handle:
            handle.write(old)
    if old != content:
        _atomic(target, content)
    if source.read_bytes() != original_source or target.read_bytes() != content:
        raise ValueError("config_generation_unverified")
    body = {"version": 1, "source": "local/config/xiaozhi.yaml", "sha256": digest}
    if model_override is not None:
        body.update(canonical_sha256=_digest(original_source), model_projection="owned_hy_gateway")
    _atomic(marker, json.dumps(body, indent=2).encode("utf-8"))
    return {"managed": True, "sha256": digest}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-dir", type=Path,
                        default=Path(__file__).resolve().parents[3].joinpath(*SERVER_PARTS))
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    try:
        if args.render:
            result = render_runtime_config(args.server_dir)
        else:
            path = config_path(args.server_dir)
            result = {"managed": managed_project(args.server_dir) is not None,
                      "canonical_exists": path.is_file()}
        print(json.dumps(result))
        return 0
    except Exception:
        print('{"error":"config_generation_failed"}')
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
