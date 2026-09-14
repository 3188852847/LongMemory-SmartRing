# Hugging Face speech-to-speech 对 LongMemory 的参考评估

- 评估日期：2026-09-14
- 上游仓库：<https://github.com/huggingface/speech-to-speech>
- 结论：高价值架构参考；不整体替换当前 Xiaozhi 圆屏链路，不在本轮安装或下载模型。

## 已核实事实

该项目名称是 speech-to-speech，但当前主路径仍是模块化级联：`VAD → STT → LLM →
TTS`。四个组件由独立线程和队列连接，并通过 OpenAI Realtime 核心事件子集向外提供
WebSocket 与 WebRTC。STT、LLM 和 TTS 都可替换；LLM 支持 OpenAI 兼容接口。

默认语音组合使用 Parakeet TDT、远程兼容 LLM 和 Qwen3-TTS。仓库也支持 Whisper、
Faster Whisper、Paraformer、Kokoro、Pocket TTS、ChatTTS、OmniVoice 以及外部
OpenAI 兼容 TTS。支持列表不等于这些组合在本机 Windows 上都完成验证。

上游 NVIDIA 全本地快速路线明确面向 Linux，并建议为未量化 LLM、语音模型和缓存预留
约 24 GB 显存；本地语音加托管 LLM 的规划值约 8 GB 显存。项目当前电脑为 Windows、
RTX 4080 16 GB，因此不能直接照搬全本地命令。默认 Qwen3-TTS 配置还明确启用了
`non_streaming_mode=True`，不能仅凭采用 Qwen3-TTS 推断首声一定比现有 CosyVoice3 快。

## 最有价值的设计

### 1. 推测式结束判定

上游的 speculative turn 不是预测用户未来会说什么，而是在短静音后把当前话轮暂时视为
结束，提前启动 STT/LLM。用户在保护窗口内继续讲话时，同一话轮以新 revision 重开，
旧 revision 的 STT、LLM、TTS 和输出事件被丢弃。

其文档中的默认值包括 64 ms 最短静音和 800 ms speculative reopen 窗口，并可用
Smart Turn v3.2 根据内容与韵律判断话轮是否完整。当前 LongMemory 近讲严格档使用
700 ms 静音后才最终判停。若照搬低阈值而没有 revision、输出门和取消机制，会频繁抢答；
真正值得借鉴的是“先算、晚提交、可重开”的完整组合。

### 2. 代际取消与过期结果隔离

上游为每次生成分配 generation。用户插话后递增 generation，LLM/TTS 每个流式块检查
自己是否过期，发送端也拒绝旧 generation 的迟到音频。这与本项目现有 sentence ID
隔离方向一致，但上游把取消、队列清理和最终事件统一成一个生命周期，适合后续强化
预测预取和自然插话。

### 3. 统一实时事件边界

OpenAI Realtime 风格事件把语音开始/结束、增量转写、回答创建、音频 delta、工具调用、
取消和完成分开。它适合作为未来通用客户端协议参考，可以减少设备端与某个模型供应商的
绑定；当前 SmartRing-Plus 已经稳定使用 Xiaozhi 协议，不应为协议整洁而重做固件链路。

### 4. 播放缓冲与延迟口径

上游把 TTS 首包和扬声器播放缓冲分开，并说明 OpenAI 兼容 TTS 的本地客户端默认增加
196 ms 缓冲来抵抗首包后的抖动。LongMemory V5 也应继续区分服务端首包与真机出声，
不能把网络已发送当成扬声器已经播放。

## 与当前项目的关系

| 方面 | Hugging Face 项目 | LongMemory 当前 | 判断 |
|---|---|---|---|
| 研究主体 | 通用实时语音代理 | 长程记忆与陪伴助手 | 不能替换主体 |
| 主链路 | VAD→STT→LLM→TTS | 同为级联链路 | 架构可比较 |
| 设备协议 | OpenAI Realtime WS/WebRTC | Xiaozhi WS、MCP、圆屏控制 | 暂不迁移 |
| 长期记忆 | 对话上下文和外部工具接口 | L0–L3、来源、时态与审计 | 保留现有核心 |
| 结束判定 | 软结束、Smart Turn、revision 重开 | 700 ms 后一次性最终结束 | 最值得借鉴 |
| 取消 | generation 贯穿所有队列 | sentence ID、队列清理、协作取消 | 可渐进强化 |
| 默认 TTS | Qwen3-TTS，可替换 | CosyVoice3，可回退 | 不因框架更换模型 |
| 本机适配 | NVIDIA 主路线偏 Linux | Windows RTX 4080 16 GB | 直接接入成本高 |

## 决定与下一步

1. 不克隆、不安装、不替换 Xiaozhi、LongMemory 或 CosyVoice3。
2. 把 speculative endpointing 作为 V5 实测后的首要语音候选：先观察至少一批真实轮次的
   VAD 判停时间；如果它持续占据明显延迟，再设计带 revision 和输出门的影子实现。
3. 在影子阶段允许 STT/LLM 提前计算，但任何音频在话轮确认前不得发送；用户继续说话时
   必须丢弃旧 revision，不把两段话保存成两个 L0。
4. 借鉴 generation-tagged cancellation，统一未来预测预取、普通回答和插话的过期判断。
5. Qwen3-TTS、Parakeet TDT 和 Smart Turn 模型均作为独立候选；没有固定版本、本机环境、
   无缓存基准和音质听检前，不加入启动面板或日用默认。

## 主要上游资料

- 项目 README：<https://github.com/huggingface/speech-to-speech>
- Realtime Engine 架构：<https://github.com/huggingface/speech-to-speech/blob/main/src/speech_to_speech/api/openai_realtime/README.md>
- Qwen3-TTS 处理器：<https://github.com/huggingface/speech-to-speech/blob/main/src/speech_to_speech/TTS/qwen3_tts_handler.py>
- OpenAI 兼容 TTS：<https://github.com/huggingface/speech-to-speech/blob/main/docs/openai-compatible-tts.md>
