# AI：EOS 后既有 VAD 阳性的撤权缺口

2026-10-22。基线 `365e53f3a222a7b8cf3a52f3635cb86cad0af114`，分支 `codex/ai-input-interruption-audit-20261022`，实现提交 `4321e740c23034e63313223b97d713d7e518c343`。ROOT 明确转交本次最小输入撤权修复；仅改 [voice_interruption.py](../../../scripts/development/xiaozhi/voice_interruption.py) 与[定向回环测试](../../../tests/unit/development/test_voice_eos_vad_control.py)，本记录和清单另交。不改 AD 发送文件、输出协议、DSP/VAD/ASR模型或阈值，不操作日用、串口或录音，不合主/推送。

## 已有证据与归因范围

AD 封存记录为其工作树忽略路径 `data/test-tmp/ad-buffered-label-observe-20261022-01/sealed-review.json`，SHA256 `3ee0f0afdc72cdf918cbc5af5e6960cc9f69d5f1e1faaecb5272d2ec76099bca`；`samples.jsonl` 为 `a4a69240783d3df8f788e871e0fb16c7817ccc2aef27ae2fdd4dbf5ba6a31be7`。AI 独立核对摘要及120行。它是 buffered 约120秒背景观测，所有者实机反馈仍未通过；没有口令标记、精确语音窗口、同连接原子证明或播放ACK（确认回执）。诊断API v2、Cosy流接口版本和设备音频头版本必须区分；未保存握手，不凭API版本证明音频头或线上标签唯一。

整轮尾计数有87次VAD阳性、3次非空ASR和2次abort，不能说全程未识别/未撤权。22:17:28和22:17:44的abort只能归为背景相邻采样事件，不能绑定用户插话。speaking分组的1次阳性/698次阴性只按服务器标志分组，不证明设备当时的声学播放或实际口令归属。AEC能量比例也不能直接当近端损失率。

复用既有 `voice_input_interruption_probe`、输入观测测试及 `test_voice_output_protocol_ws.py` 发现覆盖缺口：基础VAD快速abort、唤醒丢弃、ASR交接和显式EOS后interrupt已有测试；缺少**EOS后服务器speaking已清除，但协议仍保有未撤销输出身份时，单次VAD阳性直接撤权**的组合。

AI 用既有固定上游及真实回环夹具复现：原实现EOS后 `server_speaking=false`、协议目标仍有效，注入一次VAD阳性后进入ASR接收，但 `interrupt_sent=0`；消费者合同预言机保留一份合成尾包。基线收据为本树忽略路径 `data/test-tmp/ai-input-control-eos-baseline-20261022-01.json`，SHA256 `8bd631f828740bfbb969dd6a7df5645a84442e5d38c556d52f57d57002259626`。这个队列是合成消费者，不是读取设备队列；也没有声学VAD或ASR验收。

历史成功节点 `2b58cb5d78693605d8b8f309fe30e71fbdcc65e1` 与当前基线的 `voice_interruption.py` 同为 Git blob `400cfb3516cf3a04e2a1a18998bd954750edaed4`。因此本次是既存遗漏，不能写成后续核心改坏的引入点，也不能据此推翻历史成功或宣称查明本次现场失败。0016历史源码另有演进，本记录不把所有历史文件概括成同blob。

## 最小修复

输入处理入口捕获本包开始时的协议对象和EOS输出身份。沿固定上游原 `handleAudioMessage` 执行一次VAD，仍先经过唤醒忽略和原speaking快速abort；在其既有 `no_voice_close_connect(connection, have_voice)` 接缝复用该结果，不新增VAD推理、不改上游函数正文或ASR提供器方法。

只有本地Cosy、服务端AEC、非manual、服务器speaking已为false且EOS目标有效时才捕获目标。进入接缝后，必须原协议/原目标仍是当前、尚未撤销，AEC及模式仍允许，且已有VAD结果严格为True，才调用既有abort路径。原speaking路径已经abort、目标替换、已撤销或模式改变时不重复撤权。单包上下文在返回/异常/取消后复位，处理模块和ASR模块的别名均保留既有包装。

正常返回路径中，结束提示与持久会话的既有接缝按原顺序继续调用一次；不修改它们的正文、返回值或异常。撤权若异常或取消则原样传播，不继续ASR，沿用原快速abort的控制语义。既有撤权和输出门负责捕获/发送旧epoch的interrupt。没有新增播放ACK、按任意秒数延长speaking、推断硬件尾音时长或取消新轮的策略。EOS身份仍有效不等于硬件仍在播放；修复只撤销该输出身份，不能保证现场识别成功。

## 验证与冻结交付

新增测试复用原固定SDK `eb4b28c59ed7ed885258498cf757ce14352d620e`、实际撤权/输出代理、结束提示/持久会话包装与随机回环WebSocket。注入VAD及ASR接收边界仅证明控制流。覆盖：interrupt在ASR接收前返回、VAD每包只一次、重复输入幂等、正常speaking旧快速路径不双撤权、无目标空闲/已撤销/manual/无AEC/VAD阴性、等待中模式变化、目标被新轮替换、迟到旧包不进入新轮、两份新轮包完整到达、取消等待保持原合同。

唤醒测试执行原恢复函数，睡眠替身核对其请求2秒并控制释放；证明忽略支路/恢复次序，不冒充实测设备两秒。listen测试调用固定上游真实处理方法及reset，核对普通缓冲清空、原RNN/context保留且旧租约不会复活。消费者清队列是合同预言机，不是硬件flush证明。

最终七份相关测试文件（EOS定向、撤权、真实WebSocket、输入观测/装配、ASR预取、直连v2）**92 passed，27.07秒，零失败/错误/跳过**。使用本树源码，父进程为既有Python3.12.13，回环为既有语音Python3.10.20；无模型/GPU、日用端口或网络资源获取。JUnit为本树忽略路径 `data/test-tmp/ai-eos-vad-key-20261022-02.xml`，SHA256 `7c6cb47b2babe638d82937063fe637a31f3d7818048be4230c26ef08ed5c8874`，其中properties保存合成控制报告。

生产源码SHA256 `fbd571deaa273c0abeae22d4633fec839d4f69e71506add081ee6d3e12f7aee6`；定向测试 `67c187a64579f000638bc20b16c58b56eef9e60f467f653edc34eef9ae904f49`。冻结清单为本树忽略路径 `data/test-tmp/ai-eos-vad-freeze-20261022-01.json`，SHA256 `2646b134e8ae903deed6a9fffdce3474302d169da473909cdc1621d0c8a6f3ea`，明确绑定实现提交及基线复现/最终JUnit。实现先冻结交ROOT安排AD独立审查，本记录不代替其结论。

初次测试失败收据保留：`ai-eos-vad-first-20261022-01.xml` 为复用driver经命令行超过Windows长度限制，改成隔离临时文件执行；02/03为测试前提误认“新start会多发interrupt/直接置speaking”，按真实Turn.current及send_stt_message源码纠正夹具。未为这些前提改生产输出逻辑。04定向通过；首轮组合92项通过后，再补等待中manual/AEC变化复核，最终92项按上述收据为准。

窄记录登记及严格文档/空白检查通过。远程CI、正式发布、重启和所有者实机均未在本候选验收。既有发送前缓存、生命周期、DSP误判以及现场说话期间的识别问题仍未解决，不能把本修复宣传成所有者打断问题已经恢复。
