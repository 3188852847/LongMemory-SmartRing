# VoxCPM2 独立试听

2026-09-04：用户提供两个官方权重，已复制并校验 SHA256 一致；独立依赖尚未安装完成，未生成音频。G 盘原件保留。

本阶段只尝试本地声音，不替换 Edge TTS、不改小智配置、不开新服务端口、不做克隆或训练。验收目标：GPU 能加载模型、固定文本生成有效 WAV、用户能试听；听感好坏由用户判断。尚不代表圆屏集成完成。

## 文件归属

- `scripts/development/voxcpm/`：独立依赖声明、锁文件与试听脚本。
- 其下 `.venv/`：专用 Python 环境，不使用主项目 CPU 版 PyTorch。
- `data/models/VoxCPM2/`：官方固定版本模型，忽略 Git。
- `data/audio/voxcpm-随机编号/`：每次独立试听的音频和耗时报告，忽略 Git，不覆盖旧结果。

## 再次运行

PowerShell 中复制以下命令。首次同步需要联网下载依赖；已有环境使用 `--locked` 保持版本。

```powershell
Set-Location 'D:\02-项目\LongMemory-SmartRing\scripts\development\voxcpm'
uv sync --locked --python 3.11
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe trial.py download
.\.venv\Scripts\python.exe trial.py verify
.\.venv\Scripts\python.exe trial.py generate
```

`download` 只下载官方固定快照，不读取 Hugging Face 登录令牌；`generate` 只从本地加载，关闭自动联网、去噪、文本规范化和编译优化。生成时使用显卡，完成退出后释放模型占用。

终端最后打印试听目录，打开 `plain.wav` 与 `gentle.wav`。两段文本相同，后一段增加声音风格描述，不保证每句都遵从。报告区分加载时间、整段生成时间与音频时长；这不是首包延迟，也不是完整聊天延迟。

## 成本与回退

模型约 5 GB，GPU PyTorch wheel 约 3.2 GiB，安装展开及其他依赖另计。首次实测显卡是 RTX 4080、总显存 16376 MiB；空闲显存会变化。请避免同时运行其他大型 GPU 模型。

如果下载失败，不反复换源或重装主环境。可从 [官方模型文件页](https://huggingface.co/openbmb/VoxCPM2/tree/32279effe8c19989596f05d353d1447f51d9e915) 下载该版本全部文件，按目录原样放入 `data/models/VoxCPM2/32279effe8c19989596f05d353d1447f51d9e915/`。

参考：[官方代码](https://github.com/OpenBMB/VoxCPM)、[快速开始](https://voxcpm.readthedocs.io/en/latest/quickstart.html)。不需要运行官方 Gradio WebUI，避免额外下载转录模型。
