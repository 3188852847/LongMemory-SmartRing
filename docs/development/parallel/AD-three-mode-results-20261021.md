# AD：当前声线三模式窗口解释与模式建议

日期：2026-10-21。只读评审窗口 `AD-CURRENT-VOICE-20261021-01`，
候选 `116047ebe61db3558126dc8e9fd229afe076b63d`，外部源码 `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`。
AD当前分支 `codex/ad-three-mode-driver-20261021`；本轮只新增本记录，不改AI文件、不操作服务、不重测或加载模型。

## 技术结论

**支持ROOT提出的受控adaptive日用切换，本次摘要未见技术阻断。**
这是一项结合缓冲策略、当前声线实测及直接取消/复用证据的工程选择，不是证明adaptive普遍快于其他模式。
ROOT完成其独立GPU/监听、日用所有权与保护数据核对后，可按已授权范围执行切换；AD没有执行该切换。
真机首字、声音、较长回复连续性和打断体验仍由日用验证确认，不能把本窗口说成已验收这些体验。

依据仅为以下两份指定摘要，没有读取其他运行产物、音频或声线档案：

- [驱动摘要](D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ai-integration-review-20261021/experiments/results/ai-current-voice-20261021-01/driver/summary.jsonl)
- [整窗摘要](D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ai-integration-review-20261021/experiments/results/ai-current-voice-20261021-01/window-summary.jsonl)

本次读取字节SHA256分别为 `86d5b10d31dea94a9f1d226b4eeaa0ae5bc1ad0b6974344c1c20825af6decfc2`
及 `7fa08926a3a146d08e6381230f926f63ff477a48e413abf5b217f7cfb1d8f5de`，用于区分后续产物变化。

## 完整性、预算与身份

整窗摘要记录加载前阶段、默认热身2.141秒、选中声线热身1.812秒，随后服务就绪、driver_complete，
最后自有进程树退出确认及事件读流退出为true；总墙钟83.078秒，低于300秒。
ROOT报告进程exit0；这两份摘要没有独立退出码字段，本会话独立核对的是上述完成/退出标记。

调用账本为2次热身+12次正式测量+1次取消+1次复用=16。
14条operation_complete是**13次完整音频（12测量+1复用）及1次预期取消**，不能写成14次完整音频。
完整音频均EOS=true，采样数、帧数和尾部补齐量相容；取消EOS=false为预期。
最大operation_total为3101.1ms，均未触及15秒单次上限；没有failed/stopped事件或补跑记录。

service_ready报告显式主项目profile_root、当前声线身份未变、incremental_usable=true；
全部14行均 voice_identity_unchanged/server_idle_after/owned_socket_watcher_stopped=true。
驱动与模型自有进程清理均有确认；桌面背景仍为共享WDDM，摘要不是物理GPU独占或最终资源复核证据。
摘要主动不保存档案身份值；本会话没有重读档案来重新计算摘要。

## 按文本列出观测，不计算推广比例

T0=`下午的阳光落在窗边。`；T1=`我们可以先整理桌面，再慢慢安排接下来的事情。`。
每组仅2次，均为cache=false，正逆序重复，HTTP接口无法按请求控制seed。
下表为这两次的范围，单位秒，保留三位小数；client_total是客户端本段生成/接收/编码返回，
不是设备播完时间，也不包含整轮记忆/LLM等待。

| 文本 | 模式 | 首能量帧可用代理 | client_total | 生成PCM音频时长 |
|---|---|---:|---:|---:|
| T0 | buffered | 1.448～2.118 | 1.507～2.203 | 2.120～2.640 |
| T0 | incremental | 1.430～1.599 | 1.795～2.031 | 2.240～2.320 |
| T0 | adaptive | 1.480～1.513 | 1.994～2.055 | 2.360～2.520 |
| T1 | buffered | 2.321～2.324 | 2.429～2.469 | 3.840～3.840 |
| T1 | incremental | 1.387～1.454 | 2.915～3.047 | 3.960～4.080 |
| T1 | adaptive | 1.494～1.545 | 2.935～3.079 | 3.840～4.000 |

