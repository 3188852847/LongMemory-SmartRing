[CmdletBinding()]
param(
    [string]$Source = 'D:\Dev\esp-projects\smart-ring\otto0014',
    [string]$Build = 'D:\Dev\esp-projects\smart-ring\build-otto0014'
)
$ErrorActionPreference = 'Stop'
foreach ($path in @($Source, $Build)) {
    if (-not [IO.Path]::IsPathRooted($path) -or $path -match '[^\x21-\x7E]' -or $path -match '[()]') {
        throw 'Only ASCII absolute source/build paths are accepted.'
    }
}
if (Test-Path -LiteralPath $Build) { throw 'A clean, nonexistent build directory is required.' }
$sdk = 'D:\Dev\esp\v5.5.4\esp-idf'
if ((& git -C $sdk rev-parse HEAD) -ne '735507283d5b2f9fb363a1901172dbd9e847945d') { throw 'SDK mismatch.' }
. 'D:\Dev\esp\Microsoft.v5.5.4.PowerShell_profile.ps1'
$python = 'D:\Dev\esp\python_env\v5.5.4\venv\Scripts\python.exe'
$env:PYTHONUTF8 = '1'
$env:IDF_CCACHE_ENABLE = '0'
$env:PYTHONPATH = (Join-Path $PSScriptRoot 'offline_python') + [IO.Path]::PathSeparator + $env:PYTHONPATH
$env:IDF_COMPONENT_CACHE_PATH = 'D:\Dev\esp-projects\smart-ring\cache\components'
Set-Location -LiteralPath $Source
& $python (Join-Path $sdk 'tools\idf.py') -B $Build '-DIDF_TARGET=esp32s3' '-DCCACHE_ENABLE=0' reconfigure
if ($LASTEXITCODE -ne 0) { throw 'Offline configure failed; retain evidence, do not fetch dependencies.' }
& ninja.exe -C $Build -j 4 all
if ($LASTEXITCODE -ne 0) { throw 'Build failed; preserve directory.' }
