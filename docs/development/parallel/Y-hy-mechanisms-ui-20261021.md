# Y：全局 Hy 身份与机制探索界面

日期：2026-10-21。阶段：前端实现、合成验收和源码绑定完成，已冻结待 Z 组合审查；不代表日用联机或真实记忆验收。

本文 SDK 指软件开发包；worker 指承载引擎工作的独立执行进程；Runtime 指当前应用运行实例。

## 范围与起点

主会话串行交还 `local/worktrees/p-frontend-experience-20261015`，重新核对 tracked 干净、原 Z HEAD `8706c10f1687955c359732de479d9aeeaad6be7e`、无本树 Node/Python/pnpm 任务。保全旧 dist/test-results 174 项摘要和 ignored 状态。新建 `codex/y-hy-mechanisms-ui-20261021`，精确从 main `eaa65b5b2979add8fd513bba07e19e64d5afa36b` 开始。

只修改 `web/react-chat/**` 和本报告，不改后端、正式文档清单、私有配置、个人库、日用服务或设备。输出独占 `data/test-tmp/y-mechanisms-20261021/`；复用实体依赖，不安装、下载、联接，不覆盖旧 dist/test-results。未合入 AA 提交，未 merge main、未推送或发送跨会话工具消息。

## 最终设计与文件

- [MemoryEngineProvider](../../../web/react-chat/src/app/MemoryEngineProvider.tsx) 在 RouteWorkspace 提供唯一全站身份，严格解析轻量 `/api/memory-engine/identity`。冷加载、失败、繁忙、未初始化、未配置各自保留含义；错误后已有身份保留为“上次确认”，未知不冒充旧引擎。聊天主体不等待身份完成才挂载。无轮询、失败不自动重试；用户可手动刷新，成功身份过期后跨路径按需复核。
- [AppShell](../../../web/react-chat/src/components/AppShell.tsx)、总览、聊天状态栏、旧记忆书签统一使用该身份。Hy 全站显示“我的记忆 / 记忆机制”；旧引擎保留原入口。只有明确确认的旧引擎可读旧 L1 统计；Hy 总览/聊天既不请求旧统计，也不请求 `/items?limit=1` 来计数。数量未知显示未扫描和真实管理入口。
- [MemoryApp](../../../web/react-chat/src/pages/MemoryApp.tsx) 仅在用户打开管理页后读取原 `/api/memory-config`；机制页不读它。身份与管理配置冲突时停止挂载旧界面及旧库读取。中立/旧记忆入口不根据 `method=null` 猜测方法名。
- [HyMechanismsWorkspace](../../../web/react-chat/src/features/memory/HyMechanismsWorkspace.tsx) 懒加载到 `/memories?view=mechanisms`，没有新增独立服务端路由。URL 保存 `mechanism_tab`、`mechanism`、`layer`，直接打开、刷新和返回可恢复选择。
- [hyMechanisms](../../../web/react-chat/src/api/hyMechanisms.ts) 校验协议、锁定 SDK 版本/提交、状态枚举、未知计数与唯一标识。机制目录动态遍历全部返回项，未知分组也可浏览；测试额外追加机制验证不会只显示写死的少数目录。
- [ChatObservability](../../../web/react-chat/src/features/chat/ChatObservability.tsx) 区分平台来源与 Hy 层级，识别 Hy 检索名，不再将其叫关键词基线；缺失召回字段保持未知，平台保存的列表不等于 SDK 全轨迹、最终注入或回答采用。
- [HyMemoryWorkspace](../../../web/react-chat/src/features/memory/HyMemoryWorkspace.tsx) 在显式请求 SDK 历史前核对机制声明；关闭/未知时不调用 history 猜开关，清楚分开平台管理审计。机制页切换会卸载管理编辑，因此 UnsavedChanges 对该查询边界增加草稿保护，页内其他分类仍保留原草稿。

机制页包含四种相连视图：常见运行路径、Hy L0–L7、模式与全部能力边界、证据入口。路径只是理解入口，完整机制目录由接口提供；当前合成目录为 46 项、8 层、3 种模式，不把这组数字写成未来固定上限。

