# Y：Hy 记忆管理重设计与受控管理适配

日期：2026-10-19（Asia/Shanghai）。会话 `01a153e0-5cf5-7763-b944-7031e8a1c548`，由当前进程 `CODEX_THREAD_ID` 核对。

**结论：Y 可独立实施的前端、管理适配、安全路由及合成验证已交付本地候选。V/X 底层和 Runtime 扩展仍待接线，不能按三方组合通过或日用可写验收汇报。** 默认写门保持关闭，没有操作日用服务、个人库、共享私有配置、设备或外部模型。

## 起点与保护

主会话串行移交 `local/worktrees/p-frontend-experience-20261015`（Y 树）。它是历史 P/S/W 隔离树，不是主检出，也不是新建工作树。重新核对移交时 tracked 干净、HEAD 为 `1dda701fc87df0d40be329bf5b67f724c876a577`、分支 `codex/w-hy-frontend-validation-20261019`，没有 Node/pnpm 任务进程。使用 `git switch --no-overwrite-ignore -c codex/y-hy-memory-ui-20261019 3126c651303fb3f72c5f49b749dd119e126d1712` 从指定已推送 main 精确提交开始。

没有 reset/clean、删除、安装、下载、联接或覆盖旧输出。旧 dist/test-results 共 174 个文件先记录逐项 SHA-256，收尾全部 174 个摘要仍相同。W 已保全的历史检查点及其他 ignored 证据保留原位。旧 W 分支仍指 `1dda701`，旧 S 分支仍指 `36ebf3a0c6bc784c7b5697c4b026c6b5a2817f82`；没有把同一分支 checkout 两个树。

本轮输出独占 Y 树 `data/test-tmp/y-ui-20261019/`，包括每次构建、组件日志、浏览器截图/trace、原产物摘要及 `validation-identity-v7.json`。前端命令 workdir 显式 Y 的 `web/react-chat`，Python/Git/文档命令显式 Y 根。未读取根目录未知 design-mockups 或其他未知文件。

## 设计依据与自审

使用 frontend-design、ui-ux-pro-max 和本树 project-doc-maintenance 技能，事前告知。技能检索返回 Minimalism & Swiss Style 的通用工具方向；只采用阅读层次、留白与键盘/对比建议，没有引入其字体或配色，更没有下载依赖。主题来自智慧圆屏的个人长期记忆核对，不做运营仪表盘。

沿现有 future 主题：背景 `#06111b`、正文面 `#0b1c2c`、次级面 `#102738`、正文 `#edf7fb`、次级文字 `#a2bac9`、青色强调 `#5ce5ed`；实现全部引用既有 token，其他主题继续继承。字体沿现有系统字体栈及 Microsoft YaHei，不新增字体、图标或动画依赖。正文为视觉中心，层号只在细节中解释。

```text
我的记忆                      刷新
Hy-Memory / 本次写入与回答使用状态
记忆条目 | 基本画像 | 记录与变化 | 处理状态
本页关键词 / 本页类型
条目正文 + 记录时间 + 来源数量       查看详情
上一页                       下一页
详情：正文 → 单条来源 → 变化 → 可用操作 → 原生标识
```

设计自审先去掉统计卡片和旧层号主导航；截图后压缩窄屏页头/筛选/导航，让正文更早出现；长内容列表预览、详情全文。来源选择改用带标签的原生选择框，避免抽屉内第二个 Portal 弹层吞掉 Esc；保留 Ant Design 外壳、对话框和其他表单。没有修改全站色板或聊天/声音/角色/设备功能。

## 已实现能力映射

