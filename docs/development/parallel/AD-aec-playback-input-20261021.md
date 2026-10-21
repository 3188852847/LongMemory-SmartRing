# AD：播放期输入与固定服务端AEC合成核查

日期：2026-10-21。基线 `edc51f8b5b8ff669c1aa4d354f0ca436016de5da`，
分支 `codex/ad-aec-playback-input-20261021`。本轮只新增本记录和专属合成夹具/测试，
不改生产算法、voice_latency、AC helper、AI启动/投影，不增加另一套观测helper，不操作日用或串口。

## 新证据如何收窄范围

仅按授权读取主项目
`local/archive/hy-advanced-release/ad-incremental-20261021T115425Z-aca4ac/input-probe-deploy/owner-input-summary-01.json`，
字节SHA256 `1090b32dc7c06588fba8bc059c6f74ab8235676c19cb3d8c405b35d29640c19e`，不复制原件进Git。
ROOT报告当前buffered、实机再次失败；此次不是增量独有测试。

21:06:59.290→21:07:34.782（北京时间）两端样本：queue_put/get、vad_check均203→794，
vad_speech保持57、formal/speech保持1、abort保持0，端点样本队列深度0。
未见长度拒绝、空识别、just_woken跳过或错误累计。21:07:51.503后speech才60→65，第二次正式识别完成；
下一输出活跃窗内speech又不增长。output_active含服务端生产/输出生命周期，不能视为逐帧声学播放起止。

这排除了“这个区间服务器完全没有输入数据”的说法，也不支持继续用长度拒绝、缺AEC声明或增量独有loop阻塞解释。
但没有准确发话标记或波形，**不能证明用户说的那段近端语音已进入服务器**，更不能只凭speech不增长锁定AEC。
当前三个声明字段均true，只证明协商/安装/标志条件：
`device_aec_advertised`来自HELLO.features.aec；上游hello将它解释为启用服务端AEC，
它不是“设备本地AEC算法已执行”的回执。两个AEC字段同时true不证明串联做了两次AEC。

## 固定音频与时间戳路径

外部源固定 `eb4b28c59ed7ed885258498cf757ce14352d620e`，只从本地Git对象提取方法：

- [direct_ws_v2.py](../../../scripts/development/xiaozhi/direct_ws_v2.py) 第11/27～42行：
  16字节网络序头`!HHIII`，version/type/reserved/timestamp/payload_size；校验后取Opus载荷。
  第52～65行：先委托原解码，再在timestamp>0且client_aec时调用_apply_aec。
- 原ConnectionHandler._decode_opus_packet/_init_connection_state：单声道16kHz解码器，每帧960样本。
  direct_ws_v2第81～93行：下行用主机墙钟毫秒低32位作timestamp，先解Opus成同样16kHz/960参考PCM，入缓存再发送。
  下行发送时刻的缓存不是“设备实际扬声器已播放”的回执。
- 已给端点聚合77×1920=147840、29×1920=55680，与16kHz单声道PCM16/60ms一致；
  不等于逐帧格式验收。本轮真实CPU Opus也验证16k/24k编码各一帧均能解到16k/1920字节参考PCM，
  因此不能仅因Cosy原波形24kHz就断定AEC参考与麦克风16kHz必然失配。
- 设备端如何回传timestamp、是否已做本地处理，当前声明不提供该事实；AD未访问固件/设备。
  由ROOT根据既有0016证据及后续最小只读状态核对，不新增刷写或串口操作。

固定ConnectionHandler._apply_aec第414～524行：

1. 空参考、仅1个参考、mic RMS<100等会直接返回。
2. 第437行取原始整数timestamp绝对差最近帧，再在前后各2帧中按对数功率谱余弦绝对值选参考。
   没有最大timestamp差或低匹配拒绝，也不据独立双讲检测判定应保护近端。
3. 第483行按麦克风长度截取/补零参考；对麦克风加Hann窗后做FFT，重建未做反窗/重叠相加补偿。
4. 第507行谱减保底原幅度0.1；第514行best_corr≥0.97且ref RMS>500时再乘0.3。
   注释中的“综合算法”不代表实际包含独立近端/双讲判别。
5. 缓存维护每30秒清一次墙钟年龄>120秒的项；这不等于_apply_aec本身会拒绝音频时间上不匹配的参考。
   它不读取cache_time；60秒旧项尚未超过这个120秒TTL（存活时间），不能称其违反既有清理逻辑。

## 合成反例与正常消回声对照

[夹具](../../../tests/fixtures/ad_aec_reference_probe.py)只编译固定_apply_aec方法AST（语法树），
用现装小智3.10/numpy1.26.4调用纯FFT算法。每帧960个16kHz PCM16样本，
人为定义参考400Hz/幅度9000、近端700Hz/幅度5000；另用400Hz/相差90°近端与参考作谱重叠对照。
不使用用户音频，不加载VAD/ASR/TTS/GPU模型，不预测真实语音识别率。

