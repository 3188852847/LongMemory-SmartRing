# AI：AEC成对补充端点与按键标记整合候选

日期：2026-10-22。基线为已发布 `8617911795ede87456b4805a2f32f45356ecdea9`；新分支 `codex/ai-aec-pairs-integration-20261022`。ROOT授权仅数值诊断及隔离整合，不改变输入音频、AEC/VAD/ASR阈值、abort、声音模式、个人库、私有配置或日用服务。当前仍不能选择漏检行为修复，也不证明buffered已按本次故障实机复验。

## 来源及范围

AC定位记录 `26547006` 接为 `d160ae0d`；核心 `5d92e43b8c03fdbcba1118962dd93e365c19891c` 接为 `0deafa6c`；后笔helper/合成检查 `f30b7e2106ed6733af2c96d27f5ac75f51f71760` 接为 `c0742fa3`。AC生产侧与原始阶段证据见 [AC记录](AC-vad-trace-20261022.md)，不把未提交源码作为冻结来源。原Cosy候选分支和两份stash保留。

AI拥有 [有限投影](../../../scripts/development/xiaozhi/voice_signal_diagnostics.py)、原 [HTTP端点](../../../scripts/development/xiaozhi/control_http.py) 与 [当前连接读取](../../../scripts/development/xiaozhi/device_control.py) 的版本协商；没有改/src适配器、控制API权限或原设备状态16KiB限制。AC继续拥有原观测与 [纯本机标记工具](../../../scripts/development/xiaozhi/voice_signal_markers.py)，helper审查问题由ROOT转接修正，不在两边重复修改。

## 确定的HTTP合同

- 原 `GET /api/voice-input-signal` 及显式 `?version=1` 返回原完整严格v1，字段、浮点合法域、旧recent_groups及6000字节上限不变。
- 只有显式 `?version=2` 才调用 `voice_vad_signal_snapshot(conn, include_aec_pairs=True)`，将内部full-v2投影为独立小响应。默认getter不接新关键字，旧生产侧仍可读取v1；旧生产侧不支持v2时返回v2的unavailable，不重试、不伪装零统计。
- v2顶层恰为 `version=2/kind='aec_pairs_supplement'/state/clock_ms/observation_generation/aec_pairs`。raw的 `observation_id` 映射为公开代次；必须是16位小写十六进制的连接内随机值，不是设备身份。getter不创建新代次或观测。
- `aec_pairs` 仅含 `rms_floor_pcm16=500/ratio_edges=[0.1,0.25,0.5,0.9,1.1]/total`。不输出新增recent或旧groups；不先把整个raw字典JSON化后再删字段。total固定valid、invalid、zero_input、below_floor、original_error、observer_error及六格ratio_bins，计数域0..2**31-1；饱和值可读但不得差分。验证 `valid=min(LIMIT,zero_input+below_floor+sum(ratio_bins))`，不允许坏分母蒙混通过。
- public `clock_ms` 为同机单调毫秒，独立整数域 `0..2**63-1`，或null，拒绝bool、浮点和越界；绝不套用count上限或用当前时间补造。observed但clock未知时保留null，禁止有效对齐。无连接、未观测或不可用时数据字段为null；observed仅说明连接观测已存在，尚无成对统计或旁路失败时aec_pairs仍为null，不造零。
- 原Bearer、Host、Origin/Sec-Fetch检查在协商前执行，响应仍no-store/nosniff；不是匿名接口或浏览器CORS接口。空/未知/非规范版本返回400及固定unsupported_signal_version；重复版本或额外查询键返回400及固定invalid_signal_query，不回显坏参数。POST/HEAD及变体路径仍拒绝。

## 统计解释与容量反例

成对值来自同一次原AEC调用的输入和返回；原结果身份与原异常身份保留，计数及快照/clock在同一锁内。RMS复用既有_energy的三位小数量化标量，比值边界也作用于这些量化数值；500只是描述统计门，不是精确声学阈值、VAD行为门或足够人声的判据。原播放标志不证明设备实际发声；无标记的旧653包不能全部标为用户讲话漏检。

