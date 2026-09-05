"""在小智现有环境中核对共享路径，再复用旧启动工具；不输出配置内容。"""

from pathlib import Path
import http.client
import json
import sys
import time


def shared_paths_match(config, root, database):
    """只核对明确的共享空间；不把两份配置强行覆盖成同一份。"""
    if config["selected_module"]["Memory"] != "LongMemory":
        return False
    memory = config["Memory"]["LongMemory"]
    expected = {"database_path": database, "project_root": root,
                "python_executable": root / ".venv/Scripts/python.exe"}
    return all(Path(memory[key]).resolve() == value.resolve() for key, value in expected.items())


def tts_matches(config, backend):
    if backend == "edge":
        return config.get("selected_module", {}).get("TTS") == "EdgeTTS"
    custom = config.get("TTS", {}).get("CustomTTS", {})
    params = custom.get("params", {})
    return (
        backend == "voxcpm2"
        and config.get("selected_module", {}).get("TTS") == "CustomTTS"
        and custom.get("type") == "custom"
        and custom.get("method") == "POST"
        and custom.get("url") == "http://127.0.0.1:18768/v1/audio/speech"
        and custom.get("format") == "wav"
        and params.get("input") == "{prompt_text}"
        and params.get("response_format") == "wav"
        and params.get("stream") is False
    )


def wait_for_voxcpm(timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        connection = http.client.HTTPConnection("127.0.0.1", 18768, timeout=0.5)
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            body = json.loads(response.read(4096))
            if response.status == 200 and body.get("ready") is True and body.get("provider") == "voxcpm2":
                return True
        except (OSError, http.client.HTTPException, json.JSONDecodeError):
            pass
        finally:
            connection.close()
        time.sleep(0.25)
    return False


def main():
    try:
        root, server, database = (Path(value).resolve() for value in sys.argv[1:4])
        lan_ip, tts_backend = sys.argv[4:6]
        sys.path.insert(0, str(root / "scripts/development/xiaozhi"))
        import yaml
        import setup
        config = yaml.safe_load((server / "data/.config.yaml").read_text(encoding="utf-8"))
        setup.validate_config(config, lan_ip)
        if not shared_paths_match(config, root, database) or not tts_matches(config, tts_backend):
            return 3
        if tts_backend == "voxcpm2" and not wait_for_voxcpm():
            return 4
        sys.argv = [str(root / "scripts/development/xiaozhi/setup.py"), "start", "--server-dir", str(server),
                    "--lan-ip", lan_ip, "--allow-insecure-http", "--device-control"]
        return setup.main()
    except Exception:
        return 3  # 私有配置/路径错误，绝不回传 YAML 或第三方异常正文。


if __name__ == "__main__":
    raise SystemExit(main())
