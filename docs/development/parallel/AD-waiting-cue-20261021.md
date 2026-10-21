# AD：降低等待提示频率与恢复答案首包观测

2026-10-21；软件候选，未部署或实机验收。代码提交
`b74a4057f73f71d08bae247df653906b46c4a092`，基于
`44d7bef64d7d3ef1343bdc8044dc238aa18b15b8`。
原AD分支的交付已被主会话另提交整合，不能直接快进；保留原分支，在同一隔离工作树从44d7创建
`codex/ad-waiting-cue-20261021`，没有reset、合并main或推送。

## 本轮目的与边界

所有者反馈几乎每轮先说“稍等”，希望等待反馈偶尔缓解长等待，不希望用固定提示冒充低延迟。
主会话授权先按3秒静默、90秒连接内跨轮冷却修复，并允许在合成复现后做最小发送观测修复。
没有切换buffered/adaptive、声线、模型、角色、ASR、固件或设备协议；没有生成/下载声音，
没有访问日用API、个人库或私人日志。规则与测试产物要求已核对，终端均显式指向AD工作树，
使用既有主项目Python3.12.13，不安装依赖。

## 最终等待策略

- 默认从本轮chat计时起静默3秒；Memory、模型、工具与TTS共用这一轮计时，不在每个阶段重开提示。
- 同一连接90秒内至多开始一条提示；不同连接不共享名额，不写任何偏好或私有配置。
- 同一轮只入队一次完整既有短句，保留当前已选声线缓存；缓存缺失/不匹配仍静默。
- 答案音频准备好、取消、旧轮、声线失配时抑制未发提示及尾帧。答案就绪指编码出的答案音频，
  不是LLM首字或文字完成。保留已有丢弃提示不占60ms调度槽的答案优先逻辑。
- 入队/首包预留不消费冷却。只有**这一包**的底层socket.send成功返回，才确认首包并开始90秒冷却。
  返回瞬间轮次已取消，已发送事实仍保留；取消前未发送、异常、丢弃或仅排队均不消费。
- 首包确认后的同一提示尾帧不会重置冷却起点；已发送后发现答案就绪时丢尾，不能撤回已进入网络的声音。

预算与预留保存在连接内，使用线程锁保护；Timer回调并发也只能入队一次。发送不持有线程锁跨await；
取消只释放自己的临时预留，旧轮finally不能释放新轮预留。实际旧包晚返回时仍按实际发送时刻更新冷却，
后续排队新提示会再次检查预算。计时全部为进程内单调时钟，不受系统日期变化影响。

## 首包缺失的合成定位

44d7中，上层observed_audio_sender看到AnswerPacket后将首包计时交给最终发送观察者；
但voice_interruption.sendAudio把它改包为普通_ControlPacket，下游不再识别答案/等待类别。
用固定vendor `eb4b28c59ed7ed885258498cf757ce14352d620e` 的发送/流控/清队列AST，
按已部署包装次序构建合成连接，复现：输入AnswerPacket，socket收到_ControlPacket；实际发送1帧，
audio_dispatch_ms=0、answer_send_returned=1，而first_audio_sent_ms与first_answer_ms均null。
这证明一条确定的软件遗漏；没有据此把主会话的每个私人样本归为同一原因。

最小修复保留WaitingPacket/AnswerPacket类别、原取消条件、原始输出租约和字节；
不以dispatch、入队或共享packet_count增量作为发送成功。
每包新增轻量进程内receipt对象，保护封包传递同一对象；实际raw.send任务成功返回才确认。
等待音只记first_feedback_ms，答案才记first_answer_ms/first_audio_sent_ms。
这些属性不进入二进制或JSON协议，不改已有状态接口版本、epoch范围、代际或设备回执语义。

真实随机环回还复现：提示早期通过过滤后堵在发送门前，答案已就绪，旧提示仍会出门。
按主会话授权，在原门内有效性检查上叠加该包原取消回调；先保留原lease验证，再检查回调，
异常按失效处理。重入packet scope保留原revocation/input/turn身份；未改原发送门锁、超时或关闭策略。

