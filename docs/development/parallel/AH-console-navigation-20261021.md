# AH：360 设备页导航失败的有界定位与诊断接力

2026-10-21。远程Quality `39530302377` 的精确360候选：143 scheduled，139 passed、3项既有资源skip、1 unexpected、0 flaky。失败位于 `console.spec.ts` 的文字聊天/统一导航流程，点击“设备状态”后原5秒内没有找到“设备与状态”heading。**360的远程导航原因仍未知**，没有把本地通过或后续候选通过解释为该失败已治愈。

原始证据在主项目 `local/archive/hy-advanced-release/20261021T020149Z-360eab8e-acbb73/quality-browser-failure.log`。日志只提供runner上的截图/trace路径；工作流没有上传artifact步骤，本轮没有取得远程截图/trace，不根据不存在的画面推断原因。完整远程日志SHA已绑定在AH ignored `data/test-tmp/ah-console-navigation-20261021/release-63ef0853/binding.json`。

## 本地实际结果与界限

AH起点 `a601e7f7`，完整前端tree与360同为 `2d06c0dd5081eab580618cfbca6978477f5d0d60`。使用既有Playwright1.62.1、Node24.19.0和已安装Google Chrome155.0.8059.85（Chromium引擎），没有可用的Playwright缓存Chromium，也未下载。与远程windows-2025/其下载浏览器不是同一机器条件。后端使用本AH源码、主3.12解释器及显式AH PYTHONPATH；每次随机临时端口、独立Fake数据库/资源、离线设备桥，未读取真实配置、个人库或连接日用端口。

有界诊断结果，均保留原5秒expect、零重试：

- 原完整聊天/导航流程1项通过，实际进入 `/device`，无确认框、页面异常或认证错误。后续圆屏预览Fake `/api/round-wallpapers/device` 的500发生在设备页通过之后，不能混为本次导航失败。
- 限定到失败步骤的4倍CPU降速诊断1项通过，未复现；随后核对远程前四个chat-workspace场景再执行该完整流程的顺序，5/5通过。这些是不同有界条件，未循环重跑凑绿。
- 初版诊断加入后，原console四项4/4通过；其后只加关闭/求值失败保护，最终精确增量的目标完整流程1/1通过。未将初版4项结果冒称最终源码重新完整执行。

首次ignored诊断配置因目录未声明ESM而加载失败，未执行浏览器，修复仅该ignored目录的package type；原件保留 `before-v1/`。实际浏览器基线从 `before-v2/` 开始。上述结果分别在 `before-v2/`、`focused-cpu4/`、`original-first-five/`、`actual-console-after/` 和 `actual-critical-final/`，含JSON/日志；保留的trace/截图均为本次本地合成运行，与远程runner证据区分。

## 提交的精确增量

代码提交 `63ef0853902722c99f2111e38f797b5a1ee90132`，前端tree `030ef1f193481e0663e154ae3142cb31bcce00f3`。相对360仅改 `web/react-chat/e2e/console.spec.ts`，没有根据未证实假设修改产品或就绪条件。

在原点击与原heading断言外增加命名step和失败时限量元数据：点击前URL/href、失败实际URL、document title、当前可见heading、加载占位、路由错误边界、草稿是否存在/为空、dialog情况、失败网络状态及console/page error。仅这个合成导航步骤装监听器并在finally卸载；不记录Cookie/header/token/请求正文或完整会话文本。每类事件、文本和heading有上限。

安装dialog监听器后明确dismiss，维持原先Playwright无监听器时的默认语义；页面已关导致dismiss失败会被接住，不自动同意离页。失败快照最多750ms，不能求值时给unavailable；诊断自身异常也不会覆盖最后重新抛出的原断言异常。原点击、后续功能断言、5秒expect、30秒test上限和零retry保持不变。750ms仅是主断言已经失败后的有界取证预算，不增加成功等待或重新点击。

失败证据通过 `[console-device-navigation-failure]` JSON直接进入CI日志，不依赖已丢失runner附件。没有新增外部action、工作流或依赖。

为验证新增失败分支，另外执行三项**明确注入的本地合成失败**，均如预期返回1、保留原5000ms heading异常，未将它们当作360复现：

- `controlled-unsent-draft/`：故意保留草稿，URL停在 `/chat-react`；记录confirm和非空草稿，无网络错误。
- `controlled-lazy-chunk/`：仅该独立Fake上下文把DeviceApp chunk回应503；URL已是 `/device`，记录503、资源失败及React Router错误边界。
- 最终源码 `controlled-snapshot-timeout/`：保留草稿并让辅助evaluate不返回；750ms后记录snapshot_timeout，仍以原heading断言失败结束。没有用诊断失败替换主失败。

两项前期受控验证发生在关闭/求值保护补强前；最终补强后实际验证了求值超时与正常完整目标流程。故障注入只在ignored副本，不进入提交用例。

## 精确验证与交接

最终定向e2e TypeScript检查退出0；TypeScript7显式传文件需要 `--ignoreConfig`，首次TS5112是命令前提错误，保留原日志，随后按固定工具提示修正命令。正式src类型检查、Vite离线构建退出0。默认收集护栏检查为13份spec/143项、零retry，没有增删功能用例；没有重复全套350或143项执行。

精确63ef构建在 `data/test-tmp/ah-console-navigation-20261021/release-63ef0853/`。45文件、1,839,032字节与此前ba37及944运行时逐文件SHA一致，规范产物tree `bcde5ee77a08fa513942c7f13ffe60885e7a3c4acfe237f5dac4975886679af1`，manifest `5e94e8fea73e850d7335feac0fc3e3f190e67a3e761cdce08b07986b0b308b00`。新binding SHA256 `4aa2d3d78569168bbc3ea159f5b9e611940bc916b5a98c0fe93ef042aa1ffef4`，包含实际本树提交、前端tree、各运行结果/日志摘要、远程日志摘要及逐文件产物。未把本地Fake后端当作360整仓后端组合验收。

本增量不需部署前端运行时。ROOT转AI审查后，和AI独立修复的backend fixture一起形成新的精确候选，再运行完整Quality；新候选若成功，仅说明它该次通过。没有替ROOT合main/推送，没有改e634的8个固件源码、审计补丁、0016 BIN、共享资源或日用服务，也未操作串口/设备。

共享文档manifest登记留ROOT整合；本独立记录人工逐项核对实际证据，不冒称已通过未登记文件的共享严格正文检查。相关前轮绑定见 [类型接口接力](AH-final-interface-20261021.md) 与 [0016冻结交付](AH-round-subtitles-20261021.md)。