| 用户任务 | 实现与实际边界 |
|---|---|
| 记住了什么 | 中立 ACTIVE 列表真实 offset/limit/total 分页，页面筛选明确限定本页，不用 SDK search 冒充只读全文搜索。未完整返回一页时给部分结果提示。 |
| 依据是什么 | 按选择读取一条平台来源，显示原始角色/时间/处理状态；未知、空关联与单来源失败分开呈现。助手原话明确不是用户事实。 |
| 基本画像 | 专属能力证明范围后才读取；聚合画像在自己的详情查看，不把聚合 ID 交给普通 get/update/history。未证明隔离时明确不可用。 |
| 记录与变化 | 平台管理操作账本和 SDK 单条历史分开；后者按需读取，空数组不证明从未变化，最多投影最近 100 条并提示。 |
| 处理状态 | 本次 Runtime 写/用开关、待完成回执、排队/运行数、最近状态与诊断代码。无数据不猜正常。 |
| 纠正/删除 | 专属扩展实现单条表单、请求编号、用户来源、串行修订检查、持久审计与独立读回；默认关闭。仅 l2_fact/l3_summary，不能批量清库，不把删除等同隐私擦除。 |
| 失败和并发 | 同请求/同载荷完成可重放，不再调用 SDK；异载荷同 ID/旧修订拒绝。异常或读回不符为 uncertain，重启 running 转 uncertain，不自动重试；未确认条目拒绝新的写请求。 |
| 回答追溯 | completed 纠正的真实用户来源通过管理账本叠加至 recall；running/uncertain 条目不注入回答，返回明确警告。未修改 SDK meta 或伪造旧原话。 |
| 页面兼容 | Hy 侧栏移除旧场景/画像层级入口；旧记忆书签先核对后端再去对应新视图，旧引擎保留原页面。配置尚未读到时不闪现旧 L1 管理。 |

L4/L5 是保留层，Graph/Intention/System2 未启用；无可用开关或假动作。旧引擎通用 correction/deletion 继续 false，因为它们要求原子修订比较。新方案叫“唯一拥有者串行修订检查”，不声称 SDK 原生 CAS（比较并交换）、跨存储事务、自动回滚或全量隐私删除。设计理由和代价见 [接线契约中的 ADR HY-UI-001](../hy-memory-management-contract.md)。

## 文件与接口

前端主体为 `features/memory/HyMemoryWorkspace.tsx` / `hy-memory.css`，旧书签守卫为 `MemoryDomainRoute.tsx`。`pages/MemoryApp.tsx` 依据后端切换新工作区；`ConsoleApp.tsx` 和 `AppShell.tsx` 只改必要记忆导航/路由。传输类型在 `api/types/memory.ts`，专属客户端在 `api/memoryEngine.ts`，共享 Cookie/CSRF、不自动重试写。

后端新增 `methods/hy_memory/administration.py`，`method.py` 保留 `HyAdministration` 公开导出兼容，并为 recall 补用户纠正来源与未确认隔离。`entrypoints/api/method_management.py` 只通过 Runtime 扩展调用，不直接拿 SDK 绕过守卫。路由在 `routes/memory_engine.py`：

| 端点 | 用途 |
|---|---|
| GET `/api/memory-engine/items?limit=25&offset=...` / `/items/{id}` | 既有中立列表与详情 |
| GET `/api/memory-engine/sources/{event_id}` | 既有单条授权平台来源 |
| GET `/api/memory-engine/hy/workspace` | 引擎能力 ∩ 启动权限 ∩ 当前写开关 |
| GET `/api/memory-engine/hy/profile` | 有明确隔离证明的聚合画像 |
| GET `/api/memory-engine/hy/operations` | 独立操作账本分页，可按 item_id |
| GET `/api/memory-engine/hy/items/{id}/history` | 单条 SDK 历史，先核对该条范围 |
| POST `/api/memory-engine/hy/items/{id}/corrections` / `/deletion` | 受控单条写，真实平台用户来源和 UUID 请求编号 |

HTTP 不接受路径/user/agent/source/角色/时间覆盖；未知参数、重复参数、非法修订/确认短语拒绝。401 会话、403 同源/CSRF/权限/暂停、409 修订或请求冲突、501 未接线/不支持、503 未确认或引擎失败分别处理。管理账本只位于可信引擎根 `management.sqlite3`，新库/备份随 state resource；未启用个人数据库迁移。

使用说明见 [Hy 记忆管理](../../guides/Hy记忆管理.md)，完整形状和接线要求见 [管理契约](../hy-memory-management-contract.md)。

## 验证与真实限制