```text
长期记忆
  我的记忆                         记忆机制
运行路径 | L0–L7 | 模式与能力边界 | 证据入口
平台原话 → 写入与提取 → 冲突/版本 → 存储 → 检索 → 注入
所选机制：固定版解释 / SDK 支持 / 当前接入 / 可得证据或明确缺口
```

桌面为目录与详情，窄屏保留同一完整目录的原生选择器；沿用现有 future token：背景 #06111b、正文面 #0b1c2c、次级面 #102738、正文 #edf7fb、次级字 #a2bac9、强调 #5ce5ed，以及系统中文字体。设计技能首次检索返回营销 Hero 模式，与任务不符，已收窄到 UX 导航/标题层级，其余按项目阅读需求实施。没有增加字体、图标或装饰动画依赖。

## AA 精确接线与证据边界

依赖主会话冻结的 AA 提交 `b016c2d828cfd67e03a26d8d72afe28d06a78445`，契约 `docs/development/hy-mechanisms-contract.md`。Y 只读核对 AA 隔离树中的最终契约与 `methods/hy_memory/mechanisms.py`，没有自行定义后端字段、修改后端或摘取其提交。

1. 全局 GET `/api/memory-engine/identity`：schema 1，configured/method/representation/legacy_sqlite/state；available 是已有 Runtime 身份，不是健康；not_initialized 的 method=null 不能推断旧方法。503 busy 保留未知或上次身份。
2. GET `/api/memory-engine/hy/mechanisms`：schema 1，固定版本、内存观测时间、装配来源、模式/场景、运行开关、layers/mechanisms/modes/evidence_gaps。configured 只说明代码接入，不证明执行成功、有数据、健康或质量。
3. 目录只读装配声明和内存门控，不扫描库、计数、现场搜索或初始化 SDK。全部层 count=null，浏览活动条目不是全库按层筛选。真实管理能力仍到管理页显式核对。
4. 503 busy 不紧密重试；有旧快照则保留并标原时间，无旧快照则显示暂忙。501、协议错误和未知装配不伪装为空库或关闭。
5. 平台原话独立于 Hy L0；Hy L0 基本信息、L1 RAW。L4/L5 为保留层。当前图、意图、System 2、SDK history 等关闭/未接入/未知状态按声明展示，不用文档中的 SDK 能力替代本次装配事实。
6. schema/normal/proactive 是 SDK 通道；平台额外画像与 normal 接入、最终注入缺口、写入 RRF 与读检索差异、工作事实/经历、coding diffchain 等全部由动态目录呈现。页面不提供启用或切换模式按钮。
7. 真实跳转只到已实现的活动条目/单条来源、基本画像、平台管理审计、处理状态和已有聊天轮次。无接口的逐项决策、最终注入、SDK RAW 全浏览、图/全层筛选明确解释缺口，不构造假 ID 或轨迹。

