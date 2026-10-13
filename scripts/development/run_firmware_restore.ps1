# 由所有者执行的联网准备入口。本脚本只有下载和安装阶段，没有烧录入口。
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ProxyScript,
    [ValidateSet('All', 'Sources', 'Sdk')][string]$Stage = 'All',
    [string]$EspRoot = 'D:\Dev\esp',
    [string]$WorkRoot = 'D:\Dev\esp-projects\smart-ring'
)
$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$helper = Join-Path $PSScriptRoot 'firmware_restore'
$manifest = Get-Content -LiteralPath (Join-Path $helper 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$projectPython = Join-Path $project '.venv\Scripts\python.exe'
$eim = Join-Path $EspRoot 'eim\eim-v0.19.0.exe'
$sdk = Join-Path $EspRoot 'v5.5.4\esp-idf'
$vendor = Join-Path $WorkRoot 'vendor\SmartRing-Plus'
foreach ($path in @($EspRoot, $WorkRoot)) {
    if (-not [IO.Path]::IsPathRooted($path) -or $path -match '[^\x21-\x7E]' -or $path -match '[()]') {
        throw 'SDK 和实际固件目录必须为绝对 ASCII 路径，不能含空格或括号。'
    }
}
if (-not (Test-Path -LiteralPath $projectPython)) { throw '缺少主项目已有 Python；不自动安装主项目依赖。' }
if (-not (Test-Path -LiteralPath $ProxyScript)) { throw '找不到指定的机器代理脚本。' }
$git = (Get-Command git.exe -ErrorAction Stop).Source
$uv = (Get-Command uv.exe -ErrorAction Stop).Source
function Invoke-Checked([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "命令失败（退出码 $LASTEXITCODE）：$Command；保留已下载内容，本阶段停止。" }
}
function Invoke-Git([string[]]$Arguments) {
    $options = @('-c', 'core.longpaths=true')
    if ($env:HTTPS_PROXY) { $options += @('-c', ('http.proxy=' + $env:HTTPS_PROXY)) }
    Invoke-Checked $git ($options + $Arguments)
}
$names = @('PATH','PIP_CACHE_DIR','UV_CACHE_DIR','UV_PYTHON_INSTALL_DIR','IDF_TOOLS_PATH',
           'IDF_PATH','IDF_PYTHON_ENV_PATH','VIRTUAL_ENV','PYTHONPATH','TEMP','TMP','PYTHONUTF8')
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
. $ProxyScript
$enable = Get-Command Enable-DevProxy -CommandType Function -ErrorAction Stop
$disable = Get-Command Disable-DevProxy -CommandType Function -ErrorAction Stop
try {
    & $enable
    $env:PYTHONUTF8 = '1'
    if ($Stage -in @('All', 'Sdk')) {
        if (-not (Test-Path -LiteralPath $eim) -or
            (Get-FileHash -LiteralPath $eim -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.eim.sha256) {
            throw '已有 EIM 0.19.0 不存在或摘要不匹配；未替换现有管理器。'
        }
        if (-not (Test-Path -LiteralPath $sdk)) {
            Invoke-Git @('clone', '--config', 'core.autocrlf=false', '--depth', '1', '--branch', $manifest.sdk.tag,
                         '--recurse-submodules', '--shallow-submodules', $manifest.sdk.repository, $sdk)
        } else {
            $head = & $git -C $sdk rev-parse HEAD
            if ($LASTEXITCODE -ne 0 -or $head -ne $manifest.sdk.commit) {
                throw '已有 SDK 目录不是固定提交；未覆盖、删除或重新克隆。'
            }
            Invoke-Git @('-C', $sdk, 'submodule', 'update', '--init', '--recursive', '--depth', '1')
        }
        Invoke-Checked $projectPython @((Join-Path $helper 'check_sources.py'), 'sdk', $sdk)
        Invoke-Checked $uv @('python', 'install', $manifest.sdk.python_version,
                            '--install-dir', (Join-Path $EspRoot 'python'), '--no-bin', '--no-registry',
                            '--no-config', '--cache-dir', (Join-Path $EspRoot 'cache\uv'))
        $pythonRoot = Join-Path $EspRoot 'python\cpython-3.11.15-windows-x86_64-none'
        if (-not (Test-Path -LiteralPath (Join-Path $pythonRoot 'python.exe'))) { throw '未找到固定的 SDK 基础 Python。' }
        $env:PATH = $pythonRoot + ';' + (Split-Path -Parent $git) + ';' + $saved.PATH
        $env:PIP_CACHE_DIR = Join-Path $EspRoot 'cache\pip'
        $env:UV_CACHE_DIR = Join-Path $EspRoot 'cache\uv'
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $EspRoot 'python'
        $env:IDF_TOOLS_PATH = $EspRoot
        $env:IDF_PATH = $sdk
        foreach ($name in @('IDF_PYTHON_ENV_PATH','VIRTUAL_ENV','PYTHONPATH')) {
            [Environment]::SetEnvironmentVariable($name, $null, 'Process')
        }
        $env:TEMP = Join-Path $EspRoot 'tmp'
        $env:TMP = $env:TEMP
        New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
        $registry = Join-Path $EspRoot 'tools\eim_idf.json'
        if (-not (Test-Path -LiteralPath $registry)) { throw '缺少现有 EIM 版本清单，先核对机器环境，不擅自新建。' }
        $prior = Join-Path $EspRoot ('config\smart-ring-eim-before-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.json')
        Copy-Item -LiteralPath $registry -Destination $prior
        # 已按固定 tag 全新克隆 SDK；fix 只准备这个目录的工具和版本专属环境。
        # 不再次对非空 SDK 执行 install，也不覆盖 6.1 的 profile / 配置文件。
        Invoke-Checked $eim @('fix', '--do-not-track', 'true', '--path', $sdk,
            '--esp-idf-json-path', (Join-Path $EspRoot 'tools'),
            '--tool-install-folder-name', (Join-Path $EspRoot 'tools'),
            '--tool-download-folder-name', (Join-Path $EspRoot 'dist'),
            '--python-env-folder-name', (Join-Path $EspRoot 'python_env'),
            '--activation-script-path-override', $EspRoot,
            '--config-file-save-path', (Join-Path $EspRoot 'config\smart-ring-idf-5.5.4.toml'),
            '--log-file', (Join-Path $EspRoot 'logs\smart-ring-idf-5.5.4.log'),
            '--mirror', 'https://dl.espressif.com/github_assets', '--idf-mirror', 'https://github.com',
            '--pypi-mirror', 'https://pypi.org/simple', '--target', 'esp32s3', '--idf-tools', 'cmake,ninja',
            '--skip-components-download', 'true', '--cleanup', 'false',
            '--install-all-prerequisites', 'false', '--version-name', 'v5.5.4',
            '--python-version-override', 'python311')
        & (Join-Path $helper 'sync_registry.ps1') -EspRoot $EspRoot -SdkPath $sdk -PriorRegistry $prior
        $sdkPython = Join-Path $EspRoot 'python_env\v5.5.4\venv\Scripts\python.exe'
        Invoke-Checked $sdkPython @('-c', 'import sys; assert sys.version_info[:3] == (3, 11, 15); print(sys.version)')
        Invoke-Checked $sdkPython @('-m', 'pip', 'check')
        Write-Output 'Sdk 安装检查完成；实际编译尚待验收。'
    }
    if ($Stage -in @('All', 'Sources')) {
        if (-not (Test-Path -LiteralPath $vendor)) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $vendor) -Force | Out-Null
            Invoke-Git @('clone', '--config', 'core.autocrlf=false', '--filter=blob:none', '--no-checkout', $manifest.vendor.repository, $vendor)
            Invoke-Git @('-C', $vendor, 'sparse-checkout', 'init', '--cone')
            Invoke-Git @('-C', $vendor, 'checkout', '--detach', $manifest.vendor.commit)
            Invoke-Git @('-C', $vendor, 'sparse-checkout', 'set', $manifest.vendor.project_directory)
        }
        Invoke-Checked $projectPython @((Join-Path $helper 'check_sources.py'), 'vendor', $vendor)
        Write-Output 'Sources 核对完成；工作副本、项目补丁、组件与编译随后验收。'
    }
}
finally {
    & $disable
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
}
