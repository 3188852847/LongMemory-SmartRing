"""只读发现物理网卡并去抖；绝不修改系统网络或推断设备可达性。"""

from dataclasses import dataclass
import ipaddress
import json
import subprocess
from uuid import UUID


@dataclass(frozen=True)
class Choice:
    state: str
    address: str = ''
    interface_id: str = ''


class NetworkSelectionError(ValueError):
    def __init__(self, state):
        self.code = 'network_ambiguous' if state == 'ambiguous' else 'network_unavailable'
        messages = {'ambiguous': '无法唯一确认圆屏所在的物理网卡，请核对局域网 IP。',
                    'offline': '已选物理网卡暂时无可用局域网地址；保持配置，等待网络恢复。'}
        super().__init__(messages.get(state, '物理网卡检测暂不可用；保持配置，请核对网络后重试。'))


def physical_addresses():
    # 物理、在线、首选 IPv4；不用 DNS/路由探测，不把 Docker/VPN 当设备网卡。
    command = """[Console]::OutputEncoding = [Text.UTF8Encoding]::new();
@(Get-NetAdapter -Physical -ErrorAction Stop | Where-Object { $_.Status -eq 'Up' -and $_.HardwareInterface -and -not $_.Virtual } | ForEach-Object {
 $adapter = $_;
 Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -AddressState Preferred -ErrorAction Stop | ForEach-Object {
  [pscustomobject]@{interface_id=$adapter.InterfaceGuid.ToString();address=$_.IPAddress;physical=$true;up=$true;preferred=$true}
 }
}) | ConvertTo-Json -Compress"""
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise ValueError
        rows = json.loads(result.stdout.decode('utf-8-sig') or '[]')
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            raise ValueError
        return rows
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise ValueError('无法确认本机物理网卡；保持原配置，稍后重试。') from None


def choose_address(rows, saved_address='', interface_id=''):
    candidates = set()
    for row in rows:
        if not isinstance(row, dict) or any(row.get(key) is not True for key in ('physical', 'up', 'preferred')):
            continue
        try:
            address = ipaddress.IPv4Address(row['address'])
            identity = str(UUID(row['interface_id']))
            if any(address in ipaddress.ip_network(net) for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
                candidates.add((identity, str(address)))
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    if interface_id:
        try:
            identity = str(UUID(interface_id))
        except (ValueError, TypeError, AttributeError):
            return Choice('ambiguous')
        candidates = {item for item in candidates if item[0] == identity}
    else:
        saved = {item for item in candidates if item[1] == saved_address}
        if len(saved) == 1:
            candidates = saved
    if len(candidates) == 1:
        identity, address = next(iter(candidates))
        return Choice('selected', address, identity)
    return Choice('offline' if not candidates else 'ambiguous')


class NetworkWatch:
    def __init__(self, discover=physical_addresses, *, interval=30, settle_seconds=10, notice_seconds=10):
        self.discover = discover
        self.interval, self.settle_seconds, self.notice_seconds = interval, settle_seconds, notice_seconds
        self.next_poll = 0
        self.candidate = None
        self.since = 0

    def observe(self, values, now, *, initial=False):
        if not initial and now < self.next_poll:
            return None
        self.next_poll = now + self.interval
        choice = choose_address(self.discover(), values['lan_ip'], values['lan_interface_id'])
        if choice != self.candidate:
            self.candidate, self.since = choice, now
        settled = initial or now - self.since >= self.settle_seconds
        restart = not initial and now - self.since >= self.settle_seconds + self.notice_seconds
        return choice, settled, restart