固定来源：[2.0.3 源提交 README](https://github.com/Tencent-Hunyuan/Hy-Memory/blob/2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed/README.md)。前端严格锁定 `2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed`；没有混入当前主分支或升级 SDK。合成机制夹具取自 AA 冻结目录的纯声明函数，以文件摘要留源，未初始化 SDK、连接模型或数据库。

最初接口需求曾考虑可空计数和已存注入引用；最终 AA 契约明确无扫描、计数及最终注入接口，Y 按这个限制实现，不把原需求当已实现接口。原 `/api/memory-config` 有 status 成本，因此最终全局身份改用独立轻量端点。

## 验证与限制

验证输出均为本树独占目录，不提交 Git。直接使用已解析的 Node、TypeScript、Vite、Vitest 与 Playwright CLI；未调用与锁定版本不符的全局 pnpm，也没有安装或改锁。

- TypeScript `tsc --noEmit` 通过；从实现提交重新生成的独占生产构建 `build-v5/` 通过，与 Edge 已测 `build-v4/` 的全部 45 文件逐字节相同。保留原有 shared-visual 大包提示，没有为了本任务升级或拆动无关组件。
- 全套前端 `frontend-all-v3.json`：58 个测试文件、295 个测试通过，0 失败，已核实包含最后的 Hy 缺失召回字段案例；最后独立聊天补充回归 `chat-final-v4.json`：2 文件、13 测试通过。
- Edge 合成 API 浏览器最终 `browser-v4.log`：16/16 通过（44.3 秒），v3 也为 16/16。覆盖 1920×1080、1366×768、390×844，直接打开/刷新/URL选择、全站导航、旧引擎/未初始化、加载/空/忙/协议错误、来源核对、SDK历史关闭、已有管理回归、大字号、减少动态、键盘与草稿保护。浏览器请求被合成路由截获，未连接日用端口或个人库。
- 已逐图复核总览、机制路径、层级、窄屏及大字号。首轮真实发现能力边界网格的技术长词造成 390px 大字号横向溢出，现已以受约束网格和换行修复；最后浏览器对整页 scrollWidth 验证无水平溢出。其余首轮失败为旧测试未提供全局身份、旧文案断言、隐藏重复文本和过早展开设置导航，均按实际页面前提修正，保留原失败日志。
- 旧 dist/test-results 174 项摘要全部保持；package/lock 摘要与接手时完全一致。差异仅在分配的前端与本报告，敏感模式扫描无发现，`git diff --check` 通过，终端检查未留本树 Node/Python/pnpm/Edge 任务。代码证据在 `frontend-all-v*.json`、`chat-final-v4.json`、`build-v*.log`、`browser-v*/` 与 `browser-v*.log`，未覆盖失败/旧阶段产物。

没有执行 AA/Z 组合后端联机、真实 Hy 库、日用模型、个人数据、圆屏语音或固件验收。原页面已有 chat-config/runtime-status 成本不由本次全局身份替换；合成浏览器通过不构成真实服务延迟/健康证明。AA 后端测试以 AA/Z 的独立交付为准。

本报告为本轮唯一文档写入，正式 manifest 登记按主会话分工留待整合；严格窄范围检查实际返回 unlisted-document 与 unknown-selection（待主会话登记）；直接对本报告运行链接/旧路径检查均为 0 发现。不把未登记的 strict 检查说成通过。没有修改根 README、CHANGELOG 或 ROADMAP。


## 生产构建与源码绑定

- 实现提交：`4b18f6afe77a684cbe20ea6d245001c94e3cee02`；前端 Git tree：`683825d1af44f8d51acb94d3faf9cdbcd4442f5e`。构建时前端相对该提交无改动，唯一待提交项为本报告；之后报告提交不改变该前端树。
- 构建绝对路径：`D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/p-frontend-experience-20261015/data/test-tmp/y-mechanisms-20261021/build-v5`。
- manifest 位于该目录 `.vite/manifest.json`；SHA-256：`771273702f8de59f93a96aedd03f502a9eb4cc7b385b78d13690ad3fbced2bb3`。
- 45 文件整树摘要：`ea5388a08ffb2b5f2bb3dd010d8b42ad74f3edde89ac7fd954fd5d51e8844a73`；前端源码工作字节清单摘要：`4d4c73f667ab78235ed17d4fa7f75ff4f53500a5193fa3f23635f06588059df8`。
- 证据根目录中的 `build-v5-files.json` 为产物逐文件字节数/SHA-256，`source-files-v5.json` 为已提交前端文件实际构建字节清单，`production-binding-v5.json` 绑定实现提交、前端树、版本、manifest、整树及浏览器产物等价关系。清单按路径 Unicode 码点排序，整树摘要是 `{path,bytes,sha256}` 列表以 UTF-8、ensure_ascii=False、紧凑 JSON 序列化后的 SHA-256。
- Node v24.21.0、TypeScript 7.0.2、Vite 8.2.2、Vitest 5.0.0、Playwright 1.62.1；沿用既有 Edge 可执行文件。所有构建证据保留本地，没有拷贝到生产 dist。

## 追溯与接力

任务：Y 全局 Hy 身份与机制探索 → 设计提交 `60b9d6d` → 实现提交 `4b18f6afe77a684cbe20ea6d245001c94e3cee02` → 本树合成验收 → 主会话安排 AA+Y 组合/Z 审查 → main 合入提交待主会话记录 → 会话 `01a153e0-5cf5-7763-b944-7031e8a1c548`。

保留分支、实体工作树、旧证据及本轮 ignored 输出。由主会话负责审查、整合、正式构建与推送；Y 不重复开工或占用交还后的工作树。
