# 在管理员 PowerShell 中显式执行。只管理本工具自己的单条演示规则。
# 不关闭防火墙、不更改网络类型，也不撤销其他应用的规则。
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Allow', 'Revoke')]
    [string]$Action,
    [string]$ListenAddress,
    [string]$RemoteSubnet
)
$ErrorActionPreference = 'Stop'
$voiceRuleName = 'LongMemory-Xiaozhi-LAN-Demo'
$wallpaperRuleName = 'LongMemory-Wallpaper-LAN-Demo'
$ruleNames = @($voiceRuleName, $wallpaperRuleName)

if ($Action -eq 'Revoke') {
    $existing = @($ruleNames | ForEach-Object { Get-NetFirewallRule -Name $_ -ErrorAction SilentlyContinue })
    if ($existing) {
        $existing | Remove-NetFirewallRule
        Write-Output '已撤销本项目语音与壁纸演示规则；服务需另外停止。'
    } else {
        Write-Output '本项目演示规则不存在，无需撤销。'
    }
    return
}

# 只允许单个局域网监听地址，以及一个明确的 IPv4 地址或 /21 到 /32 网段。
# 不接受 Any、LocalSubnet、通配符或公网范围。
function Get-PrivateIPv4([string]$Value) {
    $parsed = $null
    if ($Value -notmatch '^\d{1,3}(\.\d{1,3}){3}$' -or
        -not [System.Net.IPAddress]::TryParse($Value, [ref]$parsed)) {
        throw '必须指定 IPv4 地址。'
    }
    $octets = $parsed.GetAddressBytes()
    if (-not ($octets[0] -eq 10 -or
        ($octets[0] -eq 172 -and $octets[1] -ge 16 -and $octets[1] -le 31) -or
        ($octets[0] -eq 192 -and $octets[1] -eq 168))) {
        throw '只允许 RFC1918 局域网地址。'
    }
    return $parsed.ToString()
}
$ListenAddress = Get-PrivateIPv4 $ListenAddress
if (-not $RemoteSubnet) { throw '必须提供圆屏来源 IP 或明确的来源网段。' }
$parts = $RemoteSubnet.Split('/')
if ($parts.Count -gt 2) { throw '来源网段格式无效。' }
$remoteIP = Get-PrivateIPv4 $parts[0]
$prefix = 32
if ($parts.Count -eq 2) {
    if ($parts[1] -notmatch '^\d{1,2}$') { throw '来源前缀无效。' }
    $prefix = [int]$parts[1]
    if ($prefix -lt 21 -or $prefix -gt 32) { throw '演示仅接受 /21 到 /32 的来源范围。' }
}
$RemoteSubnet = "$remoteIP/$prefix"
if (@($ruleNames | ForEach-Object { Get-NetFirewallRule -Name $_ -ErrorAction SilentlyContinue }).Count -gt 0) {
    throw '演示规则已存在。若需调整，先显式 Revoke，再 Allow；不会覆盖。'
}
$adapter = @(Get-NetIPAddress -AddressFamily IPv4 -IPAddress $ListenAddress)
if ($adapter.Count -ne 1) { throw '监听地址没有唯一对应的本机网卡。' }
$disabled = @(Get-NetFirewallProfile | Where-Object { $_.Enabled -ne 'True' })
if ($disabled.Count -gt 0) { throw '检测到有防火墙配置文件未启用，先处理后再开放演示。' }

# 从实际监听进程取得可执行路径，避免 Windows 虚拟环境重定向导致规则指错程序。
$listeners = @(Get-NetTCPConnection -State Listen -LocalAddress $ListenAddress -LocalPort 8000,8003)
if (@($listeners.LocalPort | Sort-Object -Unique).Count -ne 2) {
    throw '请先按局域网模式启动服务，确认该地址的 8000/8003 都已监听。'
}
$owners = @($listeners.OwningProcess | Sort-Object -Unique)
if ($owners.Count -ne 1) { throw '两个端口不是同一进程，本工具拒绝放行。' }
$programPath = (Get-Process -Id $owners[0]).Path
if (-not $programPath -or [System.IO.Path]::GetFileName($programPath) -ne 'python.exe') {
    throw '监听进程不是预期的 python.exe，拒绝放行。'
}
$wallpaperListeners = @(Get-NetTCPConnection -State Listen -LocalAddress $ListenAddress -LocalPort 8768)
if ($wallpaperListeners.Count -ne 1) {
    throw '请用新版启动面板启动圆屏服务，确认该地址的 8768 已监听。'
}
$wallpaperProgramPath = (Get-Process -Id $wallpaperListeners[0].OwningProcess).Path
if (-not $wallpaperProgramPath -or [System.IO.Path]::GetFileName($wallpaperProgramPath) -ne 'python.exe') {
    throw '壁纸投递监听进程不是预期的 python.exe，拒绝放行。'
}
try {
    New-NetFirewallRule -Name $voiceRuleName -DisplayName $voiceRuleName `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000,8003 `
        -LocalAddress $ListenAddress -RemoteAddress $RemoteSubnet `
        -InterfaceAlias $adapter[0].InterfaceAlias -Program $programPath `
        -Profile Any -EdgeTraversalPolicy Block | Out-Null
    New-NetFirewallRule -Name $wallpaperRuleName -DisplayName $wallpaperRuleName `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8768 `
        -LocalAddress $ListenAddress -RemoteAddress $RemoteSubnet `
        -InterfaceAlias $adapter[0].InterfaceAlias -Program $wallpaperProgramPath `
        -Profile Any -EdgeTraversalPolicy Block | Out-Null
} catch {
    $ruleNames | ForEach-Object { Get-NetFirewallRule -Name $_ -ErrorAction SilentlyContinue | Remove-NetFirewallRule }
    throw
}
Write-Output "已创建临时演示规则：$ListenAddress 的 8000/8003 与单文件壁纸端口 8768，仅来自 $RemoteSubnet。"
Write-Output "语音进程：$programPath；壁纸进程：$wallpaperProgramPath。演示结束请 Revoke。"