Node `v24.21.0`，本树解析 Vitest `5.0.0`、TypeScript `7.0.2`、Vite `8.2.2`、Playwright `1.62.1`，均来自本树实体 node_modules/.pnpm，与声明一致。稳定 pnpm 入口为主会话已核对的 12.9.1，项目仍声明 11.19.0；Y 直接调用本地 Node CLI，没有触发包管理器下载/切换，不冒充 pnpm 11.19.0 干净重装验证。

package.json SHA-256 保持 `3b935512fe8abb810de9e35805c708976843416da2ce1cefe67f3463ce081541`，锁文件保持 `c0e083751833a86c21a0f4cfa7cf66d8a8621d1459b91a66991dcfbe6ad6fdd9`。生产构建 `build-v7` 独占新目录，44 文件摘要见 `validation-identity-v7.json`；保留共享 chunk 超过 500KB 与 outDir 位于项目外的既有非阻断提示，未改阈值或使用清空参数。

| 实际检查 | 结果与边界 |
|---|---|
| 后端选定 7 个模块：新 administration / HTTP 守卫、既有 Hy backend/bridge/process、中立 boundary、SDK offline | **89 passed，28.15 秒**。主项目 Python 3.12.13 只读复用，导入 Y/src；SDK 子进程来自 V 独立环境。全新合成库、随机回环端口，避开日用端口。 |
| SDK 离线模块 | 上述 89 中包含真实 hy-memory 2.0.3/Chroma＋模拟模型的写入/列表/详情/召回/重开；不代表真实模型质量、也不代表专属 update/delete 已经真实 SDK 接线验收。 |
| Vitest：HyMemoryWorkspace / MemoryApp / AppShell / API index | **4 文件 / 26 passed**。其中新工作区 11 项，既有 MemoryApp 11 项；其他 4 项兼容。不是拿旧 11 项替代新设计验收。 |
| `node node_modules/typescript/bin/tsc --noEmit` | 退出 0。 |
| `node node_modules/vite/bin/vite.js build --outDir <Y专属build-v7>` | 退出 0，1618 模块。没有覆盖旧 dist。 |
| Edge 155.0.4283.62 / Playwright 1.62.1 | **最终 8 passed，34.3 秒**，14 张稳定帧截图逐项摘要；API 全部合成拦截，无日用/模型请求。系统 Edge 验收不替代固定 Playwright Chromium/远程 CI。 |

浏览器覆盖 1920×1080、1366×768、390×844；大字号、窄屏大字号、长文、减少动态、键盘打开/焦点回到触发按钮、抽屉/模态焦点、单条来源、历史、分页/刷新恢复、加载/空/失败/能力拒绝、未知来源、重复提交与未确认隔离、旧画像书签，以及同页返回保留草稿/跨页返回离页警告。新模型/真实用户/设备/外部费用未验。

开发时保留的失败证据：初轮来源字段误把 get.source 当业务 namespace，被真实 SDK 离线测试发现并修正；修订排除读取遥测并有回归。初轮来源 Select Portal 吞 Esc，改原生选择框后宽/窄浏览器通过；初轮测试嵌套弹层在 NODE_ENV=test 固定 test-id 冲突，组件测试从可见表单定位，生产浏览器原生可访问名称另验。新增草稿测试先因测试 HTML 无 UTF-8、后因只返回到同页详情坐标而超时，修正测试前提后才验跨页返回，没有更改草稿实现去迎合错误前提。旧日志/截图未覆盖。

## V/X 接力和未验收项

1. V 在其独占 `worker/process_client/settings` 范围实现并实测 `management_capabilities/history/update/delete` 白名单及零外部调用语义。get_user_profile 已有 RPC，但隔离证明不足时必须 false。不要把实际 SDK 副作用未知的能力标 true。
2. X 在 Runtime 增加白名单 `administer_extension("hy_memory", operation, **args)`：持既有串行锁、检查 open/namespace/写开关/真实 user 来源、先归档来源，重复请求复用原 event 时间/会话。可信装配才可选择 `HyAdministration(..., serialized_writes=True)`；默认 false 不变。
3. 三方组合验证源角色/隔离、CSRF/启动权限/写暂停、并发旧修订/重复与异载荷请求、partial commit/重启 uncertain、纠正来源进入 recall、未知条目不注入和所有备份资源。当前 HTTP 测试的 Runtime 扩展是显式替身，不能冒称 X 接线通过。
4. 未确认条目没有自动解锁/回滚 API；需明确后续人工核对方案。源码指纹并非跨 SDK 存储事务。列表 ACTIVE-only、全库检索和平台来源全量浏览未实现，不读旧库补齐。没有新增重试入口绕过守卫。
5. 本说明、接线契约、Y 报告待 X 按本批变更加入正式文档清单，关联前端/管理/测试源码；Y 未改 `docs/documentation-manifest.json`、AGENTS、根 README/CHANGELOG/ROADMAP 或 V/X 专属文件。主会话安排组合审查、main 整合/推送和受控日用切换。

