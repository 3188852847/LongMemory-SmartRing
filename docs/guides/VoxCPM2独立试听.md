# VoxCPM2 独立试听

2026-09-04：用户提供两个官方权重，已复制并校验 SHA256 一致；独立依赖尚未安装完成，未生成音频。G 盘原件保留。

2026-09-05：独立依赖安装完成，CUDA 与模型加载通过。发现 PyPI 2.0.3 不接受官方 main 分支示例中的 `seed` 参数，试听脚本已按已安装版本签名调整；此处固定 PyTorch 随机源但不宣称跨环境完全确定。

同日首次本地试听成功：RTX 4080 上模型加载约 9.71 秒，峰值分配显存 5,723,260,928 字节；默认样本生成 5.28 秒音频耗时约 6.32 秒，风格样本生成 5.60 秒音频耗时约 5.62 秒，均为 48 kHz。WAV 已检查为有限、非静音采样。上述是一次冷启动后的整段合成实测，不是流式首包、圆屏端到端性能或质量结论。

2026-09-05：已新增可替换 TTS 适配层。本机常驻服务通过与小智 `CustomTTS` 相同的请求完成真实合成，返回 48 kHz、单声道、16 位、2.88 秒有效 WAV；请求后服务已停止。当前真实小智配置仍是 EdgeTTS，没有自动切换，尚不代表圆屏集成完成。

本阶段不做克隆、训练或任意参考音频上传。当前目标是让默认 `plain` 参数经小智在圆屏播放，并记录主观听感与首句等待；通过后再决定是否投入流式合成。

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

## 用统一启动面板接入圆屏

当前推荐通过根目录 `Start.cmd` 操作，不需要另开 VoxCPM2 终端：

1. 停止旧启动面板及手动运行的小智；正在运行时不能安全切换配置。
2. 双击 `Start.cmd`，勾选“同时启动圆屏语音”。
3. 在“圆屏声音”选择 `VoxCPM2（本地 plain）`，点击“检查并同步”。确认后只修改小智 TTS 选择与固定本机接口字段，在小智私有目录生成备份；不会启动服务。
4. 核对局域网 IP、日常数据库和风险提示，再点击“启动”。面板依次托管控制台、VoxCPM2 和小智；小智等待模型健康检查后才启动。
5. 等面板显示 VoxCPM2 与语音进程运行中，再唤醒圆屏试听。首次加载会校验约 4.6 GB 权重并载入显卡，不能以控制台先打开判断语音已经就绪。
6. 结束聊天后点击“停止服务”，VoxCPM2 随本面板进程树退出并释放显存。

回退时停止服务，在同一位置选择 `EdgeTTS（联网标准音色）`，点击“检查并同步”，再重新启动。配置写入成功只证明磁盘状态；圆屏实际声音仍以重启后的试听为准。

当前 React“声音设置”只管理 Edge 标准音色；选择 VoxCPM2 时不应用该页面保存操作。后续会把后端与各自参数统一展示。

## 成本与回退

模型约 5 GB，GPU PyTorch wheel 约 3.2 GiB，安装展开及其他依赖另计。首次实测显卡是 RTX 4080、总显存 16376 MiB；空闲显存会变化。请避免同时运行其他大型 GPU 模型。第一版是整句非流式服务，长句首包可能明显慢于 Edge；小智失败重试仍可能放大成本，因此配置使用 90 秒超时并由服务限制并发。

如果下载失败，不反复换源或重装主环境。可从 [官方模型文件页](https://huggingface.co/openbmb/VoxCPM2/tree/32279effe8c19989596f05d353d1447f51d9e915) 下载该版本全部文件，按目录原样放入 `data/models/VoxCPM2/32279effe8c19989596f05d353d1447f51d9e915/`。

参考：[官方代码](https://github.com/OpenBMB/VoxCPM)、[快速开始](https://voxcpm.readthedocs.io/en/latest/quickstart.html)。不需要运行官方 Gradio WebUI，避免额外下载转录模型。
