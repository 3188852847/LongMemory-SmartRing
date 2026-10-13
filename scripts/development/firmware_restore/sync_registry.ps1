[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$EspRoot,
    [Parameter(Mandatory = $true)][string]$SdkPath,
    [Parameter(Mandatory = $true)][string]$PriorRegistry,
    [string]$VendorRegistry = 'C:\Espressif\tools\eim_idf.json'
)
$ErrorActionPreference = 'Stop'
# Windows 临时目录可能使用 RUNNER~1 等 8.3 别名；.NET 会将候选路径展开
# 为长路径。根目录与 SDK 比较也必须使用同一种规范化，否则同目录被误判越界。
$EspRoot = [IO.Path]::GetFullPath($EspRoot).TrimEnd('\')
$SdkPath = [IO.Path]::GetFullPath($SdkPath).TrimEnd('\')
$destination = Join-Path $EspRoot 'tools\eim_idf.json'
# EIM 0.19.0 fix 的默认 C 盘登记行为已在本机复现。只合并厂商实际完成记录，
# 不伪造安装成功；保留 D 盘已有版本和原默认选择。
$candidates = @($destination, $VendorRegistry)
$completed = @()
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) {
        $candidateRegistry = Get-Content -LiteralPath $candidate -Raw -Encoding UTF8 | ConvertFrom-Json
        $completed += @($candidateRegistry.idfInstalled | Where-Object {
            [IO.Path]::GetFullPath($_.path).TrimEnd('\') -eq $SdkPath -and $_.status -eq 'finished'
        })
    }
}
if ($completed.Count -lt 1) { throw 'EIM 没有实际完成记录，不能登记安装成功。' }
$record = $completed[-1]
foreach ($path in @($record.python, $record.activationScript)) {
    $resolved = [IO.Path]::GetFullPath($path)
    if (-not $resolved.StartsWith($EspRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath $resolved)) { throw '厂商完成记录的路径越界或缺失。' }
}
if ([IO.Path]::GetFullPath($record.python) -ne (Join-Path $EspRoot 'python_env\v5.5.4\venv\Scripts\python.exe')) {
    throw 'EIM 的 Python 环境不是预期的版本专属目录。'
}
$registry = Get-Content -LiteralPath $PriorRegistry -Raw -Encoding UTF8 | ConvertFrom-Json
$registry.idfInstalled = @($registry.idfInstalled | Where-Object {
    [IO.Path]::GetFullPath($_.path).TrimEnd('\') -ne $SdkPath
}) + @($record)
$temporary = $destination + '.smart-ring.tmp'
if (Test-Path -LiteralPath $temporary) { throw '登记临时文件已存在，保留现场并停止。' }
[IO.File]::WriteAllText($temporary, ($registry | ConvertTo-Json -Depth 16), (New-Object Text.UTF8Encoding($false)))
Move-Item -LiteralPath $temporary -Destination $destination -Force
Write-Output '已合并官方 5.5.4 完成记录，保留原默认 SDK 选择。'
