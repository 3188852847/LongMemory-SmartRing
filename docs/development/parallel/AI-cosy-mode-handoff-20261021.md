# AI：CosyVoice 模式偏好与连接状态候选接力

日期：2026-10-21。ROOT授权继续AD增量候选与模式持久化；本树分支 `codex/ai-cosy-mode-handoff-20261021`，基线 `7746e728a356f90f5d034f193fd37861fbaec91a`。本轮不推送、不部署，不读写个人库、共享配置或日用服务，不使用模型/GPU或设备。

## 来源与范围

旧草稿 stash `42872c691702eebaafff5b1fa123f4c87a9f7d6e` 原件保留；另存检查点 `33b9d13aa1673f667633cb625acb95ecf205de69`，仅 apply、不 pop/drop。复用七文件后检查并补齐模式选择、启动捕获、状态与界面分层，源码阶段提交 `9c279b41`。两份stash均保留。

AD原提交依次为 `27dd37f782345458f59e5a07615ca0503ac70961`、`afdb6734f5ff27fd1463c95c3af8d4ed9f80a568`、`84ac8cfc84f5beda3cc404b7ef19d75713cdf328`、`e31a288fe93be8d31e4fb256ce1d4da25719f02c`、`4ca82d96b35a548d411e496dd879386aabc1da45`；在本树分别为 `b330903a`、`05192efe`、`6590b43e`、`cf2cdb9c`、`a67323eb`。AD [候选说明](AD-incremental-candidate-20261021.md)及[完整WAV回退修复](AD-full-wav-fallback-fix-20261021.md)保留其阶段结果，不混称最终版本。

发布日志路径修复 `b2180634b147db393a082e8ab3596f4c11e96fcb` 先 cherry-pick 为 `aca7b911`，随后按ROOT要求将原发布提交合入本隔离分支，保留精确祖先以便ROOT候选CI后快进。该修复改变全源码摘要但不改受管记忆原语；原219项证明的HEAD不重写，不能用b218单独CI冒充本组合已通过。

偏好协议8、buffered默认、适用语音子进程专用传递、一次性环境覆盖与本次启动捕获、可失效的既有控制面缓存、共同有限投影及UI状态说明见 [契约](../launcher-contract.md)与 [ADR-0203](../../adr/0203-cosy-delivery-startup-preference.md)。不做热切换，不改偏好默认，不改变声音/角色。界面沿用现有控件、状态样式及原设置锁；一处原子状态区显示变更，不夺焦点。

## 版本化复现

`data/test-tmp/ai-ad-full-wav-fallback-handoff-repro-01.json` 是仅含AD27阶段、本树HEAD `b330903a949676fe301a9ad060c43a48dd1d0ce2` 的独立复现：固定上游delete_audio_file=True路径回调已入队再抛错时重复5次，handoff仍false。不能归因于最终AD。

接入afdb/84后 `...repro-02.json` 已为1次合成/1包、handoff=true、failed/after_handoff；当时HEAD `aca7b9111b6d48a0a4d2402fa84978def0c83ebd`，共同投影有空行未提交，回执未记checkout_dirty，故不作为最终清洁HEAD证明。4ca进一步修复上游耗尽重试后无回调却记fallback；最终用固定源方法、真实WAV转换与CPU Opus独立重验，保存带HEAD/dirty/consumer摘要的新回执。

## 当前验证与限制

前置后端六文件322 passed（11.06秒），报告 `data/test-tmp/ai-cosy-prep-backend-01.xml`；这是接入后续AD修复前结果，最终检查另列。旧状态15519字节与饱和AD摘要一起走实际客户端分块读取，仍小于原16384限制；AC独立端点已在前轮实现，所有者本轮选择与现有契约一致。

本工作树没有node_modules。未安装依赖、未借用共享依赖、未本机执行新增四项React组件测试、一个真实合成主机浏览器保存/重新打开用例、类型构建/其余浏览器测试。ROOT在最终冻结分支精确SHA运行现有quality.yml workflow_dispatch；CI不得改锁文件或以既有发布CI替代。建议复核命令为 `pnpm.cmd test -- src/features/launcher/LauncherApp.test.tsx src/features/launcher/api.test.ts`、`pnpm.cmd build`、`pnpm.cmd exec playwright test e2e/launcher.spec.ts`。实际完整工作流仍由ROOT执行。

CPU回放没有声学模型、服务器真实请求或物理播放。handoff只说明回调开始；reader_cleanup只说明客户端流退出，下一段仍需串行准入及服务健康。原实机漏检与增量体验未因此验收。


