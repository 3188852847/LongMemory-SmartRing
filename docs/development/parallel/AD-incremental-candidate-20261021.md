# AD：增量/自适应完整客户端候选与回退接口

日期：2026-10-21。基线 `98db9f692f1ec11df57e0a832555e925aaa89546`，
分支 `codex/ad-incremental-candidate-20261021`，沿用AD隔离树并保留旧分支/证据。
本轮实现客户端交付故障边界、只读状态和缺口合成验证；不写共享配置/个人库，不操作日用、COM3或声音/角色，
不降低VAD、不关闭AEC，不加载真实模型。所有者休息期间不请求实机/下载。

代码交付依赖顺序：

1. `27dd37f782345458f59e5a07615ca0503ac70961`：连接内策略、状态getter、流式/全双工候选测试。
2. `afdb6734f5ff27fd1463c95c3af8d4ed9f80a568`：兼容回退也正确标记回调已开始。
3. `84ac8cfc84f5beda3cc404b7ef19d75713cdf328`：兼容回退回调失败不再向上游传播可重试信号，避免入队后重播。

## 已有证据与仍失败的边界

| 项目 | 已有事实 | 不能扩大为 |
|---|---|---|
| 当前声线真实三模式窗口01 | 候选116047ebe，83.078秒，2热身+12测量+取消+复用=16调用；四次adaptive首能量约1.48～1.54秒，测量估算欠载0 | 首能量不是设备首字；两文本各两次且seed不受HTTP控制，不是推广百分比/P95 |
| 真实取消/复用 | 有能量后确认模型在途，取消后交付包0，约34.55ms客户端返回，服务空闲/reader退出，复用完整 | 不证明设备扬声器即时静音或长文/多轮全覆盖 |
| 模型成本 | 增量路径部分完整生成更慢，Flow/HiFT调用更多；T0有一次buffered更早 | 不宣称adaptive全面更快或连续性优于普通incremental |
| OWNER早先adaptive反馈 | 有时“停一下”没显示、旧声继续，实机FAILED | 合成放行不能覆盖拒收；不能因buffered后来也漏检就倒推adaptive已通过 |
| 后续输入诊断 | buffered播放期仍有入队/VAD检查但speech不增长；ROOT后来报告2b58诊断试验有一次播放中打断且OWNER说正常 | 间歇漏检尚未定位，不是根因已修复或增量实机验收 |

证据保持引用：
[窗口解释](AD-three-mode-results-20261021.md)、[OWNER失败记录](AI-adaptive-physical-failure-20261021.md)、
[前半链复现](AD-barge-in-source-duplex-20261021.md)、[AEC核查](AD-aec-playback-input-20261021.md)。
本轮不重读真实日志/音频，不复用已关闭的GPU租约，也不重复旧短句GPU窗口。

## 本轮补齐的实现

[cosyvoice_delivery.py](../../../scripts/development/xiaozhi/cosyvoice_delivery.py)
仅在连接内记录请求模式和有效模式，不读写偏好；
[cosyvoice_streaming.py](../../../scripts/development/xiaozhi/cosyvoice_streaming.py)消费这一策略：

- 正常incremental/adaptive、正常打断取消均保留原模式；没有自动推广、改模型或声线。
- 确认客户端读流清理后，普通流错误将后续片段降为buffered；持久化请求仍保留原值。
  当前已开始回调的片段记失败，不重播，也不把剩余文本补成第二遍整段。
- 回调可能已入队才抛错，现以“回调曾开始”作为保守交付边界，而不是等回调成功返回才禁止回退。
- 第一回调前且清理已确认时，保留既有完整WAV兼容回退。只调用一次既有方法；
  该方法本身仍有固定上游的合成重试，**不能把一次委托写成一次真实HTTP请求**。
  其回调若已可能入队后抛错，本层截住重试信号、丢弃后续回调并记失败，避免上游因回调异常重播。
