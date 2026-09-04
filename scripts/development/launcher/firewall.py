"""防火墙窄入口：查询无需提权，写操作仅由用户点击触发 UAC。"""
import base64
import ipaddress
import json
from pathlib import Path
import subprocess

from network import private_ipv4


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def encoded(source):
    return base64.b64encode(source.encode('utf-16-le')).decode('ascii')


def run_ps(source):
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                           '-EncodedCommand', encoded(source)], capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW)


def scope(address, subnet):
    address = private_ipv4(address)
    network = ipaddress.IPv4Network(subnet, strict=False)
    if not 21 <= network.prefixlen <= 32:
        raise ValueError('来源范围只允许 /21 到 /32；优先填写圆屏单个 IP。')
    private_ipv4(str(network.network_address))
    private_ipv4(str(network.broadcast_address))
    return address, str(network)


def inspect(address):
    address = private_ipv4(address)
    source = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try {
  $rules = @(Get-NetFirewallRule | Where-Object Name -eq 'LongMemory-Xiaozhi-LAN-Demo')
  $listeners = @(Get-NetTCPConnection -State Listen | Where-Object { $_.LocalAddress -eq ADDRESS -and $_.LocalPort -in 8000,8003 })
  $details = @($rules | ForEach-Object {
    $a = $_ | Get-NetFirewallAddressFilter
    [pscustomobject]@{ enabled = [string]$_.Enabled; local = @($a.LocalAddress); remote = @($a.RemoteAddress) }
  })
  @{ ports = @($listeners.LocalPort | Sort-Object -Unique); rules = $details } | ConvertTo-Json -Depth 5 -Compress
} catch { exit 1 }
""".replace('ADDRESS', literal(address))
    result = run_ps(source)
    if result.returncode:
        raise ValueError('无法读取监听或规则状态（可能权限不足），不是“规则不存在”。未修改防火墙。')
    return json.loads(result.stdout.decode('utf-8-sig'))


def change(action, address, subnet, root):
    if action not in ('Allow', 'Revoke'):
        raise ValueError('未知操作')
    address, subnet = scope(address, subnet) if action == 'Allow' else ('', '')
    script = Path(root) / 'scripts/development/xiaozhi/firewall.ps1'
    # 固定仓库脚本；UTF-8 显式读取兼容 Windows PowerShell 5，参数严格验证。
    child = ("$ErrorActionPreference='Stop'; try { & ([scriptblock]::Create("
             f"[IO.File]::ReadAllText({literal(script)}, [Text.Encoding]::UTF8))) "
             f"-Action {action} -ListenAddress {literal(address)} -RemoteSubnet {literal(subnet)}; exit 0 "
             "} catch { exit 1 }")
    # 用户取消 UAC 与规则执行失败分开反馈；不让整个面板获得管理员权限。
    parent = ("try { $p = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') "
              "-Verb RunAs -WindowStyle Hidden -PassThru -Wait -ArgumentList "
              f"@('-NoProfile','-NonInteractive','-EncodedCommand','{encoded(child)}'); exit $p.ExitCode "
              "} catch { exit 1223 }")
    result = run_ps(parent)
    if result.returncode == 1223:
        raise ValueError('管理员授权已取消或无法发起；未确认修改。')
    if result.returncode:
        raise ValueError('规则操作未成功：添加前请确认小智已监听、项目规则不存在且防火墙已启用。请重新检查状态；不会覆盖旧规则。')
    return '项目规则操作完成。请点击检查核对；这不代表圆屏已连接。'
