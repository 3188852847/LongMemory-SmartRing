# AH：最终前端类型接口接力与运行时绑定

2026-10-21，ROOT授权的有界短阶段。AI软件接口参考 `0970e5bf5f5c4672344bf74377eb505f00a676fe`；仅把 `web/react-chat/src/api/types/device.ts` 更新为该提交的精确Git blob `0cd6ae2c0fc8e4ab5bec74c76999b523e06d36fb`，本树独立提交 `ba37f972401af4ca064947cbeffb1f0ccc4d19dc`。文件SHA256 `5197f21b0d0754f4965e372655d85074ceec5be600e43d0d8e9cc18455ef564d`。相对e5f前端仅这一个文件变化：DeviceStatus新增可选诊断摘要和相应TypeScript类型。

实际构建来源是AH的ba37，不是AI整仓097。双方完整 `web/react-chat` Git tree均为 `2d06c0dd5081eab580618cfbca6978477f5d0d60`，已实际核对；未把097的后端、脚本或固件接入AH，也不宣称构建或验证了097整仓。

使用既有固定依赖和已安装Node 24.19.0实体，直接执行本地tsc/Vite CLI：`tsc --noEmit`及正式Vite离线构建均退出0。当前默认Node为24.21.0，因此显式调用24.19.0；未安装、升级、联接依赖或修改全局环境，未运行pnpm。原632个依赖链接仍全部在AH独占工作树内。

新独占产物目录为 `data/test-tmp/ah-release-interface-ba37f972-20261021/`。45文件、1,839,032字节，与e5f既有运行时逐文件SHA全部一致，也保持944运行时基准：

- 规范产物tree SHA256：`bcde5ee77a08fa513942c7f13ffe60885e7a3c4acfe237f5dac4975886679af1`。
- manifest SHA256：`5e94e8fea73e850d7335feac0fc3e3f190e67a3e761cdce08b07986b0b308b00`。
- 264资产引用全部存在，固定凭据/私有路径/fixture标记扫描0发现。
- 新 `release-binding.json` SHA256：`6c8465822e2c8d701f7d1ded11760ce600419c92028f4d795d6cb51b8503ad8f`。

绑定记录包含真实AH HEAD、共同前端tree、AI参考提交及接口blob、固定依赖、逐文件清单、类型/构建日志摘要和e5f基准绑定。之前350项组件结果继续注明实际来源e5f/tree b675，浏览器140通过/3项既有Otto跳过及独立chat4项继续保留原实际源提交；本轮未重跑它们，不把旧截图或旧测试结果冒充ba37新跑。d286首次资源争用失败原件亦保留，见 [CI可见性接力](AH-ci-visibility-20261021.md)。

本纯类型增量没有运行时字节变化，无需为它重新部署前端；不能把这个结论扩展为后端装配或设备候选可以跳过更新/验收。C++8文件、两份审计补丁及最终BIN冻结不变，见 [0016交付](AH-round-subtitles-20261021.md)。未操作日用服务、串口、设备、main或推送。共享文档manifest登记仍由ROOT整合；本记录未假称已通过该共享清单的严格正文检查。
