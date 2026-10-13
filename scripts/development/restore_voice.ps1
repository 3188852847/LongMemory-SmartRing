param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Sources', 'Environments', 'Models', 'Tools')]
    [string]$Stage
)

# 本脚本仅由所有者显式运行；助手不执行安装、克隆或下载阶段。
# 不加载机器代理、不改持久 PATH、不启动服务，不恢复旧备份的外部文件。
$ErrorActionPreference = 'Stop'
$voiceProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$voiceResourceRoot = Join-Path $voiceProjectRoot 'local\runtime'
$xiaozhiRepository = Join-Path $voiceResourceRoot 'xiaozhi-esp32-server'
$xiaozhiServiceRoot = Join-Path $xiaozhiRepository 'main\xiaozhi-server'
$cosyRepository = Join-Path $voiceResourceRoot 'CosyVoice'
$voiceDeclarations = Join-Path $PSScriptRoot 'voice_restore'
$sourcePins = Get-Content -LiteralPath (Join-Path $voiceDeclarations 'assets.json') -Raw -Encoding UTF8 | ConvertFrom-Json

function Invoke-VoiceCommand {
    param([string]$Command, [string[]]$ArgumentList)
    & $Command @ArgumentList | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "命令失败（退出码 $LASTEXITCODE），本阶段已停止：$Command"
    }
}

function Test-VoiceSource {
    param([string]$Directory, [string]$Revision)
    if (-not (Test-Path -LiteralPath (Join-Path $Directory '.git'))) {
        throw "缺少新下载的 Git 源码：$Directory；请先完成 Sources 阶段。"
    }
    $head = & git -C $Directory rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $head.Trim() -ne $Revision) {
        throw "源码版本与恢复清单不一致：$Directory；未重置或覆盖。"
    }
}

function Get-VoiceSource {
    param([string]$Url, [string]$Directory, [string]$Revision)
    if (-not (Test-Path -LiteralPath $Directory)) {
        Invoke-VoiceCommand -Command git -ArgumentList @('clone', '--config', 'core.autocrlf=false', '--config', 'core.longpaths=true', '--filter=blob:none', '--no-checkout', $Url, $Directory)
        Invoke-VoiceCommand -Command git -ArgumentList @('-C', $Directory, 'checkout', '--detach', $Revision)
    }
    Test-VoiceSource -Directory $Directory -Revision $Revision
}

function Get-VoicePython {
    param([string]$Directory)
    $environment = Join-Path $Directory '.venv'
    $python = Join-Path $environment 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $environment)) {
        Invoke-VoiceCommand -Command uv -ArgumentList @('venv', $environment, '--python', '3.10.20', '--seed')
    }
    if (-not (Test-Path -LiteralPath $python)) {
        throw "已有环境不完整：$environment；未覆盖，请反馈错误。"
    }
    $version = & $python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
    if ($LASTEXITCODE -ne 0 -or $version.Trim() -ne '3.10.20') {
        throw "语音环境不是 Python 3.10.20：$environment；未替换。"
    }
    return $python
}

if ($Stage -eq 'Sources') {
    [IO.Directory]::CreateDirectory($voiceResourceRoot) | Out-Null
    Get-VoiceSource -Url 'https://github.com/xinnan-tech/xiaozhi-esp32-server.git' -Directory $xiaozhiRepository -Revision $sourcePins.sources.xiaozhi
    Get-VoiceSource -Url 'https://github.com/QwenAudio/CosyVoice.git' -Directory $cosyRepository -Revision $sourcePins.sources.cosyvoice
    Invoke-VoiceCommand -Command git -ArgumentList @('-C', $cosyRepository, '-c', 'core.autocrlf=false', 'submodule', 'update', '--init', '--recursive')
    Test-VoiceSource -Directory (Join-Path $cosyRepository 'third_party\Matcha-TTS') -Revision $sourcePins.sources.matcha
}
elseif ($Stage -eq 'Environments') {
    Test-VoiceSource -Directory $xiaozhiRepository -Revision $sourcePins.sources.xiaozhi
    Test-VoiceSource -Directory $cosyRepository -Revision $sourcePins.sources.cosyvoice
    Invoke-VoiceCommand -Command uv -ArgumentList @('python', 'install', '3.10.20')
    $xiaozhiPython = Get-VoicePython -Directory $xiaozhiServiceRoot
    Invoke-VoiceCommand -Command uv -ArgumentList @('pip', 'install', '--python', $xiaozhiPython, '-r', (Join-Path $voiceDeclarations 'xiaozhi.requirements.txt'))
    Invoke-VoiceCommand -Command uv -ArgumentList @('pip', 'check', '--python', $xiaozhiPython)
    $cosyPython = Get-VoicePython -Directory $cosyRepository
    Invoke-VoiceCommand -Command uv -ArgumentList @('pip', 'install', '--python', $cosyPython, '--index-url', 'https://download.pytorch.org/whl/cu121', 'torch==2.3.1+cu121', 'torchaudio==2.3.1+cu121')
    # 旧 Whisper 的 setup 导入 pkg_resources。运行包版本表不会约束 uv 的
    # 临时构建环境，因此单独固定构建工具，继续保留隔离构建。
    Invoke-VoiceCommand -Command uv -ArgumentList @('pip', 'install', '--python', $cosyPython, '--build-constraints', (Join-Path $voiceDeclarations 'cosyvoice.build.txt'), '-c', (Join-Path $voiceDeclarations 'cosyvoice.torch.txt'), '-r', (Join-Path $voiceDeclarations 'cosyvoice.requirements.txt'))
    Invoke-VoiceCommand -Command uv -ArgumentList @('pip', 'check', '--python', $cosyPython)
}
else {
    Test-VoiceSource -Directory $xiaozhiRepository -Revision $sourcePins.sources.xiaozhi
    Test-VoiceSource -Directory $cosyRepository -Revision $sourcePins.sources.cosyvoice
    $projectPython = Join-Path $voiceProjectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $projectPython)) {
        throw '缺少已恢复的主项目 Python 环境。'
    }
    Invoke-VoiceCommand -Command $projectPython -ArgumentList @((Join-Path $voiceDeclarations 'prepare_assets.py'), '--group', $Stage.ToLowerInvariant())
}
Write-Host "$Stage 阶段完成；安装和下载不代表语音运行验收已通过。"
