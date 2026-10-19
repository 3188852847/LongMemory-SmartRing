"""独立小智服务的教学启动工具，不导入或修改 LongMemory Core。

用小智自己的 .venv 执行本文件。init/check-config 不发请求；
check-stream 才访问用户配置的模型，start 才启动本机服务。
受管实例配置位于 local/config/xiaozhi.yaml，启动前生成厂家消费副本；
实时模式使用项目已忽略的 local/config/.env.doubao.local。两种配置都不输出到日志或复制到示例。
"""

import argparse
import hashlib
import ipaddress
import os
from pathlib import Path
from config_paths import config_path, render_runtime_config
import subprocess
import sys
import re
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SERVER = ROOT / "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server"
DEFAULT_DOUBAO_ENV = ROOT / "local/config/.env.doubao.local"
DEFAULT_FFMPEG = ROOT / "local/tools/ffmpeg/bin"
CUSTOM_TTS_URLS = {
    "voxcpm2": "http://127.0.0.1:18768/v1/audio/speech",
    "sanotts": "http://127.0.0.1:18769/v1/audio/speech",
    "cosyvoice3": "http://127.0.0.1:18770/v1/audio/speech",
}
LEGACY_MEMORY_PROVIDER_SHA256 = {
    # T 20261015 部署版；X 已核对主源码与实际消费副本同摘要，只允许精确升级。
    "98998f2fcf28c754bc39336129b072c737dd2cc58ef9505137625661452ce018",
    # Q 显式语音关联接入前的日用发布版，与 e15a867 文件字节完全相同。
    "82e43c8d59de69a5ddc8cc62eb2b96eee555efec36c339a800206bcab062253d",
    # 明确日期历史证据字段加入 Runtime、但薄适配器尚未同步契约的已发布版本。
    "47ce4e06f4841fa47c1c7e5f32bc8996bec5ed0e10c646f109348164c9c6f131",
    # 日常 L1 提取账本加入前的已发布提供器；用户现场当前正使用此精确版本。
    "631569ac42c2cd623590d4f26958747c59e6fd812a25c3c22601418ec2c79991",
    # 召回策略回执校验加入前的上一版；已在用户当前小智目录精确核对。
    "c48245188b7398432e7b24cd25d4050c512e56d05d52d1f1617faa362c87ce15",
    # G2 只保存三层召回数量、尚未保存条目索引的已发布回执版。
    "4a61e6b6bbab081304582b10516e3213d569535ce094e35996b6d4789ef0469a",
    # G2 圆屏回答完成回执前的已发布计时版提供器。
    "28969e5bee2c97cbe5c3798ebb80fe5075f6b218e0b1f2fec03e60a2d8ad1357",
    # P5/U8 延迟分段计时前的已发布共享 Runtime 提供器。
    "b9c76faf1cc123bd99111eb35e2aea544ac76f6bf7033d4984d805a87b746041",
    # 逐轮启动 Python 3.12 子进程的已发布版本；只允许从这个精确内容升级。
    "aeb5df153de32986df4cfece8cf8d6ecea6b49dd936f250497b684eb41ca3ac4",
    # P3.1 本机首次安装后追加 URL/令牌严格校验前的过渡版本。
    "c0dfe5b56b83ba3c26742147a345f15ca5600d03e293a10fd6b0d59e3aefdf81",
    # P3.1 共享 Runtime 的已发布版本；可由 Git 历史提交 894b5fb/ff15db0 追溯。
    "005104cc605aa05ad834774d649a0d088bf450bcc7040e44d0e40a2964d9be52",
}


class SetupError(Exception):
    """只容纳本工具编写的、不含配置原文的错误说明。"""


def init_config(server_dir: Path) -> Path:
    """仅首次生成私有配置；使用 x 模式，已有文件绝不覆盖。"""
    if not (server_dir / "app.py").is_file():
        raise SetupError("目标目录没有 app.py，请检查服务目录。")
    target = config_path(server_dir)
    template = (ROOT / "config/examples/xiaozhi.example.yaml").read_text(encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="") as handle:
        handle.write(template)
    return target


