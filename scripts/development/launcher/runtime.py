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


@dataclass(frozen=True)
class Options:
    root: Path = ROOT
    database: Path = ROOT / "data/databases/xiaozhi-demo-v1.db"
    port: int = 8767
    role: str = "elysia_v1"
    voice: bool = False
    voice_root: Path = VOICE_ROOT
    lan_ip: str = "192.168.124.45"
    consent: bool = False


def require_free(host, port):
    """仅预检；真正启动仍可能遇到竞争，不把检查通过当作服务就绪。"""
    with socket.socket() as sock:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((host, port))
        except OSError:
            raise ValueError(f"地址 {host}:{port} 不可绑定。请检查 IP 或停止旧服务；未自动关闭其他程序。") from None


def build_commands(options, uv=None):
    """返回参数列表，绝不拼接 shell 命令；只引用现有环境和配置。"""
    if not options.consent:
        raise ValueError("请先确认聊天写入及当前 HTTP 传输风险。")
    if not 1024 <= options.port <= 65535 or options.port in {8000, 8003, 8766}:
        raise ValueError("控制台端口需在 1024–65535 且不占用小智端口。")
    if options.role not in {"plain_v1", "elysia_v1"}:
        raise ValueError("未知助手角色。")
    root = options.root.resolve()
    if not options.database.is_file():
        raise ValueError("请选择已有日常数据库；启动器不会创建或迁移数据库。")
    if not (root / ".env").is_file() or not (root / ".venv/Scripts/python.exe").is_file():
        raise ValueError("缺少项目 .env 或虚拟环境，请按使用说明准备。")
    uv = uv or shutil.which("uv")
    if not uv:
        raise ValueError("未找到 uv，请检查已有安装的 PATH。启动器不自动安装依赖。")
    console = [str(uv), "run", "--offline", "--no-sync", "--env-file", str(root / ".env"),
               "python", "-m", "longmemory.entrypoints.api", "--port", str(options.port),
               "--database", str(options.database.resolve()), "--enable-chat",
               "--chat-provider", "openai_compatible", "--assistant-role", options.role]
    # 实验启动与删除默认关闭；不因日常启动隐式开启高风险管理功能。
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
        commands.append(("voice", [str(python), str(Path(__file__).with_name("voice.py")),
                                  str(root), str(options.voice_root.resolve()), str(options.database.resolve()),
                                  str(ip)], options.voice_root.resolve()))
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
        self.options = options
        self.instance = secrets.token_hex(24)
        env = os.environ.copy()
        env.update(PYTHONUTF8="1", LONGMEMORY_LAUNCHER_INSTANCE=self.instance)
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
