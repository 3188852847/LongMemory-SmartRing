# Y：Hy 分层实际内容与页内滚动

日期：2026-10-21。阶段：滚动里程碑完成，分层内容接线进行中；不是最终组合验收。

## 接手与范围

重新核对原树 HEAD `dedb06488dea0b787906e49e9160689531eba259`（Z 冻结分支）、tracked clean、无本树 Node/Python/pnpm/Edge 任务。新分支 `codex/y-hy-layer-data-ui-20261021` 精确从 main `34b2111d646cb1672bdad62603174e0da7c57f6b` 创建，未 reset/clean。保存原 dist/test-results 与全部既有 Y/Z 测试证据共 13 根目录、1468 文件摘要；不覆盖、删除或搬移旧证据。依赖声明/锁摘要已保留，沿用实体 node_modules 与已安装 Node v24.21.0，不安装、下载、升级或联接。

本树唯一所有权为 `web/react-chat/**` 和本报告。新输出独占 `data/test-tmp/y-layer-data-20261021/`；不改后端、正式 manifest、主仓生产、私有配置、个人数据、日用服务或设备。不 merge main、不推送、不向其他会话发送工具消息。

## 滚动修复里程碑

真实 Edge 在 1366×768 与 390×844 更大字号均复现：滚到非零位置后点击运行节点，URL/选中变化，但 scrollY 变为 0。根因是 HyMechanismsWorkspace.choose 的 setSearchParams 未指定 preventScrollReset，触发既有 ScrollRestoration 默认回顶。

只为 HyMechanismsWorkspace 和 HyMemoryWorkspace 的页内查询更新增加 `preventScrollReset:true`，保留 push 历史与 URL 坐标；没有全局关闭 ScrollRestoration，也没有增加主动回顶或锚点。节点/完整目录/层选择/标签，以及已有记忆分页和详情使用相同页内导航策略。

刷新场景又实际发现既有恢复遗漏：懒页面未变高时保存位置被夹成 0，RouteWorkspace 的二次恢复只认内存 Map，刷新后 Map 丢失。现从同一个显式 ScrollRestoration 会话存储键载入最多 200 个有限非负坐标，并避免初次 layout 用 0 覆盖待恢复坐标；继续沿用已有 ResizeObserver 和 wheel/pointer/keyboard 即取消逻辑。只保存坐标，不记录正文。真实跨路径仍回顶并将焦点给 main。

验证：修前两屏真实失败日志 `scroll-before-browser.log`；修后 `scroll-fixed-browser-v2.log` 两屏通过，断言真实非零 scrollY 点击前后变化小于 5px、完整目录/移动选择、层和标签切换、浏览器返回及刷新恢复、桌面实际跨页回顶与主内容焦点。截图在对应目录。TypeScript 与 `scroll-fixed-build-v2/` 生产构建通过。组件/草稿回归 `scroll-components-v1.json`：26 项通过、0 失败。构建均为独占 outDir，生产 dist 未动。

## 分层内容设计与接口依赖

上一轮只有目录与机制解释，未满足“看每层里面保存了什么”。本轮主视图改为所选层的真实内容：层选择 → 该层计数和读取范围 → 有界服务端分页正文 → 详情及可得来源/版本。机制说明作为次级展开。L0 聚合画像与条目列表分开，L1 必须是 SDK RAW，不能拿平台原话账本代替；关闭/保留是配置属性，不作为该层空数据证据。

保持既有 future 颜色 token（#06111b / #0b1c2c / #102738 / #edf7fb / #a2bac9 / #5ce5ed）与系统中文字体，不全面改样式。宽屏以可读正文和详情为主，390px 大字号顺序阅读。设计技能检索命中“返回应符合预期”，应用其保留历史原则；泛化平滑锚点建议不适用本次页内保持视口，因此不采纳。

等待 AA 经主会话提供精确契约，不先猜 URL/字段。接线所需事实：层原生类型、读取能力与拒绝原因、计数及确切范围、分页边界和坐标、内容/时间/状态、真实详情及来源/版本能力、L0 独立画像隔离、L1 RAW 读取与隔离证明。后端不提供的能力逐项解释具体缺口，不把混合 ACTIVE 第一页过滤称完整分层；不为查看启用任何处理/写入或调用模型。总览/聊天继续只用轻量身份。

追溯：滚动修复 → 小提交待补 → 本轮两项目标最终提交待补 → Z 组合审查 → main 合入待主会话记录 → 会话 `01a153e0-5cf5-7763-b944-7031e8a1c548`。