| 已知合成条件 | 输入RMS | 输出RMS | 解释 |
|---|---:|---:|---|
| 无参考或只有1帧参考，700Hz近端 | 3535.465 | 3535.465 | 原样旁路 |
| 只有回声，0.5×400Hz参考 | 3181.901 | 58.055 | 有效消回声的正对照；不能因此主张全关AEC |
| 只有700Hz近端，独立400Hz参考 | 3535.465 | 2163.530 | PSD相关0.619477仍处理；加窗已改变无回声近端幅度 |
| 只有400Hz相差90°近端，无回声 | 3535.469 | 216.020 | 时域内积0、PSD相关0.966070，仍压到原RMS的0.061101 |
| 400Hz回声+700Hz近端 | 4756.470 | 2217.613 | 700Hz投影RMS3535.465→1765.442；并非每种近端都被同等压低 |
| 相差90°近端+时间戳相差60000ms/墙钟年龄60秒参考 | 3535.469 | 216.020 | 与当前参考输出逐字节相同；没有即时时间差拒绝 |

相差90°情形没有触发额外0.3（相关值低于0.97），仅已有谱减/窗已产生明显抑制。
这些结果证明固定算法**可以压低人为定义的近端分量**，也能消除人为回声；
它们不能证明本次真实近端已到达、真实参考过期或真实VAD因抑制而未触发。
正弦不是人声，算法性质测试不能作为声学打断验收。

## 给ROOT→AC的最少观测字段

AC负责唯一只读helper，AI负责启动与投影；AD不实现重复采集。建议在同一连接、按speaking/idle分组聚合，
不保存PCM、频谱、正文、设备标识或真实timestamp值：

| 边界 | 最少字段/含义 |
|---|---|
| 格式/调用 | 解码PCM样本数分箱，timestamp零/非零计数，_apply_aec调用/返回计数；capability不替代实际调用 |
| 参考存在性 | ref数量0/1/≥2；最近候选参考PCM长度是否匹配；最近候选raw时间戳差/缓存墙钟年龄分箱 |
| 抑制前后 | 同帧pre/post RMS分箱与比值/明显抑制计数；called不等于有效处理，output_same也不等于没报错 |
| VAD边界 | post-AEC送VAD的能量分箱、VAD概率/阈值边界及最终speech计数；不重新跑第二个VAD模型 |
| 试验阶段 | OWNER准确发话起止标记、服务发送/说话状态；播放与静音各一次相同短口令，不采集口令正文或录音 |

“最近候选”不一定是PSD搜索最终选中的帧；helper没有真实匹配结果时必须按此命名，
不能为取best_corr复制第二遍FFT或把nearest伪称matched。
若做逐帧关联，应由队列旁路匿名序号配对；不能把连接last-aec字段直接视为稍后VAD处理帧的指标，队列可领先。
若仅分组聚合，要明确它不能单独证明同一帧因果。

解释顺序：发话标记内pre-AEC就很低，先查设备/采集/设备本地处理边界；pre明显而post被压低且VAD概率低，
服务端抑制成为更强候选；post仍明显却VAD低，再查输入/VAD状态与概率；无匹配参考/实际AEC未调，则不能归因本算法。
在得到这些区分之前，不设置新的相关性/时间阈值、不关闭AEC、不改采样率或固件。

## voice_latency读数与验证

第一回答末段快照：memory_ready=4617、LLM首输出=6067、TTS开始=6122、audio_ready=8549、first_sent=8566ms；
第二回答first_sent=3016ms、memory_ready=36ms。这些是不同问题/条件，不能把8.566秒全归因AEC或作为成对回退结论。
第一轮audio_ready至发送尾差17ms，音频接口计时不提供近端波形/声学播放或AEC质量证明。

[专属测试](../../../tests/unit/development/test_ad_aec_reference_probe.py)5项通过（0.28秒）：
7种合成条件、旧/当前参考字节对照、16k/24k Opus参考格式；没有重跑旧全双工成功例或广泛CI。

```powershell
Set-Location -LiteralPath 'D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ad-cosy-continuity-20261021'
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -B -X utf8 -m pytest tests/unit/development/test_ad_aec_reference_probe.py -q -s
```

未改任何生产行为或运行状态；增量切换继续暂缓，实机故障根因仍未确证。
三处链接目标存在；严格文档检查退出1，新增记录未登记、unknown-selection，实际检查0份，
另有unlisted-document警告，未宣称通过；共享manifest未改，留主会话整合登记。
