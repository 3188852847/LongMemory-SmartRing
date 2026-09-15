# 固定等待音频

公开合成短句“我想一下。”“我查一下。”，由本机既有 CosyVoice3 服务生成，
沿用日用声线，不包含用户对话或个人记忆。生成日期：2026-09-15。

`cosyvoice3/` 保存 16kHz、24kHz 单声道、60ms Opus 帧。文件以 `LMWAIT01`
开头，后续每帧为两字节大端长度及 Opus 数据。普通提示17帧（1020ms），
查询提示18帧（1080ms）。这是编码可播放时长，不是生成延迟。

生成入口：`scripts/development/xiaozhi/prepare_voice_waiting.py`，必须显式指定
`--prepare --server-dir`，仅使用已有本机服务和依赖，不覆盖已有资产。
这四份资产是版本化的公开固定素材，不是原始个人录音。