- 读流清理超时/未确认时锁住该连接的新请求；即使同时发生正常取消，也不能把未知清理当作取消成功后继续追加。
- 已开始的连接内修改请求模式会进入restart_required；由受控重启/新连接应用人工模式切换，不热改旧生产者身份。
  客户端标记只覆盖当前连接，不是跨连接GPU租约；ROOT/AI受控恢复前仍须独立核对旧reader及服务active_requests。

本轮不改变60ms Opus帧、360ms初始缓冲、模型hop、自然分段、VAD/AEC和设备协议。
因此这些故障护栏不能修复“近端没有判speech”的输入问题。

## 给ROOT→AI的固定getter/schema

入口为 `voice_latency.delivery_snapshot(connection)`，也可直接导入
`cosyvoice_delivery.delivery_snapshot(connection)`。
纯只读：不创建session、不发HTTP、不读档案，不改既有v6 voice_latency.snapshot()结构。

固定13个键，每次均存在，无异常正文/时间戳/用户文本/历史列表：

| 字段 | 固定类型/取值与语义 |
|---|---|
| version | int，1 |
| state | no_connection / not_observed / configured / buffered_fallback / restart_required / invalid_configuration |
| requested_mode | buffered / incremental / adaptive / null；配置请求，不是实测模型行为 |
| effective_mode | 同三值或null；故障锁定时null，不谎称仍在交付 |
| failure_code | null / before_handoff / after_handoff / reader_cleanup_timeout / reader_cleanup_unconfirmed / configuration_changed |
| last_outcome | null / completed / cancelled / failed / fallback / preset / blocked；执行中为null，结束后指最近一次片段/尝试 |
| handoff_started | bool；当前/最近片段曾开始Opus回调，可能已入队；不是确认网络已发或设备已播 |
| reader_cleanup | not_observed / not_required / confirmed / unconfirmed；客户端reader状态，不是服务端active_requests证明 |
| segment_active | bool；当前客户端片段执行中 |
| next_segment_allowed | bool；当前无活动片段、无重启锁且清理非未知时，才允许到达串行入口后追加；不授予并发或服务器健康许可 |
| restart_required | bool；锁定/配置失配时true |
| outcomes | 固定六键blocked/cancelled/completed/failed/fallback/preset，各0～1000000，饱和不增长 |
| physical_playback_verified | 永远false；此getter不承担实机验收 |

补充解释：not_observed只代表当前连接尚未采到片段；configured也不是服务warm或实机通过。
buffered_fallback同时显示requested!=effective及固定原因；后续buffered完成更新last_outcome=completed，
之前失败仍留failed计数，不能将之前部分段重新标为完整成功。
执行中reader_cleanup=unconfirmed是正常“尚未收尾”，segment_active=true且追加许可false；
只有结束时仍未知才锁定为restart_required。
fallback只表示既有兼容方法已返回，不等同完整音频成功；只有completed计数当前流正常完成。
getter用于Cosy客户端，非Cosy后端不得仅凭默认not_observed字段渲染成Cosy已启用。

枚举组合与计数满值的保守json.dumps默认格式最大505字节；专属测试硬限≤512字节。
AI可在原/api/device合法上界15519字节的预算内加入这一小对象，但必须自己验证外层键及其他投影字段后仍≤16384字节；
本分支不宣称整个API集成测试已通过。

## 持久化、回退与AI文件归属

持久化键固定 `cosy_delivery_mode`，三值/default buffered；旧偏好没有此键保持buffered。
只在Cosy流水线子进程传 `--cosy-delivery-mode <value>`，不影响其他TTS，不借机开启预生成/SmartTurn。
配置请求与运行有效模式分开显示；故障降级只在连接内，不写回私有偏好。
人工长期回退由AI保存buffered并按既有所有权/重启流程重开，不删除声线、角色、个人库或旧证据。