## 提交与追溯

| 任务 | 本地提交 | Y 验收 | main / 会话 |
|---|---|---|---|
| 可先接力的接口契约 | `dee2cf4` | 文档与实际 SDK API 核对；随后在实现提交更新契约 | main 待主会话；Y `01a153e0-5cf5-7763-b944-7031e8a1c548` |
| 重设计、受控管理适配和测试 | `b1d9c784f6338bc58265d14b0bcc22df88e9960e` | 上述代码候选上的合成/离线/浏览器验证；V/X 组合待验 | 同上 |
| 窄屏与截图自审修复 | `4709c0dcdbbf3228983e667225a1ee5d329c339d` → `505277d6f7ac98f901bf51b70ce26500867499b8` | 仅记忆页样式、字数提示与确定的浏览器证据；最终 UI 11 项复测通过 | 同上 |
| 最终交付记录 | 本报告所在本地提交，完整 SHA 随最终回复 | 文档链接/差异与敏感内容收尾见下 | 同上 |

Y 只提交自身分支，不 merge main、不推送、不向 V/X/主会话发送工具消息。没有宣布主会话已接受、已切换或已归档；工作树、分支、旧输出和本次证据保留。


## 收尾补记

实现候选由 `b1d9c78` 加两次窄范围自审修复构成。最终代码身份为 `505277d`（上表完整 SHA），生产输出为 `build-v7`。89 项后端检查发生在同一后端源码上；4 文件 26 项组件检查后只改记忆页布局/字数提示，最后对当前新工作区 11 项再次复跑通过，类型检查和生产构建也重新通过，没有把旧版本输出冒充当前输出。

当前生产构建 44 文件、稳定帧截图 14 张、源码提交和原产物核对结果保存在 `validation-identity-v7.json`。浏览器最终输出为 `browser-v7`：`hy-items-{1920,1366,390}.png`、对应 `hy-source-*`、`hy-correction-large.png`、`hy-profile.png`、四张加载/空/失败/能力拒绝、`hy-uncertain.png` 和 `hy-mobile-large.png`；均为合成内容。已看图复核窄屏、来源抽屉和大字号编辑框，没有以测试绿代替图像自审。

最终自审过程还捕获过共享 `.page-action{width:100%}` 挤压窄屏标题的回归，已由更具体的记忆页规则修复；加载测试改为显式响应门控而非 300ms 猜测。来源图改为截图 API 的有限动画完成帧，防止把过渡中间帧当终态；大字号计数与确认文字的拥挤改为独立“最多1000字”提示。上述修复后全 8 项浏览器重新通过，原失败证据保留。

正式三份文档 `--only ... --strict --json` 退出 1：检查正文数 0，3 个 `unlisted-document` warning 和 3 个 `unknown-selection` error，原因都是 X 尚未登记新文档，不是链接成功证明。为独立核对正文，直接调用本树检查器 `check_links/check_old_paths`（读取正式清单的既有规则、不给正式清单写入）检查三份文档，发现 0；结果保存为 `docs-body-check.json`。待 X 登记后须正式 strict 重跑，Y 不越权修改清单。

最终新工作区敏感模式扫描无真实密钥匹配，`git diff --check` 通过；本轮没有删除文件。原 dist/test-results 174 项摘要保留不变；本次生产构建/截图输出仅位于 Y 的独占证据目录。未查询/触发远程 CI，也没有安装、联网模型调用、日用启停、配置切换或设备操作。