def validate_lan_ip(value: str) -> str:
    """仅接受明确的 RFC1918 单播地址；拒绝所有网卡、公网和 VPN 共享地址。"""
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        raise SetupError("--lan-ip 必须是电脑网卡的 IPv4 地址。") from None
    private_ranges = [ipaddress.ip_network(net) for net in
                      ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    if not any(address in network for network in private_ranges):
        raise SetupError("局域网演示只允许 RFC1918 地址，不接受 0.0.0.0、公网或回环地址。")
    return str(address)


def validate_tts_config(config: dict, backend: str) -> None:
    """按本次明确选择的后端核对配置，避免把另一个合法后端误判为配置损坏。"""
    selected = config.get("selected_module", {}).get("TTS")
    if backend == "edge":
        if selected != "EdgeTTS":
            raise SetupError("当前启动选择 EdgeTTS，但私有配置尚未同步为 EdgeTTS。")
        return
    if backend not in CUSTOM_TTS_URLS:
        raise SetupError("--tts-backend 只允许 edge、voxcpm2、sanotts 或 cosyvoice3。")

    custom = config.get("TTS", {}).get("CustomTTS", {})
    params = custom.get("params", {}) if isinstance(custom, dict) else {}
    expected = {
        "type": "custom",
        "method": "POST",
        "url": CUSTOM_TTS_URLS[backend],
        "format": "wav",
    }
    if (
        selected != "CustomTTS"
        or not isinstance(custom, dict)
        or any(custom.get(key) != value for key, value in expected.items())
        or not isinstance(params, dict)
        or params.get("input") != "{prompt_text}"
        or params.get("response_format") != "wav"
        or params.get("stream") is not False
    ):
        raise SetupError(f"当前启动选择 {backend}，但 CustomTTS 配置与本机适配服务契约不一致。")


def validate_config(config: dict, lan_ip: str | None = None, tts_backend: str = "edge",
                    voice_mode: str = "pipeline") -> dict:
    """检查本阶段边界，避免沿用上游默认公网监听或默认模型。"""
    server = config.get("server", {})
    expected_ip = validate_lan_ip(lan_ip) if lan_ip else "127.0.0.1"
    if server.get("ip") != expected_ip:
        raise SetupError("server.ip 与本次模式不一致；局域网启动须显式指定 --lan-ip。")
    if server.get("port") != 8000 or server.get("http_port") != 8003:
        raise SetupError("本阶段端口必须为 8000 / 8003。")
    if server.get("websocket") != f"ws://{expected_ip}:8000/xiaozhi/v1/":
        raise SetupError("WebSocket 地址必须指向本次监听 IP 的 8000 端口。")
    if lan_ip:
        if server.get("vision_explain") != f"http://{expected_ip}:8003/mcp/vision/explain":
            raise SetupError("vision_explain 地址应与本次监听 IP 和 HTTP 端口一致。")
        auth = server.get("auth", {})
        if auth.get("enabled") is not True or auth.get("allowed_devices") != []:
            raise SetupError("局域网模式要求 auth.enabled: true 且 allowed_devices: []，不使用免鉴权名单。")
    if config.get("manager-api", {}).get("url"):
        raise SetupError("本阶段不使用智控台配置。")
    if voice_mode not in {"pipeline", "doubao_realtime"}:
        raise SetupError("语音模式无效。")
    if voice_mode == "doubao_realtime":
        if config.get("read_config_from_api", False):
            raise SetupError("实时语音备用模式只支持本地设备配置。")
        allowed = config.get("Memory", {}).get("LongMemory", {}).get("allowed_device_id", "")
        if not re.fullmatch(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}", str(allowed)):
            raise SetupError("实时语音需要保留已核实的单设备 allowed_device_id。")
        # 这里只沿用设备身份；不加载Memory，也不要求三段式模型/TTS配置。
        return {}
    selected = config.get("selected_module", {})
    memory_name = selected.get("Memory")
    if memory_name not in ("nomem", "mem_local_short", "LongMemory"):
        raise SetupError("Memory 必须为 nomem、mem_local_short 或 LongMemory。")
    if memory_name == "LongMemory":
        memory = config.get("Memory", {}).get("LongMemory", {})
        if memory.get("type") != "longmemory":
            raise SetupError("LongMemory.type 必须为 longmemory。")
        if not re.fullmatch(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}", str(memory.get("allowed_device_id", ""))):
            raise SetupError("请填写已核实的单个圆屏 MAC 作为 allowed_device_id。")
        for key in ("python_executable", "project_root", "database_path", "audit_log"):
            if not isinstance(memory.get(key), str) or not Path(memory[key]).is_absolute():
                raise SetupError("LongMemory 的四个本地路径必须完整填写为绝对路径。")
        if "<memory>" not in config.get("prompt", "") or "</memory>" not in config.get("prompt", ""):
            raise SetupError("prompt 必须包含 <memory></memory>，否则上游快速提示阶段不会注入记忆。")
    elif memory_name == "mem_local_short":
        memory = config.get("Memory", {}).get("mem_local_short", {})
        if memory.get("type") != "mem_local_short" or "llm" not in memory:
            raise SetupError("mem_local_short 配置不完整。")
    else:
        # 小智原生 nomem 是零配置实现；历史配置可能只在 selected_module
        # 里选择它，而没有显式的 Memory.nomem 节。若用户确实写了该节，
        # 才检查其类型，兼容旧配置的同时仍能发现拼写错误。
        memory = config.get("Memory", {}).get("nomem")
        if memory is not None and memory.get("type") != "nomem":
            raise SetupError("nomem 配置不完整。")
    validate_tts_config(config, tts_backend)
    expected = dict(VAD="SileroVAD", ASR="FunASR", LLM="CampusLLM",
                    Memory=memory_name, Intent="nointent")
    if any(selected.get(key) != value for key, value in expected.items()):
        raise SetupError("所选模块与本阶段模板不一致，请核对 selected_module。")
    model = config.get("LLM", {}).get("CampusLLM", {})
    if model.get("type") != "openai":
        raise SetupError("CampusLLM.type 必须为 openai。")
    for key in ("base_url", "api_key", "model_name"):
        value = model.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SetupError(f"请在私有配置中填写 {key}。")
        if any(mark in value for mark in ("FILL_LOCALLY", "YOUR_MODEL_HOST", "${", "你的")):
            raise SetupError(f"{key} 仍是占位内容，请在私有配置中填写。")
    url = urlsplit(model["base_url"])
    if url.scheme not in ("http", "https") or not url.hostname:
        raise SetupError("模型地址必须是 HTTP(S) URL。")
    if url.username or url.password or url.query or url.fragment:
        raise SetupError("模型 URL 不应带账户、密码、查询参数或片段。")
    if not url.path.rstrip("/").endswith("/v1"):
        raise SetupError("模型基础地址必须以 /v1 结尾，不填完整 chat/completions 路径。")
    return model


def reject_ota_binaries(server_dir: Path) -> None:
    """此次只切换服务端，不允许上游 OTA 路径自动分发固件。"""
    if any((server_dir / "data" / "bin").glob("*.bin")):
        raise SetupError("data/bin 中存在固件；本轮不做 OTA 升级，请先单独处理这些文件，不会自动删除。")


def install_memory_provider(server_dir: Path, *, allow_known_update: bool = False) -> Path:
    """只新增自己的提供器文件；已有不同内容时拒绝覆盖。"""
    if not (server_dir / "core/providers/memory/base.py").is_file():
        raise SetupError("目标不是预期的小智服务目录。")
    target = server_dir / "core/providers/memory/longmemory/longmemory.py"
    content = Path(__file__).with_name("longmemory_provider.py").read_bytes()
    if target.exists():
        if target.read_bytes() != content:
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if not allow_known_update or digest not in LEGACY_MEMORY_PROVIDER_SHA256:
                raise SetupError("已有不同或用户修改过的 LongMemory 提供器，未覆盖，请先核对。")
            target.write_bytes(content)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write(content)
    return target


def require_transport_consent(model: dict, allowed: bool) -> None:
    if urlsplit(model["base_url"]).scheme == "http" and not allowed:
        raise SetupError("HTTP 明文传输密钥和内容；接受校园网合成测试风险后显式加 --allow-insecure-http。")


def prepare_environment(server_dir: Path, ffmpeg_dir: Path, voice_mode="pipeline") -> dict:
    """只改变子进程环境，不修改用户/系统永久 PATH。"""
    if voice_mode not in {"pipeline", "doubao_realtime"}:
        raise SetupError("语音模式无效。")
    opus_dir = server_dir / "native" / "libopus-1.6.1" / "Library" / "bin"
    paths = [opus_dir / "opus.dll", ffmpeg_dir / "ffmpeg.exe", ffmpeg_dir / "ffprobe.exe"]
    if voice_mode == "pipeline":
        paths.extend([
            server_dir / "models" / "SenseVoiceSmall" / "model.pt",
            server_dir / "models" / "snakers4_silero-vad" / "src" / "silero_vad" / "data" / "silero_vad.onnx",
        ])
    for path in paths:
        if not path.is_file():
            raise SetupError(f"缺少运行文件：{path}")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(opus_dir), str(ffmpeg_dir),
                                  str(server_dir / ".venv" / "Scripts"), env.get("PATH", "")])
    env["HF_HUB_OFFLINE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def probe_stream(client, model: dict) -> tuple[int, int]:
    """仅发送合成句，消费真实 content 增量；不把仅有 reasoning 的流算作成功。"""
    count = chars = 0
    with client.chat.completions.create(
        model=model["model_name"],
        messages=[{"role": "user", "content": "这是接口连通性测试，请只回复：连接成功。"}],
        stream=True,
        max_tokens=model.get("max_tokens", 256),
    ) as stream:
        for chunk in stream:
            if not chunk.choices:
                continue
            content = getattr(chunk.choices[0].delta, "content", None)
            if isinstance(content, str) and content.strip():
                count += 1
                chars += len(content)
    if not chars:
        raise SetupError("未收到非空 content 增量，小智当前提供器不能据此正常回答。")
    return count, chars


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "install-memory", "update-memory", "check-config", "check-stream", "start"])
    parser.add_argument("--server-dir", type=Path, default=DEFAULT_SERVER)
    parser.add_argument("--ffmpeg-dir", type=Path, default=DEFAULT_FFMPEG)
    parser.add_argument("--allow-insecure-http", action="store_true")
    parser.add_argument("--lan-ip", help="显式启用局域网演示，填写电脑有线 IPv4 地址")
    parser.add_argument("--device-control", action="store_true", help="显式开启本机 8766 音量验证接口")
    parser.add_argument("--voice-mode", choices=["pipeline", "doubao_realtime"], default="pipeline")
    parser.add_argument("--voice-latency-mode", choices=["realtime", "original"], default="realtime")
    parser.add_argument("--doubao-env", "--doubao-env-file", type=Path, default=DEFAULT_DOUBAO_ENV)
    parser.add_argument("--tts-backend", choices=["edge", "voxcpm2", "sanotts", "cosyvoice3"], default="edge",
                        help="核对本次实际选择的声音后端；默认 edge")
    args = parser.parse_args()
    try:
        server_dir = args.server_dir.resolve()
        if args.action == "init":
            print(f"已创建：{init_config(server_dir)}；请仅在这个私有文件填写模型地址和密钥。")
            return 0
        if args.action == "install-memory":
            print(f"已安装/确认提供器：{install_memory_provider(server_dir)}；未修改配置，未启动服务。")
            return 0
        if args.action == "update-memory":
            print(f"已升级/确认提供器：{install_memory_provider(server_dir, allow_known_update=True)}；未修改私有配置，未启动服务。")
            return 0
        # 延迟导入，只依赖小智已经安装的 PyYAML，不给记忆核心新增依赖。
        import yaml
        with (config_path(server_dir)).open(encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        if not isinstance(config, dict):
            raise SetupError("私有配置必须是 YAML 映射，不能是空文件。")
        model = validate_config(config, args.lan_ip, args.tts_backend, args.voice_mode)
        realtime = args.voice_mode == "doubao_realtime"
        if realtime:
            if args.action == "check-stream":
                raise SetupError("实时模式不使用三段式 check-stream；请先完成账号配置与独立云端验收。")
            from doubao_realtime.config import load_config, ConfigError
            try:
                load_config(args.doubao_env)  # 离线校验，不建立云连接，不输出密钥。
            except ConfigError as exc:
                raise SetupError(str(exc)) from None
        if args.device_control and args.action != "start":
            raise SetupError("--device-control 仅支持 start 操作。")
        if args.device_control:
            control_memory = config.get("Memory", {}).get("LongMemory", {})
            if ((not realtime and control_memory.get("type") != "longmemory") or
                    not re.fullmatch(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}",
                                     str(control_memory.get("allowed_device_id", "")))):
                raise SetupError("设备控制需要保留已核实的 LongMemory.allowed_device_id；当前记忆算法可以不是 LongMemory。")
            from control_compatibility import verify_control_snapshot
            try:
                verify_control_snapshot(server_dir)
            except ValueError as exc:
                raise SetupError(str(exc)) from None
        if not realtime and "LongMemory" in config.get("Memory", {}):
            installed = server_dir / "core/providers/memory/longmemory/longmemory.py"
            if not installed.is_file() or installed.read_bytes() != Path(__file__).with_name("longmemory_provider.py").read_bytes():
                raise SetupError("LongMemory 提供器未安装或版本不一致，请执行 install-memory。")
        if args.lan_ip:
            reject_ota_binaries(server_dir)
        if args.action == "check-config":
            prepare_environment(server_dir, args.ffmpeg_dir, args.voice_mode)
            print("本地配置与文件检查通过；未调用模型、未启动服务。")
            return 0
        if not realtime:
            require_transport_consent(model, args.allow_insecure_http)
        if not realtime and urlsplit(model["base_url"]).scheme == "http":
            print("警告：HTTP 会明文传输密钥和内容，只用于已确认风险的校园网合成测试。", flush=True)
        if args.action == "check-stream":
            from openai import OpenAI
            with OpenAI(api_key=model["api_key"], base_url=model["base_url"],
                        timeout=60, max_retries=0) as client:
                count, chars = probe_stream(client, model)
            print(f"流式验证通过：收到 {count} 个非空内容块，共 {chars} 字符。不是记忆问答或圆屏验收。")
            return 0
        if Path(sys.executable).resolve() != (server_dir / ".venv" / "Scripts" / "python.exe").resolve():
            raise SetupError("请使用小智 .venv 的 python.exe 启动，不使用 LongMemory 或 ESP-IDF 解释器。")
        if args.lan_ip:
            print("临时局域网演示：请限制防火墙来源，结束后撤销规则；上游令牌不是可信设备准入。", flush=True)
        memory_name = "disabled" if realtime else config['selected_module']['Memory']
        print(f"仅在 {config['server']['ip']} 启动；Voice={args.voice_mode}；Memory={memory_name}。Ctrl+C 停止。", flush=True)
        entry = (str(Path(__file__).with_name("launch_with_memory.py"))
                 if realtime or memory_name == "LongMemory" or args.device_control else "app.py")
        command = [sys.executable, entry]
        if realtime:
            command.extend(["--voice-mode", args.voice_mode, "--doubao-env", str(args.doubao_env.resolve())])
        elif entry != "app.py":
            command.extend(["--voice-latency-mode", args.voice_latency_mode])
        if args.device_control:
            command.append("--device-control")
        render_runtime_config(server_dir)
        return subprocess.call(command, cwd=server_dir,
                               env=prepare_environment(server_dir, args.ffmpeg_dir, args.voice_mode))
    except FileExistsError:
        print("已有私有配置，未覆盖。请直接检查或手动编辑。", file=sys.stderr)
    except SetupError as exc:
        # 仅回显本工具固定错误；第三方异常一律走下方脱敏路径。
        print(f"检查未通过：{exc}", file=sys.stderr)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        # 不输出 SDK 响应体、YAML 原文或 traceback，避免错误日志暴露密钥。
        status = getattr(exc, "status_code", None)
        print(f"操作失败：{type(exc).__name__}，HTTP状态={status}；未输出配置或响应正文。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
