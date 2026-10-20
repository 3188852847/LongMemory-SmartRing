"""安全清理遗留的小智语音进程或已登记本地 TTS 进程。"""

import json

from firewall import literal, run_ps
from network import private_ipv4


SAFE_REASONS = {
    "independent_ports_require_owned_launcher",
    "ambiguous_8000_owner",
    "voice_port_ownership_mismatch",
    "owner_is_not_python",
    "ports_still_listening",
    "inspection_or_stop_failed",
    "ambiguous_tts_owner",
    "tts_identity_mismatch",
    "tts_owner_changed",
    "owner_is_not_expected_runtime",
}

LOCAL_TTS = {
    "voxcpm2": (18768, ("python", "pythonw")),
    "sanotts": (18769, ("node",)),
    "cosyvoice3": (18770, ("python", "pythonw")),
}


def close_stale_voice(address: str, *, ws_port=8000, http_port=8003) -> dict:
    """核对 8000/8003/8766 的共同所有者后，只停止该单个进程。

    端口不能脱离进程单独关闭。三端口共同归属和 Python 进程名是当前
    项目侧小智启动契约；不满足时宁可拒绝，也不根据一个 PID 猜测。
    核对与停止放在同一个 PowerShell 进程中，降低 PID 在两步间复用的风险。
    """
    if (ws_port, http_port) != (8000, 8003):
        return {'state': 'refused', 'reason': 'independent_ports_require_owned_launcher'}
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


def close_stale_tts(backend: str) -> dict:
    """核对固定端口、健康身份和进程类型后停止所选本地 TTS。

    仅凭端口或 ``python.exe`` 都不足以确认身份。健康检查之后会再次核对
    监听 PID，降低检查与停止之间发生端口所有者变化的风险。
    """
    if backend == "edge":
        return {"state": "free", "provider": "edge"}
    if backend not in LOCAL_TTS:
        raise ValueError("未知本地声音后端；未停止任何程序。")
    port, process_names = LOCAL_TTS[backend]
    source = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try {
  $before = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalAddress -eq '127.0.0.1' -and $_.LocalPort -eq PORT })
  if ($before.Count -eq 0) {
    @{ state = 'free'; provider = PROVIDER } | ConvertTo-Json -Compress
    exit 0
  }
  if ($before.Count -ne 1) {
    @{ state = 'refused'; reason = 'ambiguous_tts_owner'; provider = PROVIDER } | ConvertTo-Json -Compress
    exit 0
  }
  $ownerId = [int]$before[0].OwningProcess
  try {
    $health = Invoke-RestMethod -Uri HEALTH -Method Get -TimeoutSec 2
  } catch {
    @{ state = 'refused'; reason = 'tts_identity_mismatch'; provider = PROVIDER } | ConvertTo-Json -Compress
    exit 0
  }
  if ($health.ready -ne $true -or $health.provider -ne PROVIDER -or
      $health.capabilities.provider_id -ne PROVIDER) {
    @{ state = 'refused'; reason = 'tts_identity_mismatch'; provider = PROVIDER } | ConvertTo-Json -Compress
    exit 0
  }
  $after = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalAddress -eq '127.0.0.1' -and $_.LocalPort -eq PORT })
  if ($after.Count -ne 1 -or [int]$after[0].OwningProcess -ne $ownerId) {
    @{ state = 'refused'; reason = 'tts_owner_changed'; provider = PROVIDER } | ConvertTo-Json -Compress
    exit 0
  }
  $process = Get-Process -Id $ownerId -ErrorAction Stop
  if ($process.ProcessName.ToLowerInvariant() -notin NAMES) {
    @{ state = 'refused'; reason = 'owner_is_not_expected_runtime'; provider = PROVIDER } | ConvertTo-Json -Compress
    exit 0
  }
  Stop-Process -Id $ownerId -Force -ErrorAction Stop
  Start-Sleep -Milliseconds 300
  $remaining = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalAddress -eq '127.0.0.1' -and $_.LocalPort -eq PORT })
  if ($remaining.Count -gt 0) {
    @{ state = 'failed'; reason = 'ports_still_listening'; provider = PROVIDER } | ConvertTo-Json -Compress
    exit 0
  }
  @{ state = 'stopped'; process_id = $ownerId; provider = PROVIDER } | ConvertTo-Json -Compress
} catch {
  @{ state = 'failed'; reason = 'inspection_or_stop_failed'; provider = PROVIDER } | ConvertTo-Json -Compress
}
"""
    replacements = {
        "PORT": str(port),
        "PROVIDER": literal(backend),
        "HEALTH": literal(f"http://127.0.0.1:{port}/health"),
        "NAMES": "@(" + ",".join(literal(name) for name in process_names) + ")",
    }
    for marker, value in replacements.items():
        source = source.replace(marker, value)
    result = run_ps(source)
    if result.returncode or not result.stdout or len(result.stdout) > 4096:
        raise ValueError("无法核对遗留声音进程；未停止任何程序。")
    try:
        value = json.loads(result.stdout.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("遗留声音进程检查返回无效；停止状态未知。") from None
    state = value.get("state") if isinstance(value, dict) else None
    if state not in {"free", "refused", "failed", "stopped"} or value.get("provider") != backend:
        raise ValueError("遗留声音进程检查返回无效；停止状态未知。")
    if state == "stopped":
        if set(value) != {"state", "provider", "process_id"} or type(value["process_id"]) is not int or value["process_id"] <= 0:
            raise ValueError("遗留声音进程检查返回无效；停止状态未知。")
    elif state == "free":
        if set(value) != {"state", "provider"}:
            raise ValueError("遗留声音进程检查返回无效；停止状态未知。")
    elif (set(value) != {"state", "provider", "reason"}
          or value.get("reason") not in SAFE_REASONS):
        raise ValueError("遗留声音进程检查返回无效；停止状态未知。")
    return value
