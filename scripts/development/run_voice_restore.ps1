param(
    [Parameter(Mandatory = $true)]
    [string]$ProxyScript,
    [switch]$Resume
)

# 机器代理位置由调用者传入，项目不固定本机地址或修改永久配置。
# 点源加载、阶段执行与清理均在同一进程、同一脚本作用域中完成。
$ErrorActionPreference = 'Stop'
. $ProxyScript
$enableVoiceProxy = Get-Command Enable-DevProxy -CommandType Function -ErrorAction Stop
$disableVoiceProxy = Get-Command Disable-DevProxy -CommandType Function -ErrorAction Stop
$voiceStages = @('Sources', 'Environments', 'Models', 'Tools')
if ($Resume) {
    $voiceStages = @('Environments', 'Models', 'Tools')
}
try {
    & $enableVoiceProxy
    foreach ($voiceStage in $voiceStages) {
        & (Join-Path $PSScriptRoot 'restore_voice.ps1') -Stage $voiceStage
    }
} finally {
    & $disableVoiceProxy
}