资源清单只新增完整WAV八个参数化精确用例（原因 `owner-installed CPU WAV/Opus environment unavailable`）及增量双工三个精确用例（原因 `owner-installed CPU Opus/WS unavailable`）。收集得到11项与声明逐字一致；缺资源模拟为14 passed、11 skipped（0.33秒），`audit_report=(14,11)`，报告 `data/test-tmp/ai-cosy-resource-missing-02.xml` 与 `ai-cosy-resource-audit-02.json`。这是模拟，本机实际资源可用；首轮临时脚本按模块名匹配失误、收集即断言失败，无测试执行，保留 `-01`，未改生产测试绕过。

最终AD＋投影预检63 passed（7.16秒），其中包含实际固定上游WAV/CPU Opus及v2双工三个新用例；报告 `ai-cosy-final-ad-preflight-01.xml`。新增鉴权桥实际读路径测试核对单次原GET捕获、只读快照无新请求、坏旁路/其他引擎/坏状态清缓存。五份受影响文档严格检查无告警；这些预检发生在最终源码冻结之前，最终清洁HEAD检查另列。


## 最终清洁组合验证

被测源码冻结 **`f751d3dcd885bb4256c507aee67a8786327658f6`**，Git tree `482a4732d6dd39712dbe1aa69096ce6a228cbdd1`。原发布 `b2180634` 已是祖先；合并只冲突资源清单和文档清单的新增段，保留双方记录后与合并前 `22a4f090` 文件树完全一致，没有额外源码变化。

在此精确HEAD且前后clean，后端十二文件 **416 passed、1 skipped、7 subtests passed，18.41秒**，报告 `data/test-tmp/ai-cosy-combined-clean-head-01.xml`，`audit_report=(416,1)`。唯一实际跳过为本机目录符号链接权限不足，按已有精确条目登记；完整WAV八项和双工三项均实际执行。报告SHA256 `1f4fe0d86cc65978703919c17ec6fddee944ccfc01ffa05e914bb66349be7b3c`。预冻结18.05秒同数报告单独保留，不相加为新用例。

独立运行 [固定源夹具](../../../tests/fixtures/ad_full_wav_fallback_probe.py) 的新回执为同树 **`data/test-tmp/ai-ad-full-wav-fallback-clean-combined-03.json`**，SHA256 **`a98cee7858aad70bdfb0847893c576ca2be94ed7bf2062d20c2fb7582b5d2024`**。内含checkout_head=f751d3dc完整值、checkout_dirty=false及被测consumer原字节SHA256 **`dc32e2e7da288d652a148bbc039244e83aabbff5f7c4ccfcf82ba06c0fa13d18`**。固定上游仍为 `eb4b28c59ed7ed885258498cf757ce14352d620e`；真实WAV转换/CPU Opus，无网络、Torch、模型或音频落盘。

正常回退一次合成替身调用、三包、解码4320样本；首回调抛错一次/一包，failed/after_handoff，无重播。三个取消场景丢尾且不重试；空返回、生成抛错、坏WAV各保留原上游5次交付前重试、零包、failed/before_handoff。这些调用数不是模型/HTTP调用。没有把后续完成抹掉既有failed，未声称服务端已空闲或设备已播放。

独立审查回执 **`data/test-tmp/ai-cosy-clean-head-independent-review-01.json`** 核对源码归属、JUnit零失败、精确资源审计、原证明原字节及实际Python3.10.20导入共同投影/AD getter/启动状态，no_connection正确、无Torch。全 `src/longmemory`＋`scripts/development/xiaozhi` Python路径及规范化字节摘要现为 **`4bd3aec25205c76c3cfd52610d9645d21056e8ab93a82c4229ffa5d462cf2f56`**；本次新增投影与AD修复以及b218路径修复使它不同于旧证明外围回执。

管理原语15文件摘要仍为 **`1003fe901fa49bd2750242637b18744694f5bebdabfc3d06e0cf7a5eb262fdac`**，已核对本树 `data/test-tmp/ai-embedding-resource-managed-proof-20261021-02/management-verification.json` 原字节SHA256 **`875d1eb5f7750ddc3ef4a23a812997433bdb8182e22db7c64b44b4c4a266dcdc`** 及其rpc_source_sha256仍匹配。不改旧219项实测HEAD或完整源码摘要，不因外围变化重跑不受影响管理大组，也不将旧证明冒充本次UI/音频验收。

此后仅文档收尾，`src/scripts/tests/web` 与 f751d3dc 无差异。ROOT获得最终分支/HEAD后自行审查并推送候选、对该精确SHA运行既有workflow_dispatch；不要先快进主仓再拿b218已通过的Quality39625722258代替。新四项组件和一个合成主机浏览器模式保存用例、TypeScript构建与完整浏览器仍待该次CI。真实声音、连续性和插话仍由所有者另验，本轮未部署或动日用。