保留预算失败：AC早期三位小数构造v1=5237、无代次raw-v2=5825；加强浮点构造后v1=5815、raw-v2=6481，去新增recent仍6224，均不能据此宣传完整v2可进6000B。AI再覆盖概率min/max均为23字符合法正数表示及合法false标志，得到更强构造 **v1=5846B、full raw-v2=6512B**。旧投影仍接受该v1；full raw-v2明确超过6000。公开独立补充的全部最大合法计数、16字符代次及19位clock构造为 **484B**，不是放宽预算后的压缩包。原文5243/上述5815等均保留为各阶段样本，不能当覆盖全部旧浮点域的最大值证明。

[端点回归](../../../tests/unit/development/test_voice_signal_v2.py) 使用自有随机回环HTTP及现有XiaozhiControlClient原分块读取，分别完整读取v1、v2和原15519B设备响应；默认状态明细未删改，16KiB客户端上限未变。还检查坏固定字段、未配对/null时钟、旧getter、断线/多连接、缺测、只读不推理、版本拒绝及先验权。

## 本机时钟与1Hz对齐

主Python3.12.13和现装小智Python3.10.20实测均用GetTickCount64，报告分辨率 **15.625ms**，不是QPC高精度。首轮21个短通信均在父进程时钟括号内，但0ms值是量化结果，不能解释为零延迟；第二轮覆盖31个不同刻度、跨度890ms，所有子戳仍在父进程发出/收完区间内，受控25ms子延迟每五次一次，最大往返记录47ms。回执 `data/test-tmp/ai-aec-python310-312-monotonic-check-20261022-02.json`，SHA256 `db04d41664ba09e35deddf3cf797b8201cdeedb6375d921c87769903f7edf1be`。仅证明当前机器/解释器可比较，不能证明精确发声边界或真实服务时延。

ROOT将来一次受控配合中可安排安静和播放窗口，同一句公开“停一下”、同一距离位置音量；每窗口单独新建markers文件，不能将多组起止塞入一次align。record起键后再说，讲完再按止键；至少留出起键前约2秒和止键后约1秒的安静/仅播放背景，采样覆盖止键后的完整一组请求。无效窗口停止，不追加循环实测。本轮未实际发提示或邀请所有者讲话。

AD数值采样在每组请求外实际采集monotonic_before_ms/monotonic_after_ms，约1Hz；必须将公开对象存signal_v2。clock_ms落在整组括号内，marker与sourceclock保留计时粒度余量，报告实际请求跨度、两端余量和内部采样空洞。只用同观察代次累计配对统计作差，近期三秒滚动窗口不得相减。原144行没有真实新时钟/代次/按键，禁止事后补造。

跨端点不原子：一个v2代次只能直接绑定成对统计。device先读、v2后读可能跨连接，ROOT已采纳device仅保留前后背景快照，不输出同连接严格input_delta；不新增控制API或多请求证明。AC/AD按此接力，仍不得宣传输入与paired逐帧同源。

## 阶段检查与待接力

接口初检72 passed（0.76秒）；补充丢弃字段/方法拒绝及AC新增边界后76 passed（0.82秒），报告 `data/test-tmp/ai-aec-pairs-endpoint-preflight-01.xml/-02.xml`，重叠组不相加。现装3.10已实际运行 [标准库probe](../../../tests/fixtures/ai_aec_signal_probe.py)：500→250合成PCM、原方法2次（含一次BaseException身份保留）、getter不增加调用、默认v1及源clock包围正确；无网络、模型/Torch、音频落盘。最终清洁HEAD的检查与回执待候选冻结后列明。

helper尚未放行：AI合成复现 `data/test-tmp/ai-aec-marker-review-repro-20261022-01.json` 显示f30阶段中间aec_pairs=null后仍算首末pair_delta，并且内部2500ms空洞未报告。ROOT已转AC修正marker完整schema、内部unknown、floor/edges、时钟与gap；本树只接精确后笔，不重复改其helper。不拿原13项通过覆盖新边界；当前尚无实机、部署或漏检修复结论。
