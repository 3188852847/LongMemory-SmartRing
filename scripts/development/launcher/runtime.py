"""受管启动编排：预检后同步授权配置，不迁移数据库或探测模型。"""

from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import http.client
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time

from winjob import Job
from voice_ports import validate_voice_ports, port_arguments

ROOT = Path(__file__).resolve().parents[3]
# 项目专用运行资源随项目保存；不依赖重装前的机器绝对路径。
LOCAL_ROOT = ROOT / "local"
VOICE_ROOT = LOCAL_ROOT / "runtime/xiaozhi-esp32-server/main/xiaozhi-server"
VOXCPM_PORT = 18768
SANOTTS_PORT = 18769
COSYVOICE_PORT = 18770
DEFAULT_SANOTTS_SOURCE = LOCAL_ROOT / "runtime/sanoTTS"
DEFAULT_COSYVOICE_SOURCE = LOCAL_ROOT / "runtime/CosyVoice"
DEFAULT_VOXCPM_PYTHON = LOCAL_ROOT / "runtime/voxcpm2-venv/Scripts/python.exe"
DEFAULT_COSYVOICE_MODEL = DEFAULT_COSYVOICE_SOURCE / "pretrained_models/Fun-CosyVoice3-0.5B"
EXPECTED_SANOTTS_FINGERPRINT = "e7adac23b8ae2aefa1623eaa24f6f8049ddfd97e30efd5a377e0f239e6cd7605"
WALLPAPER_DELIVERY_PORT = 8768
DEFAULT_CHAT_PATH = "/chat-react"
CONSOLE_PATHS = {"overview": "/overview", "chat": DEFAULT_CHAT_PATH, "device": "/device", "memories": "/memories", "settings": "/settings"}
DEFAULT_BGE_MODEL = LOCAL_ROOT / "runtime/models/bge-small-zh-v1.5/7999e1d3359715c523056ef9478215996d62a620"
DEFAULT_FFMPEG_DIR = LOCAL_ROOT / "tools/ffmpeg/bin"
LAUNCHER_STATUS_NAME = "launcher-status.json"


def doubao_config_module():
    """复用项目语音适配层的纯配置模块；不加载模型或访问网络。"""
    directory = str(Path(__file__).resolve().parents[1] / "xiaozhi")
    sys.path.insert(0, directory)
    try:
        from doubao_realtime import config
        return config
    finally:
        sys.path.remove(directory)


def validate_doubao_config(path):
    """启动前只核对本地配置格式；有效凭据与服务权限留待真实接入验证。"""
    try:
        doubao_config_module().load_config(path)
    except (OSError, ValueError):
        raise ValueError(
            "豆包实时语音尚未完成配置。请在“圆屏与声音”填写实时语音凭据；"
            "普通豆包文字模型的密钥不能替代此配置。未启动服务。"
        ) from None


def console_url(port: int, page: str = "chat") -> str:
    """只允许打开控制台内的固定页面，不能从首选项注入任意网址。"""
    if page not in CONSOLE_PATHS:
        raise ValueError("未知控制台起始页。")
    return f"http://127.0.0.1:{port}{CONSOLE_PATHS[page]}"


@dataclass(frozen=True)
class Options:
    root: Path = ROOT
    database: Path = ROOT / "data/databases/xiaozhi-demo-v1.db"
    port: int = 8767
    role: str = "elysia_v1"
    memory_extraction: str = "rules"
    memory_retrieval: str = "keyword"
    allow_memory_delete: bool = False
    enable_memory_consolidation: bool = False
    enable_l1_sufficiency_shadow: bool = False
    enable_l2_sufficiency_shadow: bool = False
    embedding_model_dir: Path = DEFAULT_BGE_MODEL
    voice: bool = False
    voice_mode: str = "pipeline"
    voice_latency_mode: str = "realtime"
    doubao_env: Path | None = None
    tts_backend: str = "edge"
    sanotts_source_root: Path = DEFAULT_SANOTTS_SOURCE
    vad_profile: str = "normal"
    voice_root: Path = VOICE_ROOT
    lan_ip: str = ""
    voice_ws_port: int = 8000
    voice_http_port: int = 8003
    consent: bool = False
    model_profile: str = "campus"
    voice_model_profile: str = "campus"
    memory_backend: str = "longmemory"
    ffmpeg_dir: Path | None = None


