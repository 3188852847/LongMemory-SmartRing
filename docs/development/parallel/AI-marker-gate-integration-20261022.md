# AI：本机标记门禁整合与新按键修复

日期：2026-10-22。基于已发布HTTP诊断契约 `849183ec73629d0d702c0992a0f3003145aa4d62`，新隔离分支 `codex/ai-marker-gate-integration-20261022`。ROOT授权仅本地marker/helper、纯合成检查与窄记录；不改变语音算法、服务API、模式、配置、个人库、声音资源或固件，不录音、不自动实机试验。旧“没有停、回车按早”仍是所有者反馈；原无效标记不挪动、不补零、不改写。

## 精确来源与门禁合同

AC前置 `e8c51d52` 接为 `629aef9d`，候选 `4df46bf967402e3f060bcc217de4055df9f43a21` 接为 `08d34f0d`；范围见 [AC记录](AC-vad-trace-20261022.md)。AI独立发现字符层自动重复漏洞，经ROOT授权局部修复为 **`0ca24190d2376620b5ad967a122e66b5bbefca2a`**。此前端点/成对观测的阶段证据见 [AI端点记录](AI-aec-pairs-integration-20261022.md)，不把旧CI或原统计当作本次门禁验收。

正常CLI必须 `record --samples <本次samples.jsonl> --output <新markers.jsonl> --timeout-seconds 90 --freshness-ms 3000`。缺samples在解析阶段拒绝，低层旧record只保留给已有合成夹具，不作为实测入口。记录独占新建、不覆盖原文件；helper只读本次采样文件的有限完整尾行，不连API、不打开音频、不启动后台调度。

门禁要求两组新鲜、同v2代次、clock有效、未饱和、非null且valid>0的paired基线，结合邻近device.ready、active_output、answer_send_returned增长、first_answer_send_returned>0和非preset生产路径，requested/effective均adaptive且无失败/回退。cue或预热不放行；这些device条件仍非跨端点原子/同连接证明，也不是实际声音证明。

软件条件满足后，所有者确实听到本轮正文才在当前前台窗口按英文H，不需回车。随后看到提示，再新按Enter起键，随即自然说一次“停一下”，松开后另一次新Enter终键。ready仅在软件条件与H确认后写出；旧版本的ready不能倒推具有本次门禁含义，实际使用必须绑定helper摘要。键盘时间仍是人工外括号，不是精确声学起止。

早键立即丢弃，不排队成后续起点。换代、未知/过期、模式回退、计数降或饱和、采样文件倒退、处理长停顿均取消；默认90秒包含等待、听感确认、发声和外侧采样，参数仍按AC已批准界限验证。取消不自动重试。起键后的output=false或答案包停止增长可能是成功打断，不据此取消；终键后等到同代次且请求开始不早于终键的完整组，缺失则保留原标记并追加cancelled，绝不挪时间。

## 原字符层漏洞与修复边界

原4df阶段127项接口/观测定向通过，但没有覆盖物理按下/抬起。AI合成复现：起键Enter一直按住，300ms后的自动重复字符被当作终键；门禁前按住H，后续重复字符也能被当成新的听感确认。两份原反例保留于本树 `data/test-tmp/ai-marker-gate-repeat-review-20261022-01.json`、`ai-marker-gate-held-heard-review-20261022-01.json`，均是合成字符流，不冒充真实键盘证据。

修复只在 [helper](../../../scripts/development/xiaozhi/voice_signal_markers.py) 用标准库ctypes读取当前STD_INPUT_HANDLE的ReadConsoleInputW记录，识别按下/抬起边沿；不装全局键盘钩子、不改变控制台模式、不存任意输入文字。有关键的暂存状态按虚拟键/扫描码/增强标志区分，方向键不会出现旧getwch的H后半码误认。H/Enter自动重复或合并重复都不推进，必须释放后再按；主Enter未释放时，数字键盘Enter的抬起不能将其错误清空。Q/Ctrl-C仍立即安全取消。

控制台缺失、重定向输入或读取失败只会取消，不能退回旧无门禁record。只有当前前台控制台的输入有效；ROOT未来须在适合的本机交互控制台运行，不以管道代替所有者确认。ABI固定宽度KEY_EVENT=16B、INPUT_RECORD=20B，Unicode单位按Windows UTF-16处理；未用真实键盘验证来代替合成检查。

