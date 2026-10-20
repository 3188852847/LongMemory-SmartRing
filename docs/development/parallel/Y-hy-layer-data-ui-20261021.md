# Y：Hy 分层实际内容与页内滚动

日期：2026-10-21。阶段：两项前端实现与关键合成回归完成，源码冻结交还主会话；不是最终组合/日用验收。

SDK 指软件开发包；RAW 指 Hy 原生保存的原始记忆；向量存储与未打开的图库分开核对。

## 接手与范围

重新核对原树 HEAD `dedb06488dea0b787906e49e9160689531eba259`（Z 冻结分支）、tracked clean、无本树 Node/Python/pnpm/Edge 任务。新分支 `codex/y-hy-layer-data-ui-20261021` 精确从 main `34b2111d646cb1672bdad62603174e0da7c57f6b` 创建，未 reset/clean。保存原 dist/test-results 与全部既有 Y/Z 测试证据共 13 根目录、1468 文件摘要；不覆盖、删除或搬移旧证据。依赖声明/锁摘要已保留，沿用实体 node_modules 与已安装 Node v24.21.0，不安装、下载、升级或联接。

本树唯一所有权为 `web/react-chat/**` 和本报告。新输出独占 `data/test-tmp/y-layer-data-20261021/`；不改后端、正式 manifest、主仓生产、私有配置、个人数据、日用服务或设备。不 merge main、不推送、不向其他会话发送工具消息。

## 滚动修复里程碑

真实 Edge 在 1366×768 与 390×844 更大字号均复现：滚到非零位置后点击运行节点，URL/选中变化，但 scrollY 变为 0。根因是 HyMechanismsWorkspace.choose 的 setSearchParams 未指定 preventScrollReset，触发既有 ScrollRestoration 默认回顶。

只为 HyMechanismsWorkspace 和 HyMemoryWorkspace 的页内查询更新增加 `preventScrollReset:true`，保留 push 历史与 URL 坐标；没有全局关闭 ScrollRestoration，也没有增加主动回顶或锚点。最终内容页仅在显式点层后、内容标题仍在屏外时适度移入该内容并交给标题焦点，不回到整页顶部；刷新/前后退不触发这种定位。节点/完整目录/层选择/标签，以及已有记忆分页和详情使用相同页内导航策略。

刷新场景又实际发现既有恢复遗漏：懒页面未变高时保存位置被夹成 0，RouteWorkspace 的二次恢复只认内存 Map，刷新后 Map 丢失。现从同一个显式 ScrollRestoration 会话存储键载入最多 200 个有限非负坐标，并避免初次 layout 用 0 覆盖待恢复坐标；继续沿用已有 ResizeObserver 和 wheel/pointer/keyboard 即取消逻辑。只保存坐标，不记录正文。真实跨路径仍回顶并将焦点给 main。

验证：修前两屏真实失败日志 `scroll-before-browser.log`；修后 `scroll-fixed-browser-v2.log` 两屏通过，断言真实非零 scrollY 节点/目录点击前后变化小于5px，层和标签选择、浏览器返回及刷新恢复、桌面实际跨页回顶与主内容焦点。截图在对应目录。真实指标：1366px 节点点击 `105 → 105px`，390px 更大字号 `556 → 556px`，记录于 `scroll-metrics-browser.json` 的附件；修前均变成 0。TypeScript 与 `scroll-fixed-build-v2/` 生产构建通过。组件/草稿回归 `scroll-components-v1.json`：26 项通过、0 失败。构建均为独占 outDir，生产 dist 未动。

## 分层内容设计与接口依赖

上一轮只有目录与机制解释，未满足“看每层里面保存了什么”。本轮主视图改为所选层的真实内容：层选择 → 该层计数和读取范围 → 有界服务端分页正文 → 详情及可得来源/版本。机制说明作为次级展开。L0 聚合画像与条目列表分开，L1 必须是 SDK RAW，不能拿平台原话账本代替；关闭/保留是配置属性，不作为该层空数据证据。

保持既有 future 颜色 token（#06111b / #0b1c2c / #102738 / #edf7fb / #a2bac9 / #5ce5ed）与系统中文字体，不全面改样式。宽屏以可读正文和详情为主，390px 大字号顺序阅读。设计技能检索命中“返回应符合预期”，应用其保留历史原则；泛化平滑锚点建议不适用本次页内保持视口，因此不采纳。

