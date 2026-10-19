param([ValidateSet('All', 'Resolve', 'Sync', 'Preflight')][string]$Phase = 'All')
$ErrorActionPreference = 'Stop'
$hyRepo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
$hyRoot = Join-Path $hyRepo 'local/runtime/hy-memory'
$hyPython = Join-Path $hyRoot '.venv/Scripts/python.exe'
$hyLock = Join-Path $hyRoot 'requirements.lock'
$hyInput = Join-Path $PSScriptRoot 'requirements.in'
Push-Location -LiteralPath $hyRepo
try {
    if (-not (Test-Path -LiteralPath $hyRoot)) {
        New-Item -ItemType Directory -Path $hyRoot | Out-Null
    }
    if (-not (Test-Path -LiteralPath $hyPython)) {
        if ($Phase -eq 'Sync' -or $Phase -eq 'Preflight') { throw 'Dedicated interpreter missing.' }
        if (Test-Path -LiteralPath (Join-Path $hyRoot '.venv')) { throw 'Incomplete existing environment; inspect without deleting.' }
        uv venv --no-python-downloads --python 'D:\03-项目\01-正式项目\智慧圆屏\.venv\Scripts\python.exe' (Join-Path $hyRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Environment creation failed.' }
    }
    & $hyPython -X utf8 -B -c "import pathlib,sys; assert sys.version_info[:3] == (3,12,13); assert pathlib.Path(sys.prefix).resolve() == pathlib.Path(sys.argv[1]).resolve(); assert sys.prefix != sys.base_prefix" (Join-Path $hyRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Interpreter identity mismatch.' }
    if (($Phase -eq 'All' -or $Phase -eq 'Resolve') -and -not (Test-Path -LiteralPath $hyLock)) {
        uv pip compile $hyInput --python $hyPython --no-python-downloads --only-binary :all: --no-binary langdetect,jieba --generate-hashes --default-index https://pypi.org/simple --output-file $hyLock
        if ($LASTEXITCODE -ne 0) { throw 'Resolution failed; preserve evidence and stop.' }
    }
    if ($Phase -eq 'All' -or $Phase -eq 'Sync') {
        if (-not (Test-Path -LiteralPath $hyLock)) { throw 'Hash lock missing; resolve first.' }
        uv pip sync $hyLock --python $hyPython --no-python-downloads --require-hashes --only-binary :all: --no-binary langdetect,jieba --default-index https://pypi.org/simple
        if ($LASTEXITCODE -ne 0) { throw 'Sync failed; stop without changing sources or build scope.' }
    }
    if ($Phase -ne 'Resolve') {
        uv pip check --python $hyPython
        if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
        & $hyPython -X utf8 -B -c "import pathlib,sys; sys.path.insert(0,str(pathlib.Path.cwd()/'src')); from longmemory.methods.hy_memory.preflight import main; raise SystemExit(main(['--check-api']))"
        if ($LASTEXITCODE -ne 0) { throw 'Offline API preflight failed.' }
    }
    if (Test-Path -LiteralPath $hyLock) { Get-FileHash -Algorithm SHA256 -LiteralPath $hyLock }
} finally {
    Pop-Location
}
