"""在小智现有环境中核对共享路径，再复用旧启动工具；不输出配置内容。"""

from pathlib import Path
import sys


def shared_paths_match(config, root, database):
    """只核对明确的共享空间；不把两份配置强行覆盖成同一份。"""
    if config["selected_module"]["Memory"] != "LongMemory":
        return False
    memory = config["Memory"]["LongMemory"]
    expected = {"database_path": database, "project_root": root,
                "python_executable": root / ".venv/Scripts/python.exe"}
    return all(Path(memory[key]).resolve() == value.resolve() for key, value in expected.items())


def main():
    try:
        root, server, database = (Path(value).resolve() for value in sys.argv[1:4])
        lan_ip = sys.argv[4]
        sys.path.insert(0, str(root / "scripts/development/xiaozhi"))
        import yaml
        import setup
        config = yaml.safe_load((server / "data/.config.yaml").read_text(encoding="utf-8"))
        setup.validate_config(config, lan_ip)
        if not shared_paths_match(config, root, database):
            return 3
        sys.argv = [str(root / "scripts/development/xiaozhi/setup.py"), "start", "--server-dir", str(server),
                    "--lan-ip", lan_ip, "--allow-insecure-http", "--device-control"]
        return setup.main()
    except Exception:
        return 3  # 私有配置/路径错误，绝不回传 YAML 或第三方异常正文。


if __name__ == "__main__":
    raise SystemExit(main())