已读取主会话交接的 AA `docs/development/hy-layer-data-contract.md` 和 `methods/hy_memory/layer_data.py`，按其实际字段接线，未摘取或改写 AA 代码。本次核对契约 SHA-256 为 `c5665a42bb91b9c726dbdff1df67a81cfae5a7f61eb1afa63b72e33feaccd0bb`。后端不提供的能力逐项解释具体缺口，不把混合 ACTIVE 第一页过滤称完整分层；不为查看启用处理/写入或调用模型。总览/聊天继续只用轻量身份。

追溯：滚动修复 → `ced8ba53703294b567e41ddb260a632908acc280` → 分层内容实现 `52c5c79ef647afb12969a518ce6f51ce155ec04e` → 最后视口断言与简化空态见交接 HEAD → Z 组合审查 → main 合入待主会话记录 → 会话 `01a153e0-5cf5-7763-b944-7031e8a1c548`。


## 逐层内容实际实现

- [hyLayerData](../../../web/react-chat/src/api/hyLayerData.ts) 定义 schema 1 的层页/详情协议和请求范围校验；[MemoryEngineApi](../../../web/react-chat/src/api/memoryEngine.ts) 只增加两个专属 GET：`/api/memory-engine/hy/layers/{layer}?limit=20&offset=...&state=...`、`/api/memory-engine/hy/layers/{layer}/items/{item_id}`。不修改旧 items/profile/history 协议，不接受任意用户、助手、来源或路径参数。
- [HyLayerBrowser](../../../web/react-chat/src/features/memory/HyLayerBrowser.tsx) 仅在打开分层标签后的所选层挂载读取。L0 展示完整可读版本合并的字段、每个字段可得来源及其原生版本；null和空文本分别保留展示，来源版本未知时不构造链接；聚合句柄 profile、实际链头和普通版本 ID 分别呈现，聚合份数与存储版本数不同。L1 展示真实 SDK RAW，来源账本仍经显式单条读取另验，不互相冒充。
- L2/L3 以及 L4 历史、L5 保留、L6/L7 存量沿真实层端点读取。默认 all 原生状态，可选 active/superseded/negated/conflicted/shadow/archived；L0 仅 all。生成状态、读能力、数据状态、覆盖范围、总数和计数范围独立解释；选择器上的“机制”标记不代替内容 API 的生成声明。
- 每页最多20条，正文按后端有界内容显示，列表1024、详情32768字符上限与原文字符数/截断标志可见。实际原生层类型、状态、当前/历史版本、存储/记忆/生效/失效时间均有位置；缺失时间不补造。
- 页号与 layer/state/offset/item 坐标保留 URL；跨层或状态变更清除不适用的旧分页/详情。页面和详情不展示另一层或失败刷新后的旧内容；未确认身份时禁止自动读取及手动绕过门控。分页过渡保留基本阅读高度，短末页不会因整体布局骤然塌陷回到页顶。
- 详情提供同层原生版本关联、L0版本摘要到真实版本详情、可证明的平台来源和关联 RAW 的真实请求。普通详情没有 versions 时不造完整历史；关联越范围404不从其他层补读。来源选择绑定层和条目坐标，切换后不串用前条来源。
- L6/L7 只能读向量范围时，明确提示图库未打开、总数未知；空页不代表整层为空。L0范围证明不足/历史超限/字段超限为不可读，既不显示空画像，也不扩读其他范围。繁忙、失败、协议错层与真实无记录分开，有明确手动重试，不自动轮询。
- UI 将层内容放在机制说明之前，装配说明和本层代码依据折叠为次级内容。没有纠正/删除/启用/模型操作，不新增依赖或全面改样式。

## 本轮验证与实际限制

输出根目录为本树 `data/test-tmp/y-layer-data-20261021/`。仅用实体依赖的直接 CLI 与已安装 Edge，浏览器 API 全部拦截成合成响应，独立临时端口/临时浏览器 profile，未连接日用服务、个人库或设备。