class AddressBindingError(ValueError):
    """只公开受控的绑定原因；不把系统异常、路径或配置正文送到页面。"""

    def __init__(self, host, port, error_code):
        address = str(ipaddress.ip_address(host))
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError('端口范围无效。')
        if error_code in {10049, errno.EADDRNOTAVAIL}:
            self.code = 'lan_address_unavailable'
            reason = '此 IP 已不属于本机，请在启动设置更新电脑局域网 IP，并核对圆屏保存的 OTA/服务器地址。'
        elif error_code in {10048, errno.EADDRINUSE}:
            self.code = 'port_in_use'
            reason = '端口已被其他服务占用，请先核对进程归属，再决定如何处理该服务。'
        elif error_code in {10013, errno.EACCES}:
            self.code = 'bind_denied'
            reason = '系统拒绝绑定，可能是独占占用或端口保留；请核对占用和保留范围，不要关闭防火墙。'
        else:
            self.code = 'bind_failed'
            reason = '绑定检查失败，请核对本机地址与端口。'
        super().__init__(f'地址 {address}:{port} 不可绑定：{reason} 未关闭其他程序。')


def require_free(host, port):
    """仅预检；真正启动仍可能遇到竞争，不把检查通过当作服务就绪。"""
    with socket.socket() as sock:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((host, port))
        except OSError as error:
            code = getattr(error, 'winerror', None) or error.errno
            raise AddressBindingError(host, port, code) from None


def require_no_listener(host, port):
    """VoxCPM2 可越过旧健康连接的 TIME_WAIT，但不覆盖真实监听者。"""
    with socket.socket() as sock:
        sock.settimeout(0.25)
        if sock.connect_ex((host, port)) == 0:
            raise AddressBindingError(host, port, errno.EADDRINUSE)