AI已有草稿stash对象 `42872c691702eebaafff5b1fa123f4c87a9f7d6e`，其preferences/runtime/controller/API等归AI，
AD未恢复或复制该草稿。ROOT已转报AI在复用三值校验、默认buffered、仅Cosy子进程传参，
正在做配置/观测分离；本分支不包含其文件或声称持久化已经合入/上线。
AI组合复核应覆盖保存→重启→精确子进程参数、缺失/非法值、非Cosy不传参、运行降级不改请求、保存buffered后的受控恢复，
以及上述完整API字节上限。实际设置写入/重启仅由ROOT在后续范围内协调，本轮未执行。

## 新增合成全双工与回退结果

[专属策略测试](../../../tests/unit/development/test_cosyvoice_delivery_candidate.py)及
[候选v2全双工测试](../../../tests/unit/development/test_ad_incremental_candidate_duplex.py)
复用[AD夹具](../../../tests/fixtures/ad_duplex_probe.py)，不再重跑旧10例成功矩阵：

- 真实CPU Opus、真实随机回环HTTP/WS、直连v2头、固定上游AEC纯FFT控制流，以及VAD/ASR明确替身。
  合成假定上行回显最近下行timestamp，**不冒充固件真实行为或声学识别验证**。
- 正常adaptive：18帧输入均到达，18次固定AEC调用，1次文本交接/interrupt，reader回收；
  outcome=cancelled、有效模式仍adaptive，没有因正常打断误降级。
- incremental/adaptive分别注入一次缺EOS：旧段只发有限的已成完整帧，不重播整句；
  HTTP模式序列准确为incremental→buffered，后续新轮完整生成60帧，仍可收到18帧输入并完成交接/interrupt。
  旧段failed=1，后续completed=1，不把失败段算成功。
- 16k连续FIR缺EOS不冲刷尾样本，adaptive错误时丢弃未交付队列，旧段完整帧数可随线程交错在1～9之间；
  早期测试假定固定10/9帧的前提不适用，已改成不重播上界及新轮60帧精确核对，未为凑帧改生产算法。
- 模拟cleanup异常先回收实际合成线程再注入“不确定”，验证下一新句也不发HTTP；没有遗留真实线程。
  验证新连接重建、合成设置内存roundtrip/人工buffered回退、状态不可变副本、计数饱和与512字节上限。

最终代码组合42项通过（6.04秒）：专属策略/原流式受影响分支、新v2全双工3例及独立v6结构不变1例；
不把早期中间版本的测试数当作最终结果。
不运行模型/日用HTTP，不写音频，夹具断言未导入torch。

```powershell
Set-Location -LiteralPath 'D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ad-cosy-continuity-20261021'
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -B -X utf8 -m pytest tests/unit/development/test_cosyvoice_delivery_candidate.py tests/unit/development/test_cosyvoice_streaming.py tests/unit/development/test_ad_incremental_candidate_duplex.py -q
```

## 审查状态与下一步

AD客户端候选可交AI审查；持久化/公共getter投影组合仍由AI交付，默认日用buffered不变。
本次控制流修改不依赖新的模型结果，今晚无需为了重复既有短句收益再开GPU窗。
已有有界三模式驱动与AI整窗启动器继续保留（18774、16调用、300秒含加载/两次热身、每次15秒），
若ROOT判定需要新的真实证据，必须另核对资源与新收据，不能复用旧租约或擅自换长文本扩大预算。
长回复/多轮实际供给与真机首字、声音、间歇输入漏检仍未形成当前候选通过证据；本记录不批准自动切换日用。
不打扰休息中的所有者，后续实机由ROOT在合适阶段协调。

本轮文件未触及AC输入helper/AI启动投影/共享manifest。九处链接目标存在，暂存差异检查通过。
严格文档检查退出1：新记录未登记、unknown-selection，实际检查0份，另有unlisted-document警告；
未宣称通过，清单由主会话整合登记。
