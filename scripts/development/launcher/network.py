"""只读发现网卡；显式同步交给小智已有 Python，不新增 YAML 依赖。"""
import ipaddress
import json
import subprocess
from pathlib import Path
from voice_ports import validate_voice_ports


def private_ipv4(value):
    address = ipaddress.IPv4Address(value)
    if not any(address in ipaddress.ip_network(net) for net in
               ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
        raise ValueError('请选择本机 RFC1918 局域网 IPv4。')
    return str(address)


def local_addresses():
    # .NET 网卡枚举不依赖管理员权限，不向外网发送探测包。
    command = "[System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | Where-Object OperationalStatus -eq Up | ForEach-Object { $_.GetIPProperties().UnicastAddresses | ForEach-Object { $_.Address.ToString() } } | ConvertTo-Json -Compress"
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise ValueError('网卡枚举超时，请稍后刷新。') from None
    if result.returncode:
        raise ValueError('无法读取本机网卡，请检查网络后刷新。')
    values = json.loads(result.stdout.decode('utf-8-sig') or '[]')
    found = []
    for value in ([values] if isinstance(values, str) else values or []):
        try:
            found.append(private_ipv4(value))
        except ValueError:
            pass
    return sorted(set(found))


def config_action(server, address, apply=False, *, ws_port=8000, http_port=8003, expected_digest=None, refresh_consumer=False):
    private_ipv4(address)
    validate_voice_ports(ws_port, http_port)
    if address not in local_addresses():
        raise ValueError('所选 IP 已不在本机网卡上，请刷新地址。')
    try:
        result = subprocess.run([str(server / '.venv/Scripts/python.exe'),
                             str(Path(__file__).with_name('sync_network.py')),
                             str(server), address, 'apply' if apply else 'check', str(ws_port), str(http_port),
                             expected_digest or '', 'refresh-network-copy' if refresh_consumer else ''],
                                capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise ValueError('同步检查超时，请核对配置后重试；不要假定配置未写入。') from None
    # 不回显第三方异常或配置原文，避免带出凭据。
    if result.returncode:
        raise ValueError('小智网络配置检查/同步失败；未启动服务。请核对目录与配置格式。')
    return json.loads(result.stdout.decode('utf-8'))


def load_choice(path):
    try:
        return private_ipv4(json.loads(path.read_text(encoding='utf-8'))['lan_ip'])
    except (OSError, ValueError, KeyError, TypeError):
        return ''


def save_choice(path, address):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'lan_ip': private_ipv4(address)}), encoding='utf-8')
