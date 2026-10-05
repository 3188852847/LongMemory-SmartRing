param(
    [string]$IdfPath = 'D:\LongMemory-local\tools\Espressif\.espressif\v5.5.4\esp-idf',
    [string]$ToolsPath = 'C:\Espressif\tools'
)
$ErrorActionPreference = 'Stop'
# 复制到新的英文临时路径，避开 Windows 下 SDK 对中文构建路径的兼容问题。
# 不删除已有目录；不运行 flash/erase/monitor，不修改 EIM 全局版本选择。
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$stageRoot = Join-Path ([IO.Path]::GetTempPath()) ('axp-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
if (Test-Path -LiteralPath $stageRoot) { throw 'Staging directory already exists; retry with a new name.' }
if ($stageRoot -match '[^\x00-\x7F]') { throw 'TEMP must be an ASCII path for this build.' }
$sourceRoot = Join-Path $stageRoot 'app'
$testRoot = Join-Path $stageRoot 'tests'
New-Item -ItemType Directory -Path $sourceRoot, $testRoot | Out-Null
foreach ($item in @('CMakeLists.txt', 'sdkconfig.defaults', 'main')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $item) -Destination $sourceRoot -Recurse
}
Copy-Item -LiteralPath (Join-Path $repoRoot 'tests\firmware\axp2101_decode_test.cpp') -Destination $testRoot

# 仅使用已安装的 SDK 5.5.4 与工具；不自动下载依赖或更改用户安装。
$pythonExe = Join-Path $ToolsPath 'python\v5.5.4\venv\Scripts\python.exe'
$toolBins = @('python\v5.5.4\venv\Scripts', 'cmake\3.30.2\bin', 'ninja\1.12.1',
              'xtensa-esp-elf\esp-14.2.0_20260121\xtensa-esp-elf\bin')
$variables = @{
    IDF_PATH = $IdfPath
    IDF_TOOLS_PATH = $ToolsPath
    IDF_PYTHON_ENV_PATH = (Join-Path $ToolsPath 'python\v5.5.4\venv')
    ESP_ROM_ELF_DIR = (Join-Path $ToolsPath 'esp-rom-elfs\20241011')
    IDF_COMPONENT_MANAGER = '0'
    IDF_CCACHE_ENABLE = '0'
    PYTHONNOUSERSITE = '1'
    PATH = (($toolBins | ForEach-Object { Join-Path $ToolsPath $_ }) -join ';') + ';' + $env:PATH
}
$previous = @{}
try {
    foreach ($name in $variables.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $variables[$name], 'Process')
    }
    Write-Host "Staged source: $sourceRoot"
    $testSource = Join-Path $testRoot 'axp2101_decode_test.cpp'
    & $pythonExe (Join-Path $IdfPath 'tools\idf.py') -C $sourceRoot "-DAXP_TEST_SOURCE=$testSource" build
    if ($LASTEXITCODE -ne 0) { throw "ESP-IDF build failed ($LASTEXITCODE); staging retained: $stageRoot" }
    Get-FileHash -LiteralPath (Join-Path $sourceRoot 'build\axp2101_readonly.bin') -Algorithm SHA256
    Write-Host "Build passed. No device accessed. Artifacts: $sourceRoot\build"
} finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
}
