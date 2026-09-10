"""安全清理占用固定三端口的遗留小智语音进程。"""

import json

from firewall import literal, run_ps
from network import private_ipv4


SAFE_REASONS = {
    "ambiguous_8000_owner",
    "voice_port_ownership_mismatch",
    "owner_is_not_python",
    "ports_still_listening",
    "inspection_or_stop_failed",
}


def close_stale_voice(address: str) -> dict:
    """核对 8000/8003/8766 的共同所有者后，只停止该单个进程。

    端口不能脱离进程单独关闭。三端口共同归属和 Python 进程名是当前
    项目侧小智启动契约；不满足时宁可拒绝，也不根据一个 PID 猜测。
    核对与停止放在同一个 PowerShell 进程中，降低 PID 在两步间复用的风险。
    """
    selected = private_ipv4(address)
    source = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try {
  $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue)
  $primary = @($listeners | Where-Object { $_.LocalAddress -eq ADDRESS -and $_.LocalPort -eq 8000 })
  if ($primary.Count -eq 0) {
    @{ state = 'free' } | ConvertTo-Json -Compress
    exit 0
  }
  if ($primary.Count -ne 1) {
    @{ state = 'refused'; reason = 'ambiguous_8000_owner' } | ConvertTo-Json -Compress
    exit 0
  }
  $ownerId = [int]$primary[0].OwningProcess
  $required = @(
    @($listeners | Where-Object { $_.LocalAddress -eq ADDRESS -and $_.LocalPort -eq 8003 }),
    @($listeners | Where-Object { $_.LocalAddress -eq '127.0.0.1' -and $_.LocalPort -eq 8766 })
  )
  foreach ($items in $required) {
    if ($items.Count -ne 1 -or [int]$items[0].OwningProcess -ne $ownerId) {
      @{ state = 'refused'; reason = 'voice_port_ownership_mismatch' } | ConvertTo-Json -Compress
      exit 0
    }
  }
  $process = Get-Process -Id $ownerId -ErrorAction Stop
  if ($process.ProcessName -notin @('python', 'pythonw')) {
    @{ state = 'refused'; reason = 'owner_is_not_python' } | ConvertTo-Json -Compress
    exit 0
  }
  Stop-Process -Id $ownerId -Force -ErrorAction Stop
  Start-Sleep -Milliseconds 300
  $remaining = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.OwningProcess -eq $ownerId -and $_.LocalPort -in 8000,8003,8766 })
  if ($remaining.Count -gt 0) {
    @{ state = 'failed'; reason = 'ports_still_listening' } | ConvertTo-Json -Compress
    exit 0
  }
  @{ state = 'stopped'; process_id = $ownerId } | ConvertTo-Json -Compress
} catch {
  @{ state = 'failed'; reason = 'inspection_or_stop_failed' } | ConvertTo-Json -Compress
}
""".replace("ADDRESS", literal(selected))
    result = run_ps(source)
    if result.returncode or not result.stdout or len(result.stdout) > 4096:
        raise ValueError("无法核对遗留语音进程；未停止任何程序。")
    try:
        value = json.loads(result.stdout.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("遗留语音进程检查返回无效；停止状态未知，请重新检查端口。") from None
    if not isinstance(value, dict) or value.get("state") not in {
        "free", "refused", "failed", "stopped",
    }:
        raise ValueError("遗留语音进程检查返回无效；停止状态未知，请重新检查端口。")
    if value["state"] == "stopped":
        process_id = value.get("process_id")
        if type(process_id) is not int or process_id <= 0:
            raise ValueError("遗留语音进程检查返回无效；停止状态未知，请重新检查端口。")
        return {"state": "stopped", "process_id": process_id}
    if value["state"] == "free":
        if set(value) != {"state"}:
            raise ValueError("遗留语音进程检查返回无效；停止状态未知，请重新检查端口。")
        return {"state": "free"}
    if (set(value) != {"state", "reason"}
            or value.get("reason") not in SAFE_REASONS):
        raise ValueError("遗留语音进程检查返回无效；停止状态未知，请重新检查端口。")
    return {"state": value["state"], "reason": value["reason"]}
