"""最小启动编排：不修改配置、不迁移数据库、不探测模型。"""

from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys

from winjob import Job

ROOT = Path(__file__).resolve().parents[3]
VOICE_ROOT = Path(r"D:\ESP32-Workspace\xiaozhi-esp32-server\main\xiaozhi-server")
VOXCPM_PORT = 18768
DEFAULT_CHAT_PATH = "/chat-react"
CONSOLE_PATHS = {"chat": DEFAULT_CHAT_PATH, "device": "/device", "memories": "/memories", "settings": "/settings"}
DEFAULT_BGE_MODEL = ROOT / "data/models/bge-small-zh-v1.5/7999e1d3359715c523056ef9478215996d62a620"


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
    embedding_model_dir: Path = DEFAULT_BGE_MODEL
    voice: bool = False
    tts_backend: str = "edge"
    voice_root: Path = VOICE_ROOT
    lan_ip: str = ""
    consent: bool = False
    model_profile: str = "campus"
    voice_model_profile: str = "campus"
    memory_backend: str = "longmemory"


def require_free(host, port):
    """仅预检；真正启动仍可能遇到竞争，不把检查通过当作服务就绪。"""
    with socket.socket() as sock:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((host, port))
        except OSError as error:
            code = getattr(error, 'winerror', None) or error.errno
            reason = {10049: '此 IP 不属于本机，请刷新局域网地址并同步小智配置。',
                      10048: '端口已被占用，请停止原终端中的旧服务后重试。',
                      10013: '系统拒绝绑定，可能是独占占用或端口保留；不要关闭防火墙。'}.get(code, f'系统错误 {code}，请检查地址和端口。')
            raise ValueError(f"地址 {host}:{port} 不可绑定：{reason} 未关闭其他程序。") from None


def require_no_listener(host, port):
    """VoxCPM2 可越过旧健康连接的 TIME_WAIT，但不覆盖真实监听者。"""
    with socket.socket() as sock:
        sock.settimeout(0.25)
        if sock.connect_ex((host, port)) == 0:
            raise ValueError(f"地址 {host}:{port} 已有服务监听；未关闭该程序。")


