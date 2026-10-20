#requires -Version 5.1
<#
.SYNOPSIS
所有者执行的固定 Smart Turn CPU 模型获取入口；本次已下载，无需重跑。
.EXAMPLE
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/development/xiaozhi/Download-SmartTurn.ps1
.EXAMPLE
.\scripts\development\xiaozhi\Download-SmartTurn.ps1 -Proxy http://your-proxy:port
#>
[CmdletBinding()]
param(
    [string]$ModelDirectory = (Join-Path $PSScriptRoot '../../../local/runtime/models/smart-turn-v3.2'),
    [string]$Proxy = '',
    [string]$CurlPath = 'curl.exe'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# 固定来源；不提供 URL、版本、大小或摘要覆盖参数，不下载源码/依赖。
$SourceCommit = '4786657e242dfe77dd138699ac564ee074a2a543'
$ModelRevision = 'f766f81d3cfdf7737ac64aad813d91bbfd56bf93'
$ModelName = 'smart-turn-v3.2-cpu.onnx'
$ExpectedBytes = 8679182L
$ExpectedSha256 = '2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f'
$ModelUrl = "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/$ModelRevision/$ModelName"

function Assert-ModelFile([string]$Path) {
    $item = Get-Item -LiteralPath $Path
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'UNSUPPORTED_TARGET'
    }
    if ($item.Length -ne $ExpectedBytes) { throw 'SIZE_MISMATCH' }
    # 直接用 .NET，避免 PowerShell 5 继承不同版本 PSModulePath 时找不到 Get-FileHash。
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $actualSha256 = ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose(); $stream.Dispose() }
    if ($actualSha256 -ne $ExpectedSha256) {
        throw 'SHA256_MISMATCH'
    }
}

try {
    $directory = [IO.Path]::GetFullPath($ModelDirectory)
    $destination = Join-Path $directory $ModelName
    $partial = $destination + '.download'

    # 正式文件存在时只读核验；无论正确与否，都不联网、不覆盖或处理旧临时文件。
    if (Test-Path -LiteralPath $destination) {
        Assert-ModelFile $destination
        Write-Output 'SmartTurn VERIFIED_EXISTING; no download or changes.'
        exit 0
    }
    if (Test-Path -LiteralPath $directory) {
        $directoryItem = Get-Item -LiteralPath $directory
        if (-not $directoryItem.PSIsContainer -or ($directoryItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'UNSUPPORTED_TARGET'
        }
    }
    $partialBytes = 0L
    if (Test-Path -LiteralPath $partial) {
        $partialItem = Get-Item -LiteralPath $partial
        if ($partialItem.PSIsContainer -or ($partialItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'UNSUPPORTED_TARGET'
        }
        $partialBytes = $partialItem.Length
        if ($partialBytes -gt $ExpectedBytes) { throw 'SIZE_MISMATCH' }
    }
    if ($partialBytes -lt $ExpectedBytes) {
        if ($Proxy) {
            $proxyUri = $null
            if (-not [Uri]::TryCreate($Proxy, [UriKind]::Absolute, [ref]$proxyUri) -or
                $proxyUri.Scheme -notin @('http', 'https', 'socks5', 'socks5h')) {
                throw 'INVALID_PROXY'
            }
        }
        try { $curl = Get-Command -Name $CurlPath -CommandType Application | Select-Object -First 1 }
        catch { throw 'CURL_NOT_FOUND' }
        if ($null -eq $curl) { throw 'CURL_NOT_FOUND' }
        [IO.Directory]::CreateDirectory($directory) | Out-Null
        # -q 必须为首个参数：不读 .curlrc，不改全局配置/代理，不重试或换源。
        $curlArguments = @('-q', '--fail', '--location', '--proto', '=https', '--proto-redir', '=https',
                           '--continue-at', '-', '--connect-timeout', '20', '--max-time', '600', '--output', $partial)
        if ($Proxy) { $curlArguments += @('--proxy', $Proxy) }
        $curlArguments += $ModelUrl
        $savedErrorPreference = $ErrorActionPreference
        try {
            # Windows PowerShell 5 将原生 stderr 包装为 ErrorRecord；进度不等于失败。
            $ErrorActionPreference = 'Continue'
            & $curl.Source @curlArguments
            $curlExitCode = $LASTEXITCODE
        } finally { $ErrorActionPreference = $savedErrorPreference }
        if ($null -eq $curlExitCode -or $curlExitCode -ne 0) {
            [Console]::Error.WriteLine("SmartTurn CURL_FAILED exit=$curlExitCode; partial file retained.")
            exit 3
        }
    }
    Assert-ModelFile $partial
    # 同目录、无覆盖重命名；即便此刻有人创建了正式文件，也只失败并保留现场。
    [IO.File]::Move($partial, $destination)
    Write-Output "SmartTurn VERIFIED_SAVED; source=$SourceCommit model=$ModelRevision"
    exit 0
} catch {
    $reason = $_.Exception.Message
    if ($reason -notin @('UNSUPPORTED_TARGET', 'SIZE_MISMATCH', 'SHA256_MISMATCH', 'INVALID_PROXY', 'CURL_NOT_FOUND')) {
        $reason = 'IO_FAILED'
    }
    [Console]::Error.WriteLine("SmartTurn $reason; existing files retained, no automatic retry.")
    exit 1
}