T1两次增量路径的首能量代理均早于buffered，但完整合成返回更晚。
T0第二次buffered首能量1447.6ms，早于该轮adaptive1513.4ms；因此不能概括成每次提速。
同文本各次音频时长也不同，不能视为同波形重放或逐种子配对；不计算可推广的精确提速百分比、P95或因果效应。

粗阶段诊断支持“增量有额外分块计算成本”这一方向：
buffered每次Flow/HiFT各1次；incremental/adaptive在T0各2次、T1各3次。
例如T1 buffered Flow墙钟约263～296ms，增量两模式约1108～1133ms。
这些墙钟阶段可与语音token线程重叠，未新增CUDA同步，不能相加当作纯GPU耗时，
也不能据此唯一归因本轮或此前日用3.9～4.1秒等待。

首能量规则已按摘要变为5ms滚动RMS≥200且至少半窗样本绝对幅值≥200，允许正常过零。
指标记录的是客户端已解码到含能量帧的时刻；此前静音帧可能仍排在播放队列中，
所以1.48～1.54秒不是圆屏实际听见首字的测量，不能直接作用户端承诺。

## 连续性、取消与选择adaptive的理由

全部12次测量的估算underflow_count/max_underflow/total_underflow均为0；复用也为0。
四次adaptive正式测量初始/恢复目标均360ms、rebuffer_count=0，队列峰值1320～2040ms。
360ms是音频库存目标，不是固定增加360ms墙钟延迟：本窗首PCM至首Opus约1ms。
普通incremental同样没有估算欠载，**本窗没有证明adaptive的连续性优于它**。
两条短句不足以代表长文、GPU并发负载、网络/设备播放或日用多轮分布。

adaptive独有的直接取消案例报告：

- 首能量后确认generation_in_flight=true且active_requests>0，cancel_live_work_observed=true。
- 取消后交付包数0，客户端约34.547ms返回；reader_join约34.476ms，reader_stopped=true。
- 本地已排队音频丢弃1080ms；服务随后空闲，健康清理等待约2.577ms。
- 下一次同编码器复用完整，EOS=true、身份不变、服务空闲、估算欠载0。

这证明本次客户端与协作服务取消/清理/复用路径可用；34.547ms不是扬声器静音时间，
零后续回调包也不表示此前排队/设备缓冲已经播放完或GPU支持即时kernel抢占。

ROOT选择adaptive可保留现有有界缓冲/欠载恢复策略，并采用本次直接验证过的取消路径；
它实际请求模型incremental。该选择是保留缓冲余量的工程判断，不是本窗证明最优。
记录接受的成本为部分案例完整生成更慢；不为追求较低首帧数字改seed、声线、hop或分段，
也不把“首能量代理更早”扩大为所有回复、全链路或设备端均更快。

## 交付与后续执行边界

AD放行意见只覆盖本候选、当前声线和adaptive模式的受控日用切换；ROOT负责配置/服务部署与恢复。
ROOT核对资源及保护数据后按已授权范围切换，随后采集实际日用首声、连续性、声音及打断反馈；
若出现明确故障，保留该候选/模式/样本上下文并按既定范围回退，不复用本次已结束GPU窗口补跑。
本会话没有改变日用模式、宣称设备验收或重复执行模型。

只读汇总脚本重新解析14条operation行，确认13 complete/1 intentional_cancel、全部身份/服务空闲/
watcher退出标记及0欠载计数；13条完整音频的帧数/采样/尾部补齐关系逐条断言通过，脚本未导入torch。
两处本地证据链接存在。严格文档检查退出1：新记录未登记、unknown-selection，实际检查0份；
另有本记录及前两份AD记录unlisted-document警告，未宣称严格检查通过；共享manifest未改。