## 清洁源码及检查

helper冻结提交 **0ca24190完整值如上**，原字节SHA256 **`8051c108448a815f66a22da4db3e8aa220214fa7944962bf9d6644c151ca1684`**。新 [事件检查](../../../tests/unit/development/test_voice_signal_console_keys.py) 覆盖持键、松键后新按、合并重复、修饰键、主/数字Enter、扩展键、API失败及完整record_gated流程。141项定向检查通过（0.96秒）；此前140项为加主/数字Enter用例前结果，均保留，不相加。

在清洁 **`0ca24190d2376620b5ad967a122e66b5bbefca2a`**、tree `5784a28ecd352eb408f4fad1c2982432ffeb8370` 上，九文件组合 **338 passed、0 skipped，1.76秒**，报告 `data/test-tmp/ai-marker-gate-combined-clean-head-01.xml`，SHA256 **`343ac6077a1cab3b9ea1d3349e4cee4e886c3fb58111b9560a2dca23d4636419`**，audit_report=(338,0)。没有改资源例外或质量守卫。

现装主Python3.12.13及小智Python3.10.20分别实际导入修后helper、检查ABI/Windows函数导出并解码合成按下/抬起；未调用真实控制台输入函数。缺samples的裸CLI均在创建文件前拒绝，未调用旧record。回执 `data/test-tmp/ai-marker-key-events-python310-312-clean-20261022-01.json`，SHA256 **`0c4a773a310364ce01c9490adc156b9de8b5cbbb8011a2b1b3314e456a4164c9`**。没有安装依赖、加载模型或操作设备。

本轮完整审查回执 `data/test-tmp/ai-marker-gate-clean-combined-receipt-20261022-01.json`，SHA256 **`5d7df6ab33a37fb539eacb8c3b0daadb32a78316204c11cd333e74cb8c7a4d5f`**。全src/longmemory及scripts/development/xiaozhi的路径＋规范化字节摘要为 **`0663f4b5415a920a151954acaea45b4ddb4c5ae2faabe3a806bbefdbd9400dbc`**；受管记忆原语仍为 `1003fe901fa49bd2750242637b18744694f5bebdabfc3d06e0cf7a5eb262fdac`，不重签或伪写旧管理证明。

## AD精确重绑及交付范围

AI已只读逐文件核对AD最终manifest中全部文件摘要，并核对时间边界验证器实际从当前verify_handoff加载冻结helper，不将旧4df绑定当成新结果。最终manifest位于AD树 `data/test-tmp/ad-aec-pairs-v2-prep-20261022-01/gate-0ca24190/delivery-manifest.json`，SHA256 **`b09635ccf6cd9b4739142d8492b30e1fda7e8b4879dc3d5ad885461391fffd48`**。它绑定helper提交0ca24190/摘要8051c108…及私有采样入口 `sample_gated_0ca24190.py`，入口SHA256 **`7c5c1869bb6761d1f5698833f5415cf29c20325559a8e7b67c85664539232f11`**。

该重绑16场景及采样生命周期/3000与3001ms边界/90秒跨阶段截止通过；新增事件验证确认持键不误记、控制台失败时采样器不发任何请求。handoff结果SHA256 `b4a200108ce12734440708d16b555b3502487a71f2a49f86f96f2da3ce06d173`，时间边界结果 `23bb82168ac821f31c9b65e86051c1a657bc95bc96970ac6e05534357bb94e0b`，事件接力结果 `51d38e18e132caf0b3adef1a9cb44124eb45095ae6935fadf461a9e7b6c05b9e`。结果source=849指HTTP合同，helper另用0ca提交及8051摘要绑定，不能混写。AD结果并非AI新增执行次数，不与338相加；AC亦向ROOT报告修后无契约冲突。

最终收尾只改本记录及manifest，不改helper或其他源码，故不使AD字节绑定失效。与849逐文件比较，src、前端/锁文件、启动器、服务端点、投影及生产侧AEC/VAD观测均未变；本轮无需因此重启无关日用、重建前端或触碰个人数据。ROOT负责合入/推送和今后得到所有者新READY后的单次实际控制台/圆屏体验；目前仅软件门禁通过，不声称语音故障修好，不主动再测，也未获录音授权。
