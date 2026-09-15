"""在小智现有环境中核对共享路径，再复用旧启动工具；不输出配置内容。"""

from pathlib import Path
import argparse
import http.client
import json
import sys
import time


MEMORY_PROVIDERS = {
    "longmemory": "LongMemory",
    "xiaozhi_local": "mem_local_short",
    "none": "nomem",
}
CUSTOM_TTS_URLS = {
    "voxcpm2": "http://127.0.0.1:18768/v1/audio/speech",
    "sanotts": "http://127.0.0.1:18769/v1/audio/speech",
    "cosyvoice3": "http://127.0.0.1:18770/v1/audio/speech",
}


def memory_contract_matches(config, root, database, backend):
    """核对所选后端和设备控制身份；数据仍由各后端独立保存。"""
    if backend not in MEMORY_PROVIDERS:
        return False
    if config["selected_module"]["Memory"] != MEMORY_PROVIDERS[backend]:
        return False
    memory = config["Memory"]["LongMemory"]
    expected = {"database_path": database, "project_root": root,
                "python_executable": root / ".venv/Scripts/python.exe"}
    if not all(Path(memory[key]).resolve() == value.resolve() for key, value in expected.items()):
        return False
    selected = config["Memory"].get(MEMORY_PROVIDERS[backend], {})
    expected_type = {"longmemory": "longmemory", "xiaozhi_local": "mem_local_short", "none": "nomem"}[backend]
    return selected.get("type") == expected_type


def tts_matches(config, backend):
    if backend == "edge":
        return config.get("selected_module", {}).get("TTS") == "EdgeTTS"
    custom = config.get("TTS", {}).get("CustomTTS", {})
    params = custom.get("params", {})
    return (
        backend in CUSTOM_TTS_URLS
        and config.get("selected_module", {}).get("TTS") == "CustomTTS"
        and custom.get("type") == "custom"
        and custom.get("method") == "POST"
        and custom.get("url") == CUSTOM_TTS_URLS[backend]
        and custom.get("format") == "wav"
        and params.get("input") == "{prompt_text}"
        and params.get("response_format") == "wav"
        and params.get("stream") is False
    )


def wait_for_local_tts(backend, timeout=90):
    port = {"voxcpm2": 18768, "sanotts": 18769, "cosyvoice3": 18770}[backend]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            body = json.loads(response.read(4096))
            if response.status == 200 and body.get("ready") is True and body.get("provider") == backend:
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
        lan_ip, tts_backend, memory_backend = sys.argv[4:7]
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--voice-mode", choices=("pipeline", "doubao_realtime"), default="pipeline")
        parser.add_argument("--voice-latency-mode", choices=("realtime", "original"), default="realtime")
        parser.add_argument("--doubao-env", type=Path)
        arguments = parser.parse_args(sys.argv[7:])
        sys.path.insert(0, str(root / "scripts/development/xiaozhi"))
        import setup
        if arguments.voice_mode == "doubao_realtime":
            # 独立云端会话保留设备协议和控制桥，由 setup 核对身份与环境。
            # 不检查、同步或加载现有 ASR / LLM / TTS / 记忆提供器。
            sys.argv = [str(root / "scripts/development/xiaozhi/setup.py"), "start",
                        "--server-dir", str(server), "--lan-ip", lan_ip,
                        "--device-control", "--voice-mode", "doubao_realtime",
                        "--doubao-env", str(arguments.doubao_env or root / ".env.doubao.local")]
            return setup.main()
        import yaml
        config = yaml.safe_load((server / "data/.config.yaml").read_text(encoding="utf-8"))
        setup.validate_config(config, lan_ip, tts_backend)
        if (not memory_contract_matches(config, root, database, memory_backend)
                or not tts_matches(config, tts_backend)):
            return 3
        # 统一启动本来就是项目侧适配器的发布入口。这里只允许 setup 中列出的
        # 已知旧哈希升级；未知文件仍会拒绝覆盖，避免掩盖用户或上游修改。
        setup.install_memory_provider(server, allow_known_update=True)
        if tts_backend in CUSTOM_TTS_URLS and not wait_for_local_tts(tts_backend):
            return 4
        sys.argv = [str(root / "scripts/development/xiaozhi/setup.py"), "start", "--server-dir", str(server),
                    "--lan-ip", lan_ip, "--allow-insecure-http", "--device-control",
                    "--tts-backend", tts_backend,
                    "--voice-latency-mode", arguments.voice_latency_mode]
        return setup.main()
    except Exception:
        return 3  # 私有配置/路径错误，绝不回传 YAML 或第三方异常正文。


if __name__ == "__main__":
    raise SystemExit(main())