- `layer-components-v3.json` 通过本层分页、聚合/原生版本、RAW、来源、关闭仍有数据、保留/历史真空、范围拒绝、未知总数、繁忙手动恢复、截断、404和身份门控。全套 `frontend-all-v2.json`：59文件、308项通过、0失败；最后空字段/未知版本来源与选层显露的增量在 `layer-components-v5.json` 对4个受影响文件26项回归通过。首轮全套有一个测试对页面与抽屉重复的404文本使用全局单元素选择器，已改为抽屉范围断言；没有改变实现来迎合错误前提，原失败结果保留。
- TypeScript 与 `layers-build-v6/` 生产构建通过；保留既有大 chunk 提示，没有扩大到无关构建优化。构建输出独占，原 dist 未覆盖。
- `layers-browser-v6.log` 全部25项通过，含三屏1920×1080、1366×768、390×844更大字号；真实分页/未知及末页数量、原生状态筛选、详情/单条来源/版本/RAW、L0合并而非链头diff、L6/L7部分覆盖、加载/空/忙/错误/范围拒绝/错层、404和长正文截断；保留旧引擎及旧记忆管理、草稿保护和全站轻量身份回归。
- 新增键盘覆盖 Enter 打开详情、Escape 关闭并回到触发按钮；浏览器后退/前进恢复层和详情，刷新恢复分页与非零视口。`layers-profile-keyboard-browser.log` 4项补充通过，最终v6完整25项已包含这些检查。
- 已人工看桌面正文、390px大字来源、L0聚合/原生版本和部分范围截图；正文、边界、来源可读，整页scrollWidth检查无横向溢出。所有截图/trace/日志均保留，失败阶段未覆盖。刷新测试曾只临时改DOM字号导致刷新恢复到标准字号、原目标坐标超出短布局；已改用真实外观偏好键和Provider事件，断言大字号在刷新后仍保留，未为错误前提关闭或放宽生产滚动恢复。
- `preservation-and-scope.json` 复核原1468个文件全部摘要不变、package/lock不变、修改限前端与本报告、秘密模式扫描无发现。最终源码/构建逐文件清单及绑定见独占输出 `production-binding-v7.json`、`source-files-v7.json`、`build-v7-files.json`；完成后以实际绑定字段为准。

本轮是前端到精确契约的合成验收。AA 的真实离线 SDK、范围证明、进程/关闭、后端测试与管理原语指纹变更由 AA/Z/主会话验证；Y 没有连接真实库或证明某个个人层实际已有数据，也没有重签生产 proof、发布或切换日用。真实所有者内容与实际服务体验须在组合审查和正式交接后验收。

本报告直接链接检查0发现；窄范围strict检查实际返回未登记/未知选择，等待主会话登记，没有宣称strict通过。正式 manifest 由主会话/Z统一登记，本会话只改本报告，不改根 README/CHANGELOG/ROADMAP。保留所有实体依赖、分支、工作树和新旧ignored证据，冻结后由主会话串行交给Z，Y不继续占用。


## 最终交还

AA 已冻结 `6d2df85` 与 `5126862d3831f8f3cac15858c6c93ca8150e0e12`，本树未摘取这些提交；主会话串行交Z组合。前端实现提交为 `52c5c79ef647afb12969a518ce6f51ce155ec04e`，早期滚动提交 `ced8ba53703294b567e41ddb260a632908acc280` 可独立审查；最终本树 HEAD 由交接消息及绑定 JSON 记录。

最终关键浏览器 `layers-final-key-browser.log` 6/6 通过，硬断言 L0实际字段、L1/L2/L3/L4/L6正文及L5/L7真实空/未知说明进入视口；最后为状态说明换成较小的空态图，避免图库边界提示把未知说明压出屏幕。`layers-mobile-content-browser.log` 2/2 进一步硬断言桌面/390px大字点层后正文进入视口，同时保留节点不跳顶、前后退/刷新检查。没有为此扩大到新产品功能或全仓样式。

源码提交后重新生成 `layers-build-v7/`，要求与已测 `layers-build-v6/` 全部产物逐字节一致；manifest为 `.vite/manifest.json`。绑定 JSON 保存精确源码提交、前端 Git tree、共享 `web/assets` Git tree、实际构建输入字节、逐文件及整树SHA-256、Node/工具版本和浏览器证据路径。此路径均在本树 `data/test-tmp/y-layer-data-20261021/`，未覆盖正式 dist。

最后合成浏览器 server/worker 由 Playwright 完成后退出，PID清单在 `final-browser-pids.json`；交还前以 `process-check.json` 核验这些PID及本树进程。Y不停止其它会话或日用服务，不删除依赖/产物。报告strict的未登记待办和真实服务未验收边界保持上述记录。
