# 固定板型的检查、联网配置及本地构建入口；没有串口或烧录操作。
[CmdletBinding()]
param(
    [ValidateSet('Check', 'Configure', 'Build')][string]$Action = 'Check',
    [string]$ProxyScript,
    [string]$EspRoot = 'D:\Dev\esp',
    [string]$WorkRoot = 'D:\Dev\esp-projects\smart-ring'
)
$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$helper = Join-Path $PSScriptRoot 'firmware_restore'
$python = Join-Path $project '.venv\Scripts\python.exe'
$sdk = Join-Path $EspRoot 'v5.5.4\esp-idf'
$sdkPython = Join-Path $EspRoot 'python_env\v5.5.4\venv\Scripts\python.exe'
$sdkProfilePath = Join-Path $EspRoot 'Microsoft.v5.5.4.PowerShell_profile.ps1'
$vendor = Join-Path $WorkRoot 'vendor\SmartRing-Plus'
$source = Join-Path $WorkRoot 'src'
$build = Join-Path $WorkRoot 'build-idf554'
foreach ($path in @($EspRoot, $WorkRoot)) {
    if (-not [IO.Path]::IsPathRooted($path) -or $path -match '[^\x21-\x7E]' -or $path -match '[()]') {
        throw 'SDK 和实际工作目录必须为无空格、括号的 ASCII 绝对路径。'
    }
}
function Invoke-Checked([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "操作失败（退出码 $LASTEXITCODE）：$Command；保留现场，不清理构建或源码。" }
}
if (-not (Test-Path -LiteralPath $sdkProfilePath) -or -not (Test-Path -LiteralPath $sdkPython)) {
    throw '先执行 run_firmware_restore.ps1，准备独立的 ESP-IDF 5.5.4。'
}
Invoke-Checked $python @((Join-Path $helper 'check_sources.py'), 'sdk', $sdk)
# 由 powershell.exe -NoProfile -File 在独立进程使用，不点源进入日常终端。
. $sdkProfilePath
$env:PYTHONUTF8 = '1'
$env:PIP_CACHE_DIR = Join-Path $EspRoot 'cache\pip'
$env:CCACHE_DIR = Join-Path $EspRoot 'cache\ccache'
$env:IDF_COMPONENT_CACHE_PATH = Join-Path $WorkRoot 'cache\components'
if ([IO.Path]::GetFullPath($env:IDF_PATH).TrimEnd('\') -ne $sdk) { throw '激活后不是固定的 5.5.4 SDK，停止。' }
Invoke-Checked $sdkPython @('-c', 'import sys; assert sys.version_info[:3] == (3, 11, 15); print(sys.executable); print(sys.base_prefix)')
$cmake = (Get-Command cmake.exe -ErrorAction Stop).Source
$ninja = (Get-Command ninja.exe -ErrorAction Stop).Source
$compiler = (Get-Command xtensa-esp32s3-elf-gcc.exe -ErrorAction Stop).Source
foreach ($tool in @($cmake, $ninja, $compiler)) {
    if (-not $tool.StartsWith($EspRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '命令来自公共工具链，停止。' }
}
$cmakeVersion = & $cmake --version
if ($LASTEXITCODE -ne 0 -or $cmakeVersion[0] -ne 'cmake version 3.30.2') { throw '不是固定的 SDK CMake 3.30.2。' }
$ninjaVersion = & $ninja --version
if ($LASTEXITCODE -ne 0 -or $ninjaVersion -ne '1.12.1') { throw '不是固定的 SDK Ninja 1.12.1。' }
$compilerVersion = & $compiler --version
if ($LASTEXITCODE -ne 0 -or ($compilerVersion -join "`n") -notmatch '14\.2\.0') { throw '不是固定的 GCC 14.2.0。' }
Write-Output ($compilerVersion -join "`n")
Invoke-Checked $sdkPython @((Join-Path $sdk 'tools\idf.py'), '--version')
Invoke-Checked $sdkPython @('-m', 'pip', 'check')
Write-Output "SDK 专属命令核对：$cmake；$ninja；$compiler"
if ($Action -eq 'Check') { return }
if (-not (Test-Path -LiteralPath $source)) {
    if ($Action -ne 'Configure') { throw '缺少新工作副本，请先执行联网 Configure 阶段。' }
    Invoke-Checked $python @((Join-Path $helper 'prepare_worktree.py'), '--vendor', $vendor, '--work-root', $WorkRoot)
}
$receipt = Get-Content -LiteralPath (Join-Path $source 'restore-source.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($receipt.target -ne 'esp32s3' -or $receipt.sdk_commit -ne '735507283d5b2f9fb363a1901172dbd9e847945d') {
    throw '工作副本没有匹配的恢复身份，不编译未知工程。'
}
if ($Action -eq 'Configure') {
    if (-not $ProxyScript -or -not (Test-Path -LiteralPath $ProxyScript)) { throw '联网配置阶段需显式提供机器代理脚本。' }
    . $ProxyScript
    $enable = Get-Command Enable-DevProxy -CommandType Function -ErrorAction Stop
    $disable = Get-Command Disable-DevProxy -CommandType Function -ErrorAction Stop
    Push-Location -LiteralPath $source
    try {
        & $enable
        # 此阶段由所有者执行：Component Manager 按版本记录重新取得组件。
        # 独立 build 不复用旧 CMakeCache；不传 flash / monitor 或串口参数。
        Invoke-Checked $sdkPython @((Join-Path $sdk 'tools\idf.py'), '-B', $build,
            '-DIDF_TARGET=esp32s3', '-DSDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.defaults.esp32s3;sdkconfig.restore.defaults',
            'reconfigure')
    }
    finally { & $disable; Pop-Location }
    Write-Output 'Configure 已完成；组件及模型文件仍须核对，然后进行实际本地编译。'
    return
}
if (-not (Test-Path -LiteralPath (Join-Path $build 'build.ninja'))) { throw '缺少已完成的配置，请先由所有者执行 Configure。' }
# 先用 Ninja 只读列出动作。若要求重新配置，交回用户的联网 Configure 阶段，
# 不在助手构建中隐式下载新的依赖；本脚本也不尝试清理或自动重试。
$plan = & $ninja -C $build -n all 2>&1
if ($LASTEXITCODE -ne 0) { throw '构建预检失败，请核对配置，保留现场。' }
if (($plan -join "`n") -match '(?i)Re-running CMake|--regenerate-during-build') {
    throw 'Ninja 要求重新配置，请先由所有者执行 Configure；尚未开始编译。'
}
Invoke-Checked $ninja @('-C', $build, '-j', '4', 'all')
Invoke-Checked $python @((Join-Path $helper 'check_artifacts.py'), $build)