def build_commands(options, uv=None):
    """返回参数列表，绝不拼接 shell 命令；只引用现有环境和配置。"""
    if options.model_profile not in {"campus", "official"}:
        raise ValueError("未知模型配置档。")
    if options.voice_model_profile not in {"campus", "official"}:
        raise ValueError("未知圆屏模型配置档。")
    if options.memory_backend not in {"longmemory", "xiaozhi_local", "none"}:
        raise ValueError("未知圆屏记忆后端。")
    if (options.model_profile == "campus" or
            (options.voice and options.voice_model_profile == "campus")) and not options.consent:
        raise ValueError("请先确认聊天写入及当前 HTTP 传输风险。")
    if not 1024 <= options.port <= 65535 or options.port in {8000, 8003, 8766}:
        raise ValueError("控制台端口需在 1024–65535 且不占用小智端口。")
    if options.role not in {"plain_v1", "elysia_v1"}:
        raise ValueError("未知助手角色。")
    if options.memory_extraction not in {"rules", "llm"}:
        raise ValueError("未知记忆提取策略。")
    if options.memory_retrieval not in {"keyword", "hybrid"}:
        raise ValueError("未知记忆召回策略。")
    if options.tts_backend not in {"edge", "voxcpm2"}:
        raise ValueError("未知语音后端。")
    root = options.root.resolve()
    if not options.database.is_file():
        raise ValueError("请选择已有日常数据库；启动器不会创建或迁移数据库。")
    env_file = {"campus": ".env", "official": ".env.deepseek.local"}[options.model_profile]
    if not (root / env_file).is_file() or not (root / ".venv/Scripts/python.exe").is_file():
        raise ValueError(f"缺少项目 {env_file} 或虚拟环境，请先在控制台配置该模型档。")
    uv = uv or shutil.which("uv")
    if not uv:
        raise ValueError("未找到 uv，请检查已有安装的 PATH。启动器不自动安装依赖。")
    # 当前 uv 的 env-file 参数会拆分反斜杠/空格路径。子进程 cwd 已明确
    # 固定为项目根目录，使用相对 .env 同时规避两种路径解析问题。
    console = [str(uv), "run", "--offline", "--no-sync", "--env-file", env_file,
               "python", "-m", "longmemory.entrypoints.api", "--port", str(options.port),
               "--database", str(options.database.resolve()), "--enable-chat",
               "--chat-provider", "openai_compatible", "--assistant-role", options.role,
               "--memory-extraction", options.memory_extraction,
               "--memory-retrieval", options.memory_retrieval,
               "--xiaozhi-server", str(options.voice_root.resolve()),
               "--memory-audit-log", str(root / "data/logs/xiaozhi-demo-v1.jsonl")]
    console.extend(["--model-profile", options.model_profile])
    console.extend(["--memory-backend", options.memory_backend])
    # 人工纠正每次都需要在网页中核对旧内容并再次确认；日常入口默认开放这一
    # 可追溯写入能力。不可恢复的硬删除仍保持关闭。
    console.append("--allow-memory-correction")
    console.append("--allow-scenario-management")
    # L3 只能由本机页面显式创建候选并复核；尚不参与回答。
    console.append("--allow-persona-management")
    if options.enable_memory_consolidation:
        console.append("--enable-memory-consolidation")
    if options.allow_memory_delete:
        # 这里只授予服务端能力；浏览器仍需打开具体 L1 并二次确认。
        # 当前删除保留 L0 原话，因此不能显示成“彻底遗忘”。
        console.append("--allow-memory-delete")
    if options.memory_retrieval == "hybrid":
        if not options.embedding_model_dir.is_dir():
            raise ValueError("混合召回需要已有的本地 BGE 快照目录。")
        console.extend(["--embedding-model-dir", str(options.embedding_model_dir.resolve())])
    # 实验启动默认关闭；L1 删除只能由面板显式勾选，不能隐式开启。
    commands = [("console", console, root)]
    if options.voice:
        import ipaddress
        try:
            ip = ipaddress.IPv4Address(options.lan_ip)
        except ValueError:
            raise ValueError("圆屏模式需要有效的电脑局域网 IPv4。") from None
        if not any(ip in ipaddress.ip_network(net) for net in
                   ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
            raise ValueError("只允许 RFC1918 局域网地址，不允许公网或所有网卡地址。")
        python = options.voice_root / ".venv/Scripts/python.exe"
        if not python.is_file():
            raise ValueError("未找到小智自己的 Python 环境。")
        if options.tts_backend == "voxcpm2":
            voxcpm_python = root / "scripts/development/voxcpm/.venv/Scripts/python.exe"
            service = root / "scripts/development/voxcpm/service.py"
            if not voxcpm_python.is_file() or not service.is_file():
                raise ValueError("VoxCPM2 独立环境或服务脚本不完整。")
            commands.append(("voxcpm2", [str(voxcpm_python), str(service),
                                           "--host", "127.0.0.1", "--port", str(VOXCPM_PORT)],
                             service.parent))
        commands.append(("voice", [str(python), str(Path(__file__).with_name("voice.py")),
                                  str(root), str(options.voice_root.resolve()), str(options.database.resolve()),
                                  str(ip), options.tts_backend, options.memory_backend], options.voice_root.resolve()))
    return commands


class Singleton:
    """无 PID 文件的本机锁；进程退出自动释放，不存在陈旧锁文件。"""
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

    def start(self, options):
        if self.services:
            raise ValueError("已有受管服务，请先停止再更换模式。")
        commands = build_commands(options)
        require_free("127.0.0.1", options.port)
        if options.voice:
            for host, port in [(options.lan_ip, 8000), (options.lan_ip, 8003), ("127.0.0.1", 8766)]:
                require_free(host, port)
            if options.tts_backend == "voxcpm2":
                require_no_listener("127.0.0.1", VOXCPM_PORT)
            # 端口均空闲后才检查并同步小智私有配置，避免给外部正在运行的
            # 语音服务换地址、声音、模型或记忆后端。先完成四项只读检查，
            # 再逐项备份写入；格式错误不会造成“改了一半才发现无法检查”。
            from network import config_action as network_config_action
            from tts import config_action as tts_config_action
            from model import config_action as model_config_action
            from memory import config_action as memory_config_action
            network_checked = network_config_action(options.voice_root, options.lan_ip)
            tts_checked = tts_config_action(
                options.voice_root, options.root, options.tts_backend
            )
            model_checked = model_config_action(
                options.voice_root, options.root, options.voice_model_profile
            )
            memory_checked = memory_config_action(
                options.voice_root, options.root, options.memory_backend
            )
            if network_checked["changed"]:
                network_config_action(options.voice_root, options.lan_ip, apply=True)
            if not tts_checked["config_matches"]:
                tts_config_action(
                    options.voice_root, options.root, options.tts_backend,
                    apply=True, expected_digest=tts_checked["digest"],
                )
            if not model_checked["config_matches"]:
                model_config_action(options.voice_root, options.root,
                                    options.voice_model_profile, apply=True,
                                    expected_digest=model_checked["digest"])
            # 记忆后端与模型/TTS 一样只在端口空闲后同步。切换只改变提供器
            # 指针及缺失的内置配置，不读取、迁移或删除任何后端数据。
            if not memory_checked["config_matches"]:
                memory_config_action(
                    options.voice_root, options.root, options.memory_backend,
                    apply=True, expected_digest=memory_checked["digest"],
                )
        self.options = options
        self.instance = secrets.token_hex(24)
        runtime_token = secrets.token_hex(32)
        env = os.environ.copy()
        env.update(
            PYTHONUTF8="1",
            LONGMEMORY_LAUNCHER_INSTANCE=self.instance,
            LONGMEMORY_MEMORY_TRANSPORT="runtime",
            LONGMEMORY_RUNTIME_URL=(
                f"http://127.0.0.1:{options.port}/api/internal/memory/prepare"
            ),
            LONGMEMORY_RUNTIME_TOKEN=runtime_token,
        )
        try:
            for name, command, cwd in commands:
                self.services[name] = OwnedService(command, cwd, env)
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
            return response.status == 200 and response.getheader("X-LongMemory-Instance") == self.instance
        except (OSError, http.client.HTTPException):
            return False
        finally:
            conn.close()

    def voxcpm_ready(self):
        if "voxcpm2" not in self.services or self.services["voxcpm2"].process.poll() is not None:
            return False
        conn = http.client.HTTPConnection("127.0.0.1", VOXCPM_PORT, timeout=0.25)
        try:
            conn.request("GET", "/health")
            response = conn.getresponse()
            body = json.loads(response.read(4096))
            return response.status == 200 and body.get("ready") is True and body.get("provider") == "voxcpm2"
        except (OSError, http.client.HTTPException, json.JSONDecodeError):
            return False
        finally:
            conn.close()

    def stop(self):
        errors = []
        for service in reversed(list(self.services.values())):
            try:
                service.stop()
            except Exception:
                errors.append(service)
        if errors:
            raise RuntimeError("停止未完全确认，请勿重复启动。")
        self.services.clear()