def build_commands(options, uv=None):
    """返回参数列表，绝不拼接 shell 命令；只引用现有环境和配置。"""
    validate_voice_ports(options.voice_ws_port, options.voice_http_port, console_port=options.port)
    if options.voice_mode == 'doubao_realtime' and (options.voice_ws_port, options.voice_http_port) != (8000, 8003):
        raise ValueError('独立圆屏端口当前支持本地语音链路；豆包备用请使用原默认端口。')
    if options.model_profile not in {"campus", "official"}:
        raise ValueError("未知模型配置档。")
    if options.voice_model_profile not in {"campus", "official"}:
        raise ValueError("未知圆屏模型配置档。")
    if options.voice_mode not in {"pipeline", "doubao_realtime"}:
        raise ValueError("未知圆屏语音模式。")
    if options.voice_latency_mode not in {"realtime", "original"}:
        raise ValueError("未知圆屏响应策略。")
    if options.memory_backend not in {"longmemory", "hy_memory", "xiaozhi_local", "none"}:
        raise ValueError("未知圆屏记忆后端。")
    if (options.model_profile == "campus" or
            (options.voice and options.voice_mode == "pipeline"
             and options.voice_model_profile == "campus")) and not options.consent:
        raise ValueError("请先确认聊天写入及当前 HTTP 传输风险。")
    if not 1024 <= options.port <= 65535 or options.port in {options.voice_ws_port, options.voice_http_port, 8766, WALLPAPER_DELIVERY_PORT}:
        raise ValueError("控制台端口需在 1024–65535 且不占用小智端口。")
    if options.role not in {"plain_v1", "elysia_v1"}:
        raise ValueError("未知助手角色。")
    if options.memory_extraction not in {"rules", "llm"}:
        raise ValueError("未知记忆提取策略。")
    if options.memory_retrieval not in {"keyword", "hybrid"}:
        raise ValueError("未知记忆召回策略。")
    if options.tts_backend not in {"edge", "voxcpm2", "sanotts", "cosyvoice3"}:
        raise ValueError("未知语音后端。")
    if options.vad_profile not in {"normal", "noisy", "close_talk"}:
        raise ValueError("未知拾音环境档位。")
    root = options.root.resolve()
    hy_selected = options.memory_backend == "hy_memory"
    if hy_selected:
        if options.voice and options.voice_mode != "pipeline":
            raise ValueError("Hy 圆屏接入仅支持原语音主链路。")
        from longmemory.infrastructure.config.hy_deployment import load_hy_deployment
        deployment = load_hy_deployment(root)
        if not deployment.source_path.is_file() or not (deployment.state_directory / "hy-state.json").is_file():
            raise ValueError("Hy 新库尚未由受控切换初始化；普通启动不会建库。")
    if not options.database.is_file():
        raise ValueError("请选择已有日常数据库；启动器不会创建或迁移数据库。")
    env_file = {"campus": "local/config/.env", "official": "local/config/.env.deepseek.local"}[options.model_profile]
    if not (root / env_file).is_file() or not (root / ".venv/Scripts/python.exe").is_file():
        raise ValueError(f"缺少项目 {env_file} 或虚拟环境，请先在控制台配置该模型档。")
    uv = uv or shutil.which("uv")
    if not uv:
        raise ValueError("未找到 uv，请检查已有安装的 PATH。启动器不自动安装依赖。")
    # 当前 uv 的 env-file 参数会拆分反斜杠/空格路径。子进程 cwd 已明确
    # 固定为项目根目录，使用相对 local/config/.env 同时规避两种路径解析问题。
    console = [str(uv), "run", "--offline", "--no-sync", "--env-file", env_file,
               "python", "-m", "longmemory.entrypoints.api", "--port", str(options.port),
               "--database", str(options.database.resolve()), "--enable-chat",
               "--chat-provider", "openai_compatible", "--assistant-role", options.role,
               "--memory-extraction", "rules" if hy_selected else options.memory_extraction,
               "--memory-retrieval", "keyword" if hy_selected else options.memory_retrieval,
               "--tts-backend", options.tts_backend,
               "--xiaozhi-server", str(options.voice_root.resolve()),
               "--launcher-status-file", str(root / "data/control" / LAUNCHER_STATUS_NAME),
               "--memory-audit-log", str(root / "data/logs/xiaozhi-demo-v1.jsonl")]
    console.extend(["--model-profile", options.model_profile])
    console.extend(["--memory-backend", options.memory_backend])
    if not options.voice or hy_selected:
        # 文字模式保留圆屏联系设置，但不启动无法投递的圆屏定时任务。
        console.append("--disable-proactive-schedule")
    # 媒体工具是用户已安装的本地依赖。启动器只发现并传递路径，
    # 不下载、不改 PATH；找不到时其他控制台功能仍可启动。
    ffmpeg_dir = options.ffmpeg_dir or DEFAULT_FFMPEG_DIR
    if (ffmpeg_dir / "ffmpeg.exe").is_file() and (ffmpeg_dir / "ffprobe.exe").is_file():
        console.extend(["--ffmpeg-dir", str(ffmpeg_dir.resolve())])
    # 人工纠正每次都需要在网页中核对旧内容并再次确认；日常入口默认开放这一
    # 可追溯写入能力。不可恢复的硬删除仍保持关闭。
    console.append("--allow-memory-correction")
    console.append("--allow-scenario-management")
    # L3 只能由本机页面显式创建候选并复核；尚不参与回答。
    console.append("--allow-persona-management")
    if options.enable_memory_consolidation and not hy_selected:
        console.append("--enable-memory-consolidation")
    if options.enable_l1_sufficiency_shadow and not hy_selected:
        # 只观测 L1 候选是否足以回答；默认关闭且不修改正式上下文。
        console.append("--enable-l1-sufficiency-shadow")
    if options.enable_l2_sufficiency_shadow and not hy_selected:
        # 影子审计只旁路记录 L2 证据是否足够，不改变本轮注入和回答。
        # 默认关闭，因为每个存在 L2 候选的用户问题会增加一次模型请求。
        console.append("--enable-l2-sufficiency-shadow")
    if options.allow_memory_delete:
        # 这里只授予服务端能力；浏览器仍需打开具体 L1 并二次确认。
        # 当前删除保留 L0 原话，因此不能显示成“彻底遗忘”。
        console.append("--allow-memory-delete")
    if options.memory_retrieval == "hybrid" and not hy_selected:
        if not options.embedding_model_dir.is_dir():
            raise ValueError("混合召回需要已有的本地 BGE 快照目录。")
        console.extend(["--embedding-model-dir", str(options.embedding_model_dir.resolve())])
    # 实验启动默认关闭；L1 删除只能由面板显式勾选，不能隐式开启。
    commands = [("console", console, root)]
    if options.voice:
        try:
            ip = ipaddress.IPv4Address(options.lan_ip)
        except ValueError:
            raise ValueError("圆屏模式需要有效的电脑局域网 IPv4。") from None
        if not any(ip in ipaddress.ip_network(net) for net in
                   ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
            raise ValueError("只允许 RFC1918 局域网地址，不允许公网或所有网卡地址。")
        # 专用监听只提供短时、单次、哈希绑定的 GIF；控制台本身仍只监听回环。
        console.extend(["--wallpaper-lan-ip", str(ip)])
        python = options.voice_root / ".venv/Scripts/python.exe"
        if not python.is_file():
            raise ValueError("未找到小智自己的 Python 环境。")
        if options.voice_mode == "doubao_realtime":
            validate_doubao_config(options.doubao_env or root / "local/config/.env.doubao.local")
        elif options.tts_backend == "voxcpm2":
            # 独立环境与模型集中存放；服务代码仍来自主仓库，二者不再靠旧目录联接绑定。
            voxcpm_python = DEFAULT_VOXCPM_PYTHON
            service = root / "scripts/development/voxcpm/service.py"
            if not voxcpm_python.is_file() or not service.is_file():
                raise ValueError("VoxCPM2 独立环境或服务脚本不完整。")
            commands.append(("voxcpm2", [str(voxcpm_python), str(service),
                                           "--host", "127.0.0.1", "--port", str(VOXCPM_PORT)],
                             service.parent))
        elif options.tts_backend == "sanotts":
            service = root / "scripts/development/sanotts/service.mjs"
            source = options.sanotts_source_root.resolve()
            required = [
                service,
                source / "web/snt_voice.js",
                source / "web/snt_voice.wasm",
                source / "web/voices/chinese-xiaoya/meta.json",
            ]
            if not all(path.is_file() for path in required):
                raise ValueError("sanoTTS 源码或中文模型不完整；请核对外部目录。")
            node = shutil.which("node")
            if not node:
                raise ValueError("未找到已有 Node.js；启动器不会自动安装依赖。")
            commands.append(("sanotts", [node, str(service), "--host", "127.0.0.1",
                                          "--port", str(SANOTTS_PORT), "--source", str(source),
                                          "--expected-fingerprint", EXPECTED_SANOTTS_FINGERPRINT],
                             service.parent))
        elif options.tts_backend == "cosyvoice3":
            cosyvoice_python = DEFAULT_COSYVOICE_SOURCE / ".venv/Scripts/python.exe"
            service = root / "scripts/development/cosyvoice/service.py"
            required = [cosyvoice_python, service, DEFAULT_COSYVOICE_MODEL / "cosyvoice3.yaml"]
            if not all(path.is_file() for path in required):
                raise ValueError("CosyVoice 独立环境、适配服务或模型快照不完整。")
            commands.append(("cosyvoice3", [str(cosyvoice_python), str(service),
                                              "--host", "127.0.0.1",
                                              "--port", str(COSYVOICE_PORT),
                                              "--source-root", str(DEFAULT_COSYVOICE_SOURCE),
                                              "--model-dir", str(DEFAULT_COSYVOICE_MODEL)],
                             service.parent))
        voice_command = [str(python), str(Path(__file__).with_name("voice.py")),
                                  str(root), str(options.voice_root.resolve()), str(options.database.resolve()),
                                  str(ip), options.tts_backend, options.memory_backend]
        if options.voice_mode == "doubao_realtime":
            voice_command.extend(["--voice-mode", "doubao_realtime", "--doubao-env", str(
                (options.doubao_env or root / "local/config/.env.doubao.local").resolve()
            )])
        else:
            voice_command.extend(["--voice-latency-mode", options.voice_latency_mode])
        voice_command.extend(port_arguments(options.voice_ws_port, options.voice_http_port))
        commands.append(("voice", voice_command, options.voice_root.resolve()))
    return commands


class Singleton:
    """持有本机单实例端口；控制桥复用这个监听 socket，不增加端口。"""
    def __init__(self, port=18767):
        self.socket = socket.socket()
        try:
            if os.name == "nt":
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.socket.bind(("127.0.0.1", port))
            self.socket.listen(1)
        except OSError:
            self.socket.close()
            raise ValueError("启动面板已打开，或本机 18767 被占用。请使用原面板；未关闭任何程序。") from None

    def close(self):
        self.socket.close()


class OwnedService:
    def __init__(self, command, cwd, env):
        self.job = Job()
        self.process = None
        try:
            # 门控 worker 加入 Job 后才创建真实服务，uv/小智的后代同属任务树。
            self.process = subprocess.Popen(
                [sys.executable.replace("pythonw.exe", "python.exe"), str(Path(__file__).with_name("worker.py"))],
                cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self.job.assign(self.process)
            self.process.stdin.write((json.dumps(command) + "\n").encode("utf-8"))
            self.process.stdin.close()
        except Exception:
            if self.process is not None:
                # 只有门控且尚未运行服务的自己子进程可以直接停止。
                self.process.kill()
                self.process.wait(timeout=5)
            self.job.close()
            raise

    def stop(self):
        self.job.close()
        self.process.wait(timeout=5)


class Manager:
    def __init__(self):
        self.services = {}
        self.instance = ""
        self.options = None
        self.status_path = None
        self.runtime_token = None
        self._binding_next_check = 0
        self._binding_ready = False

    def _service_state(self, name, *, ready=False):
        """只报告启动器拥有的进程事实，不把“进程活着”冒充业务就绪。"""
        service = self.services.get(name)
        if service is None:
            return "disabled"
        process = getattr(service, "process", None)
        if process is None:
            # 测试替身或未来代理可能不暴露句柄；旁路诊断不得阻断启动。
            return "running"
        code = process.poll()
        if code is not None:
            return "exited"
        return "ready" if ready else "running"

    def publish_status(self, phase, *, console_ready=False, voice_ready=False,
                       tts_ready=False):
        """原子发布不含正文/密钥的本机诊断快照；失败不能影响主服务。"""
        if self.status_path is None or not self.instance:
            return
        snapshot = {
            "schema_version": 5,
            "launcher_instance": self.instance,
            "launcher_pid": os.getpid(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "services": {
                "console": self._service_state("console", ready=console_ready),
                "voice": self._service_state("voice", ready=voice_ready),
                "voxcpm2": self._service_state(
                    "voxcpm2", ready=tts_ready and self.options is not None
                    and self.options.tts_backend == "voxcpm2"
                ),
                "sanotts": self._service_state(
                    "sanotts", ready=tts_ready and self.options is not None
                    and self.options.tts_backend == "sanotts"
                ),
                "cosyvoice3": self._service_state(
                    "cosyvoice3", ready=tts_ready and self.options is not None
                    and self.options.tts_backend == "cosyvoice3"
                ),
            },
            # 只记录启动时的非敏感选项，不记录地址、密钥、模型或对话。
            "startup": {
                "voice_enabled": bool(self.options and self.options.voice),
                "voice_mode": self.options.voice_mode if self.options is not None else "pipeline",
                "vad_profile": (
                    self.options.vad_profile
                    if self.options is not None and self.options.voice
                    and self.options.voice_mode == "pipeline" else None
                ),
                "tts_backend": (
                    self.options.tts_backend
                    if self.options is not None and self.options.voice
                    and self.options.voice_mode == "pipeline" else None
                ),
            },
        }
        temporary = self.status_path.with_suffix(".tmp")
        try:
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.status_path)
        except OSError:
            # 诊断是旁路能力；磁盘/杀毒软件短暂占用不能中断聊天或语音。
            pass

    def start(self, options):
        if self.services:
            raise ValueError("已有受管服务，请先停止再更换模式。")
        commands = build_commands(options)
        require_free("127.0.0.1", options.port)
        if options.voice:
            for host, port in [(options.lan_ip, options.voice_ws_port), (options.lan_ip, options.voice_http_port),
                               (options.lan_ip, WALLPAPER_DELIVERY_PORT),
                               ("127.0.0.1", 8766)]:
                require_free(host, port)
            if options.voice_mode == "doubao_realtime":
                pass  # 云端模式没有本地 TTS 服务，不探测或占用这些端口。
            elif options.tts_backend == "voxcpm2":
                require_no_listener("127.0.0.1", VOXCPM_PORT)
            elif options.tts_backend == "sanotts":
                require_no_listener("127.0.0.1", SANOTTS_PORT)
            elif options.tts_backend == "cosyvoice3":
                require_no_listener("127.0.0.1", COSYVOICE_PORT)
            # 端口均空闲后才检查并同步小智私有配置，避免给外部正在运行的
            # 语音服务换地址、声音、模型、记忆后端或拾音档位。先完成只读检查，
            # 再逐项备份写入；格式错误不会造成“改了一半才发现无法检查”。
            from network import config_action as network_config_action
            network_ports = ({} if (options.voice_ws_port, options.voice_http_port) == (8000, 8003)
                             else dict(ws_port=options.voice_ws_port, http_port=options.voice_http_port))
            network_checked = network_config_action(options.voice_root, options.lan_ip, **network_ports)
            network_apply = {**network_ports, 'expected_digest': network_checked['digest']}
            if options.voice_mode == "doubao_realtime":
                if network_checked["changed"]:
                    network_config_action(options.voice_root, options.lan_ip, apply=True, **network_apply)
            else:
                from tts import config_action as tts_config_action
                from model import config_action as model_config_action
                from memory import config_action as memory_config_action
                from vad import config_action as vad_config_action
                tts_checked = tts_config_action(
                    options.voice_root, options.root, options.tts_backend
                )
                model_checked = {"config_matches": True} if options.memory_backend == "hy_memory" else model_config_action(
                    options.voice_root, options.root, options.voice_model_profile
                )
                memory_checked = memory_config_action(
                    options.voice_root, options.root, options.memory_backend
                )
                vad_checked = vad_config_action(
                    options.voice_root, options.root, options.vad_profile
                )
                config_changed = False
                if network_checked["changed"]:
                    network_config_action(options.voice_root, options.lan_ip, apply=True, **network_apply)
                    config_changed = True
                # 五个配置域共用同一个私有 YAML。上一个域一旦写入，后面预检时
                # 取得的摘要就已经陈旧；写入前重新检查既保留“全部先预检”的安全
                # 边界，也避免启动器被自己的前序修改触发并发保护。
                if config_changed:
                    tts_checked = tts_config_action(
                        options.voice_root, options.root, options.tts_backend
                    )
                if not tts_checked["config_matches"]:
                    tts_config_action(
                        options.voice_root, options.root, options.tts_backend,
                        apply=True, expected_digest=tts_checked["digest"],
                    )
                    config_changed = True
                if config_changed and options.memory_backend != "hy_memory":
                    model_checked = model_config_action(
                        options.voice_root, options.root, options.voice_model_profile
                    )
                if not model_checked["config_matches"]:
                    model_config_action(options.voice_root, options.root,
                                        options.voice_model_profile, apply=True,
                                        expected_digest=model_checked["digest"])
                    config_changed = True
                # 记忆后端与模型/TTS 一样只在端口空闲后同步。切换只改变提供器
                # 指针及缺失的内置配置，不读取、迁移或删除任何后端数据。
                if config_changed:
                    memory_checked = memory_config_action(
                        options.voice_root, options.root, options.memory_backend
                    )
                if not memory_checked["config_matches"]:
                    memory_config_action(
                        options.voice_root, options.root, options.memory_backend,
                        apply=True, expected_digest=memory_checked["digest"],
                    )
                    config_changed = True
                if config_changed:
                    vad_checked = vad_config_action(
                        options.voice_root, options.root, options.vad_profile
                    )
                if not vad_checked["config_matches"]:
                    vad_config_action(
                        options.voice_root, options.root, options.vad_profile,
                        apply=True, expected_digest=vad_checked["digest"],
                    )
        self.options = options
        self._binding_next_check = 0
        self._binding_ready = False
        self.instance = secrets.token_hex(24)
        self.status_path = options.root.resolve() / "data/control" / LAUNCHER_STATUS_NAME
        self.publish_status("starting")
        runtime_token = secrets.token_hex(32)
        self.runtime_token = runtime_token
        env = os.environ.copy()
        env.update(
            PYTHONUTF8="1",
            LONGMEMORY_LAUNCHER_INSTANCE=self.instance,
            LONGMEMORY_MEMORY_TRANSPORT="runtime",
            LONGMEMORY_RUNTIME_URL=(
                f"http://127.0.0.1:{options.port}/api/internal/memory/prepare"
            ),
            LONGMEMORY_RUNTIME_TOKEN=runtime_token,
            LONGMEMORY_MEMORY_BACKEND=options.memory_backend,
        )
        try:
            for name, command, cwd in commands:
                child_env = env
                if name == "voice" and options.voice_mode == "doubao_realtime":
                    # 云端备用入口不领取个人记忆内部接口凭据。
                    child_env = {key: value for key, value in env.items() if key not in {
                        "LONGMEMORY_MEMORY_TRANSPORT", "LONGMEMORY_RUNTIME_URL",
                        "LONGMEMORY_RUNTIME_TOKEN",
                    }}
                self.services[name] = OwnedService(command, cwd, child_env)
                self.publish_status("starting")
        except Exception:
            self.stop()
            raise

    def ready(self):
        if not self.services or self.services["console"].process.poll() is not None:
            return False
        conn = http.client.HTTPConnection("127.0.0.1", self.options.port, timeout=0.25)
        try:
            conn.request("GET", "/chat")
            response = conn.getresponse()
            response.read(1024 * 1024)
            # 实例标识不是认证令牌，仅避免把占用端口的别的服务误判为本次实例。
            console_ready = (
                response.status == 200
                and response.getheader("X-LongMemory-Instance") == self.instance
            )
        except (OSError, http.client.HTTPException):
            return False
        finally:
            conn.close()
        if not console_ready:
            return False
        return not self.options.voice or self.voice_bridge_ready()

    def _maintenance(self, *, voice, draining):
        if self.options is None or not self.instance:
            return False
        if voice:
            try:
                token = (self.options.root / 'data/control/device-control.token').read_text(encoding='ascii').strip()
                if len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
                    return False
            except OSError:
                return False
            port, path = 8766, '/api/network-maintenance'
        else:
            token = self.runtime_token
            port, path = self.options.port, '/api/internal/network-maintenance'
        if not token:
            return False
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=0.5)
        try:
            conn.request('POST', path, json.dumps({'instance': self.instance, 'draining': draining}),
                         headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
                                  'Host': f'127.0.0.1:{port}'})
            response = conn.getresponse()
            body = json.loads(response.read(4096))
            return (response.status == 200 and isinstance(body, dict)
                    and body.get('instance') == self.instance and body.get('draining') is draining)
        except (OSError, http.client.HTTPException, ValueError):
            return False
        finally:
            conn.close()

    def acquire_network_restart(self):
        """仅本面板Job存活、设备已断开、网页和后台均空闲才加闸；失败不停止。"""
        if (self.options is None or not self.options.voice or self.options.voice_mode != 'pipeline'
                or not self.services or not all(isinstance(service, OwnedService)
                    and getattr(service.job, 'handle', None) and service.process.poll() is None
                    for service in self.services.values())):
            return False
        if self._maintenance(voice=True, draining=True) and self._maintenance(voice=False, draining=True):
            return True
        self.release_network_restart()
        return False

    def sync_network_only(self, options):
        """停止状态下同步本项目网络；外部监听者存在时不写任何配置。"""
        if self.services:
            raise ValueError('同步前必须停止本面板服务。')
        validate_voice_ports(options.voice_ws_port, options.voice_http_port, console_port=options.port)
        for host, port in [('127.0.0.1', options.port), (options.lan_ip, options.voice_ws_port),
                           (options.lan_ip, options.voice_http_port), (options.lan_ip, WALLPAPER_DELIVERY_PORT),
                           ('127.0.0.1', 8766)]:
            require_free(host, port)
        from network import config_action
        ports = dict(ws_port=options.voice_ws_port, http_port=options.voice_http_port)
        checked = config_action(options.voice_root, options.lan_ip, **ports)
        config_action(options.voice_root, options.lan_ip, apply=True, expected_digest=checked['digest'], **ports)
        # 无运行服务领取该副本；正式启动再生成当次专属Hy网关投影，不复用旧网关。
        result = subprocess.run([str(options.voice_root / '.venv/Scripts/python.exe'),
                                 str(Path(__file__).parents[1] / 'xiaozhi/config_paths.py'),
                                 '--server-dir', str(options.voice_root), '--render'],
                                capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise ValueError('网络消费副本未确认更新；保留备份，请核对配置。')

    def release_network_restart(self):
        self._maintenance(voice=False, draining=False)
        self._maintenance(voice=True, draining=False)

    def voice_bridge_ready(self):
        """验权读取本机桥状态；只证明语音控制面已监听，不要求圆屏在线。"""
        if (self.options is None or not self.options.voice
                or "voice" not in self.services
                or self.services["voice"].process.poll() is not None):
            return False
        try:
            token = (self.options.root.resolve() / "data/control/device-control.token").read_text(
                encoding="ascii"
            ).strip()
            if len(token) != 64 or any(char not in "0123456789abcdef" for char in token):
                return False
        except OSError:
            return False
        conn = http.client.HTTPConnection("127.0.0.1", 8766, timeout=0.25)
        try:
            conn.request("GET", "/api/device", headers={
                "Authorization": "Bearer " + token,
                "Host": "127.0.0.1:8766",
            })
            response = conn.getresponse()
            body = json.loads(response.read(32_768))
            valid = (
                response.status == 200
                and isinstance(body, dict)
                and type(body.get("connection_count")) is int
                and type(body.get("ready")) is bool
            )
            if not valid:
                return False
            # 控制面就绪之外，还核对本次选中的两个LAN监听；不向模型或圆屏发命令。
            now = time.monotonic()
            if now < self._binding_next_check:
                return self._binding_ready
            self._binding_next_check, self._binding_ready = now + 5, False
            for port in (self.options.voice_ws_port, self.options.voice_http_port):
                with socket.create_connection((self.options.lan_ip, port), timeout=0.25):
                    pass
            self._binding_ready = True
            return True
        except (OSError, http.client.HTTPException, json.JSONDecodeError):
            return False
        finally:
            conn.close()

    def local_tts_ready(self):
        if self.options is not None and self.options.voice_mode != "pipeline":
            return False
        backend = self.options.tts_backend if self.options else ""
        port = {"voxcpm2": VOXCPM_PORT, "sanotts": SANOTTS_PORT,
                "cosyvoice3": COSYVOICE_PORT}.get(backend)
        if port is None or backend not in self.services or self.services[backend].process.poll() is not None:
            return False
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.25)
        try:
            conn.request("GET", "/health")
            response = conn.getresponse()
            body = json.loads(response.read(4096))
            return response.status == 200 and body.get("ready") is True and body.get("provider") == backend
        except (OSError, http.client.HTTPException, json.JSONDecodeError):
            return False
        finally:
            conn.close()

    def voxcpm_ready(self):
        """保留旧调用方名称；实际按当前本地 TTS 后端检查。"""
        return self.local_tts_ready()

    def stop(self):
        self.publish_status("stopping")
        errors = []
        for service in reversed(list(self.services.values())):
            try:
                service.stop()
            except Exception:
                errors.append(service)
        if errors:
            raise RuntimeError("停止未完全确认，请勿重复启动。")
        self.services.clear()
        self.publish_status("stopped")
