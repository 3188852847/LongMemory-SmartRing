# AH：5c每日回顾流程超时的整段查询窄修

2026-10-21。代码提交 `b806fdc66253214ae56e2fd3ff33fbb7b9ec5bfb`，前端tree `b10d606b0860e7a6d8528c738011375082db6eb5`。本轮只改 `web/react-chat/src/pages/MemoryApp.test.tsx` 中“从当天回顾直达已有的追加式纠正确认窗”，不改生产UI、服务、固件、依赖、CI调度或超时。

## 已确认事实

ROOT提供5c main Quality `39576502051`：backend成功，component 63文件349通过/1失败，目标用例5000ms整项超时、报告5380ms；browser未运行。原始日志位于主项目 `local/archive/hy-advanced-release/20261021T092143Z-5c5f6fa4-732b85/quality-5c-failure.log`，本轮保留原件并将摘要绑定。ROOT既有f159候选350通过、f159 main frontend/browser通过的记录也保留；不靠重跑改写5c失败。

实际核对本AH起点、`5c5f6fa498d9eb82f60e94a727e67ceb42ede030`、`f1595515dd2ccf9111792b5d7e1a399057e5518f` 的该文件Git blob完全一致：`f8caddd6d845f777e5395c2379f4a17d3f1a1b44`。不能将文件差异当作上述通过/失败差异的原因。本地没有完整复现5c runner当时的资源状态或精确失败落点。

## 有界整段profile

证据根为本AH ignored `data/test-tmp/ah-memory-flow-ci-20261021/`。只调用既有Node24.19.0、Vitest5和本树依赖；不装包、不接日用端口/个人数据。仪器包裹真实query、render、fireEvent、isInaccessible和getComputedStyle并返回原结果，同时记录进程CPU及事件循环延迟；没有mock可访问性、缓存样式结果或改变CSS。计时包括初始任务定位、日报所有断言、回看/审计、L0核对、L1切回、日报再入和纠正弹窗，不只测最后按钮。

先以Memory目标用例和未修改RoundDisplay皮肤用例形成两项实际UI负载，比较普通本地2/1 worker。过滤项只用于诊断，不计作完整执行通过：

| 条件 | Memory流程wall | 进程CPU | 外层样式调用/耗时 | 事件循环p99 |
| --- | ---: | ---: | ---: | ---: |
| 原文件，普通2 worker | 1961ms | 2625ms | 191 / 1082ms | 1116ms |
| 原文件，普通1 worker | 1959ms | 2500ms | 191 / 1091ms | 1124ms |

CPU是进程累计用户/系统时间，含V8工作线程，不能当单线程CPU百分比。首轮输出文件名受Vite动态URL转换影响，Memory实际原件保留为 `undefined`；对应结果JSON正常。后续只修ignored仪器的输出路径，使用独立label/PID文件，不覆盖原件。

原2-worker完整链路中，任务导航findByRole约235ms，全屏“查看回答与证据”角色查询103ms；普通render约97ms，几次交互27–70ms，末端弹窗等待98ms。真正文案可见性检查943ms，其中真实样式解析约928ms，是最大同步热点，但不是流程全部成本。单worker普通测量接近，不能据此声称改1 worker必然改善本机。

尝试过单次同步样式复用，完整profile没有显示足够收益，已撤回临时helper和参考测试，没有交付自定义可访问性替代物。最终窄修的普通2-workerprofile中样式调用为165次，但wall约2877ms、样式耗时1560ms，存在明显波动；**不把调用次数减少包装成已证明的固定耗时提升**。

随后仅对本次新建诊断终端及其子测试进程施加单逻辑CPU affinity，顺序量化相同两条流程的资源竞争，保持各自5秒限制、零retry：

| 受控单逻辑CPU | Memory目标 | RoundDisplay负载 |
| --- | --- | --- |
| 2 worker | 6922ms，超时失败 | 5886ms，超时失败 |
| 1 worker | 3638ms，通过 | 3541ms，通过 |

这组确实出现同类测试超时，证明受限CPU下两个jsdom/Ant Design进程争用足以越过5秒；它不是5c机器实际CPU状态的证明。所有原始失败保留为 `onecpu-2w-*`，没有重跑覆盖。affinity在finally恢复，之后新终端实际读到完整mask `16777215`；未更改既有服务、全局环境或CI worker配置。ROOT要求CI调度保持不变，本轮未修改工作流。

## 提交范围与保留的语义

- 初次任务定位改为按准确aria-label等待原生nav，再明确断言原生/声明的navigation角色及原库isInaccessible真实CSS/祖先可见性；不跳过就绪等待。
- 日报链接、计数、归档说明和删除审计文案限定在已取得的“每日回顾”region；保留原链接角色与href断言，减少全屏扫描，也避免被其他任务的同文案满足。
- 保留跨视图两份事实文本计数、L0核对和日期、切回L1/日报、禁用就绪等待、纠正弹窗原说明等全部业务断言；补核原生纠正按钮角色。原文案isInaccessible、hidden/aria-hidden祖先检查保留，没有再绕开CSS。

不拆分原流程预算，不加retry、skip、通用等待、全局隐藏配置或可访问性mock。生产实现与原13项MemoryApp测试数不变。新的文件blob为 `79e119abcdd2f3092616bf7a5c7ab4648fc87ce9`，测试前raw SHA和Git blob另存 `test-source-binding.json` 并与提交实际核对。

## 必要全量与交接

资源探针结束并恢复后，原标准配置、不加载profile hook、无限制CPU、`--maxWorkers=2` 的一次完整运行：**63文件350/350，0失败/跳过**；目标用例2227ms。`tsc --noEmit`退出0。结果 `full-final.json`、`full-final.log` 和 `types-final.log` 保留，不额外循环全量；没有运行/冒称新的browser或远程Quality通过。

精确代码提交的离线构建在 `release-b806fdc6/`，45文件、1,839,032字节，逐文件与ba37/944运行时一致。规范产物tree `bcde5ee77a08fa513942c7f13ffe60885e7a3c4acfe237f5dac4975886679af1`，manifest `5e94e8fea73e850d7335feac0fc3e3f190e67a3e761cdce08b07986b0b308b00`；新绑定SHA256 `dcd6ff2dc29bb1a93305a40b909fdacf2c32e1ea496c784e4ae4f374eadc49b7`。无需因本增量重新部署前端运行时。

本轮交付是可审查的整段查询窄修及资源证据，不保证任意拥挤runner都能在5秒内完成，也不宣称治愈未完整定位的5c失败。ROOT/AI将与AD独立交付整合成新精确候选再验；不重复AD备用时钟问题，不操作main/推送、日用pipeline、共享配置、串口或0016源码/BIN。共享文档manifest由ROOT/AI整合登记，本记录不冒称未登记文件已通过共享严格正文检查。