## 实际验证

核心回归命令（工作目录为AD，解释器为主项目既有.venv，均加`-B -X utf8`）：

```text
python -m pytest tests/unit/development/test_voice_waiting_policy.py tests/unit/development/test_voice_output_protocol_ws.py tests/unit/development/test_voice_interruption.py tests/unit/development/test_voice_waiting_cache.py tests/unit/development/test_voice_waiting_handoff.py tests/unit/development/test_voice_latency.py tests/unit/development/test_cosyvoice_streaming.py tests/unit/development/test_device_control.py tests/unit/development/test_ad_cosy_continuity.py tests/unit/development/test_voice_interruption_opus.py tests/unit/development/test_voice_completion_executor.py tests/integration/memory_pipeline/test_voice_completion_revocation.py tests/unit/development/test_advanced_voice_bootstrap.py -q
```

结果：**218 passed、3 skipped，29.40秒**。3个跳过项要求显式绑定native仓库，不自动安装或访问。
`git diff --check`通过。本文未登记共享manifest，单文件strict检查为unlisted-document/unknown-selection，
实际选中文档数0，不能据此声称正文检查通过；按文件归属留ROOT整合登记。测试包括：

- 0.9/2.999秒静默、3秒边界、8个Timer线程并发、每轮一次、90秒边界与不同连接隔离。
- 取消/旧轮/答案就绪/未实际发送/发送异常不消费；已实际发送后立即取消仍消费；旧预留不能改新预留。
- 共享flow计数增加但本包未发送的cue/answer负例，均不产生本包首发或冷却记录。
- 完整vendor+观测+等待+保护封包次序：提示只记反馈，答案在实际发送后记首包；合成时钟例中
  反馈为3000ms、答案为3300ms，等待尾帧被抑制。
- 真实环回WS同时覆盖已协商v1和legacy的逐包事实、未发提示不消费、底层发送失败不标答案，
  以及等待门前答案就绪、取消发生在实际write之后的负例。
- 原有阻塞发送取消、超时/关闭、旧EOS/残音打断、hello能力兼容、Opus调度、完成归档和启动组合回归。

测试范围澄清：门前等待提示在答案就绪后被抑制的新增真实环回负例使用已协商v1；
legacy新增的是成功发送receipt正例，不能据此宣称legacy门前取消竞争已覆盖。
主会话随后转达AI独立审查：legacy路径在门内直接_write，缺少v1相同的取消重查，
由AI在整合树负责最小复核与负例。本AD代码保持`b74a4057`冻结，不重叠修改或重复实现。
此前218 passed、3 skipped为所选测试的事实，不是对这个尚未覆盖负例的通过声明。

原测试中1秒正例改为3秒正例；原“已排队提示尾包交接”夹具显式delay=0，只隔离调度机制，
不改变产品默认。合成传输替身在自己的实际发送成功点确认receipt，不能只递增共享计数。

## 对日用时延的结论限制

以下由主会话提供，本会话没有读取私人server.log：17:55:27后的12个audio_ready样本
1.662–5.227秒、中位3.355秒；11个模型首输出203–705ms、中位358ms，缺first_audio_sent。
最近一轮metadata为memory_ready38、llm_requested38、llm_first_output366、tts_started470、
audio_ready4348、response_completed575ms，TTS两段3937/3855ms，输入VAD614/ASR1ms。
这些是不同问题/取消混合数据，不能算新版相对旧版的降幅；模型首字不等于有效答案声音。

本轮减少的是提示频率，并恢复答案**发送返回**的观测完整性，没有缩短模型或TTS计算。
receipt只证明应用层write返回，不能证明设备接收/播放、首帧有声或用户听到首个有效词。
应由ROOT安排AI审查与组合部署，再用可比条件采集新首包数据；本地fixture通过不替代真实体验验收。
