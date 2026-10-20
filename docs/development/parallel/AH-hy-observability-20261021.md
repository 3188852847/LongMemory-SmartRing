# AH：L6/L7 与延迟只读观测

日期：2026-10-21。基线 `a93258e903954525b88b7af79756aaffe2bd50d6`，分支 `codex/ah-hy-observability-20261021`。

## 第一里程碑：代码核查与文件归属

现有 `/memories?view=mechanisms&mechanism_tab=layers` 已有 L0–L7 逐层读取、分页、详情、来源、冷链接与滚动恢复。L6/L7 目前只有 VDB 存量记录和 `vdb_only_graph_unopened` 边界；不能由此画出真实关系图、推断图为空或把 configured 当作已成功运行。当前页面没有原生更新时间，`observed_at` 仅为读取完成时刻。

AH 文件范围：

- `web/react-chat/src/api/hyLayerData.ts`：后端契约的展示解析；待 AB 正式交接后增加图/派生/L7生命周期 DTO。
- `web/react-chat/src/features/memory/HyLayerBrowser.tsx`、`HyMechanismsWorkspace.tsx`、`hy-layer-data.css`：所选层的只读展示与现有装配快照接线。
- 新增 `features/memory/HyLayerStatus.tsx` 及相关测试：把配置、内容、覆盖和开关独立呈现。
- 对应 `src/tests/fixtures/`、组件测试与专属浏览器用例。
- 延迟展示待 AI 统一阶段契约交接后接线；不另造采样协议。

不修改 AB 的 `methods/hy_memory/`、worker/layer_data；不修改共享控制器、启动器、音频采样或公共任务书。不需要新增后端端点或持久化决定即可完成现有协议下的状态展示；若 AB 新接口确需独立只读 view/service，先由主会话协调准确文件。

请求主会话接力 AB 契约：真实 L6 有界节点/边/派生来源及覆盖范围、L7生命周期原生字段、真实后台开关和只读失败码；AI 契约：统一阶段 ID、耗时来源与缺失/取消/有效首答边界。未收到前不猜字段、不造个人图谱。

## 设计依据

已读 frontend-design/ui-ux-pro-max。沿用既有 future token（`#06111b/#0b1c2c/#102738/#edf7fb/#a2bac9/#5ce5ed`）和中文系统字体。左对齐正文；L6/L7 状态紧凑排列，详细来源随记录展示，不增加无证据图形。技能 UX 检索 `status empty state` 命中 Empty States，采用明确空态与手动刷新，保留未知/失败/部分覆盖区别。

## 验证与交接

阶段一已实现 `HyLayerStatus` 受控组件和 `hyCapabilityView` 页面内投影。主会话补充的五轴为期望配置、实例实际能力、证据与条目覆盖、后台任务、管理可用性。页面内每轴是 `{state,description,observed_at}`；`state` 可区分 configured/enabled/disabled/unknown/unsupported/failed/partial/empty/present/idle/running/blocked。这不是新 HTTP 或 SDK 协议，不预定 AB 字段；真实能力的适配器待 AB 交接。组件 `capabilities` prop 接收已适配视图，未传时只投影现有逐层声明/覆盖，其余轴保持 unknown。

运行门通过独立 `runtimeSnapshot:{runtime:{write_enabled,use_enabled},observed_at,stale}` prop 接入现有机制声明，不新增请求。刷新失败/忙碌时不能用旧内容投影新状态；快照过期明确显示上次，写入门开启不会提升为图生成或管理可用。原生更新时间没有上游字段，明确未提供，保留逐条存储/记忆/有效期与独立读取时间。

五轴证据为内容与分页之后的原生 details 折叠区，无修改按钮、无自动轮询。列表、详情、来源和原生版本仍经既有有界 GET 读取。首轮把摘要放在正文之前导致选层后正文出屏，已移至次级内容之后。补充的 844px 高视口还暴露原显露条件仅给标题后留240px，导致标题虽然可见、内容不可见；已仅针对显式点层调整留白，筛选/刷新/历史恢复仍不触发滚动，不滚到页面顶。旧失败证据保留。

测试只使用合成响应、独立端口与浏览器 profile；不连接个人库、日用服务、模型或设备。未更改锁文件或安装依赖。主项目既有固定版本 node_modules 被复制为 AH 实体副本，632个内部链接全部改指本树，23794个常规文件独立复制；不修改来源，不把共享可变 node_modules 联接到本树。React/Vitest解析路径核对来自AH；主Python3.12.13只用于源码来源只读核验，`longmemory.__file__`为AH的src。本树前端目录自动选择Node24.19.0。全局pnpm12.9.1没有调用，使用本树固定TypeScript7.0.2/Vitest5.0.0/Vite8.2.2/Playwright1.62.1直接CLI，packageManager/锁文件保持pnpm11.19.0原声明；未联网。

阶段一不涉及新持久化或系统边界决定，暂不使用预留 ADR-0202。AB实际能力/图派生/L7生命周期、AI统一延迟字段仍是接力依赖，当前可插拔fixture不得充作个人图谱或真实后台任务验收。

实际证据保留在本树 `data/test-tmp/ah-observability-20261021/`：

- `components-v2.json`：3个文件、30项相关组件/协议测试全通过，含新增6项五轴语义和受控显示测试。TypeScript `--noEmit` 通过。
- `build-v3/` 与 `build-v3.log`：独占生产构建通过，既有大chunk警告保留，没有覆盖正式dist。
- `browser-v3.log` 与 `browser-v3/`：已安装Edge、独立随机端口/临时profile、27项全部通过。包含原25项记忆/机制/逐层回归和新增1366/390两项五轴/只读/忙碌/前后退检查；原有1920/1366/390、较大字号、减少动态、来源和版本详情、刷新恢复、非零滚动选项不跳顶、旧引擎及草稿保护仍通过。
- `layer-capability-1366.png` 和 `layer-capability-390.png` 等位于对应浏览器用例子目录，已视觉核查左对齐可读、折叠语义清晰、无横向溢出。截图均为合成接口结果，不是个人图谱。
- 首轮 `browser-v1/` 的3个视口失败和布局调整后的 `browser-v2/` 两个高视口失败均保留；实际修复后v3通过，未削弱视口断言。

`git diff --check` 通过；前端包声明/锁文件与原字节一致，后端目录未修改。未运行远程CI，未切换日用服务、未使用GPU/学校模型、未读取个人数据、未写管理proof、未推送或合入main。阶段一完成不等于本轮L6/L7/延迟目标全部完成，后续需在本分支接 AB/AI 契约并重新做真实边界与组合验收。

## 第二阶段：冻结原生字段与公共只读HTTP

主会话授权本阶段接线；实现先依据 AB 的公开稳定候选记录，随后只读核对冻结提交 `5a4c1ecb9abf5d2434f8a6eff2e5b3565d8e5d6a` 的 `semantic.py/worker.py/layer_data.py`，以及 AI 的 `a7a61b87e7da6ee7adacf73a401fa8e7e292c4b7` 公共路由、Runtime、参数白名单与 HTTP 测试。没有合入或复制同伴脏源码，也没有把前端fixture当真实SDK验收。

早先 AH 提议 wrapper，主会话已冻结使用 AI 实际扁平响应，以下形状为本阶段唯一接线依据：

- `GET /api/memory-engine/hy/semantic/status`，无参数：AB `protocol:2` 全部状态字段在顶层，追加 HTTP `observed_at` 与 Runtime `runtime:{write_enabled,use_enabled}`，没有 `status/data` wrapper。
- `GET /api/memory-engine/hy/semantic/tasks/{task_id}`，无查询：AB `task_id/kind/state/created_at/finished_at/elapsed_ms/reason_code` 在顶层，追加 HTTP `observed_at`。本阶段初版沿当时 AI 的1–96位白名单；随后发现其拒绝AB自动任务ID，当前规则由下方“自动任务ID接口修正”取代。
- 错误：503 `hy_semantic_busy/hy_semantic_unavailable`、501不支持、404单任务不存在。客户端只实现这两个GET，没有 enqueue/cancel/启用管理入口，没有自动轮询或失败重试。

状态读取仅在用户点击“读取实例状态”或打开已有任务冷链接后发生；任务用已知ID单条读取。冷链接按层页→实例状态→任务顺序，避免初始争抢owner锁；Runtime未确认或存储请求进行中禁止启动该按需读取。页/详情/来源与新请求均沿原会话认证，没有扫描全任务或新资源。URL `semantic_task`保留前后退/刷新，选项仍使用`preventScrollReset`；busy保留上次快照并标旧，不把上次能力伪装为本次事实。

### 实际展示

- 新 `api/hySemantic.ts` 精确校验 protocol2、两个策略字符串、false执行/主动联系授权、任务计数、UTC时间、Runtime门和单任务ID；缺计数键保留未知，ready_epoch=-1保留，不猜0。旧协议、错任务ID、未知策略和伪执行授权拒绝。策略分别是 `read_only_expiry_filter_and_dedup/disabled`、`archive_not_assert_completion/disabled`。
- `hyLayerData.ts` 追加 `graph_complete`、`graph_only_legacy_vdb_present` 和 `owner_agent_source_layer_state_graph`；旧VDB共存必须partial、固定原因码、total=null，不把图页计数当全层总数。L7保持精确VDB。旧页缺整组语义字段仍可显示；新字段出现须整组合法、按L6/L7匹配且`execution_authorized=false`。
- `HySemanticRecord` 展示L6模型归纳、ready/isolated、L7未来意图与stored/expired，最多16个可得依据ID或未知；ID没有层信息，不造跨层链接或不存在的全图边。平台原话与RAW仍分别按单条GET读取。L6归纳不直接当用户事实，L7过期不表示执行或完成。
- 原生 `updated_at` 与存储/记忆/有效期/读取时刻分别显示；null不补造。AB冻结的`schema_injection_isolated`即使空图页也立即提示派生隔离；图空页不能凭配置或读取成功改写为空层。原生图覆盖和旧VDB未纳入分别说明。
- 五轴接入实际实例：期望配置与enabled分开；图式隔离不混作关闭；pending、running、paused和管理可用性分别解释，缺计数不补零，已认领不假称暂停回滚。单任务回执区分completed/partial/uncertain/cancelled，完成不代表意图已执行；不自动重放。
- 按主会话允许的分阶段交付，本页明确“尚无统一阶段测量证据”；后台任务耗时不能代替用户说完到首个有效回答声音。没有性能卡片或虚构P95，后续待真实延迟导出字段追加。

本阶段仅追加消费既有Hy专属只读接口及视图，没有新持久化决定；对应系统边界由AB ADR-0195与AI ADR-0201说明，AH预留0202未占用。

### 第二阶段验证与组合接力

证据继续位于本树 `data/test-tmp/ah-observability-20261021/`。实际源码、构建输入/产物及最终提交另由 ignored 绑定JSON记录；正式dist、依赖锁、后端和所有日用资源不变。

- `components-stage2-release.json`：相关5个文件的44项组件/协议回归全部通过，含实际启用/关闭、期望与实例差异、隔离空页、L7过期、依据未知、图/VDB混合覆盖、精确计数范围、UTC与原生更新时间、读请求串行、501/404/busy、缺计数/队列状态和伪授权拒绝。最后区分后台paused标签的小改动增量验证见`components-stage2-paused.json`，不改变已认领任务仍运行的边界。
- `browser-stage2-v2.log`：29项记忆/机制/分层浏览器回归通过，含新增1366/390语义原生记录、来源、实例状态、单任务不确定回执和只读GET检查，保留原前后退/分页/滚动/旧引擎与草稿保护。后续无障碍名称/任务ID与原生隔离原因码的窄范围检查保留在独占最终浏览器目录，不覆盖旧证据。
- `build-stage2-delivery/`为最终独占生产构建，TypeScript通过；既有大chunk警告保留。`browser-stage2-delivery.log`对最终产物的4项桌面/窄屏关键浏览器检查通过，含本阶段两个真实契约路径与两个旧协议兼容路径；不把此前29项回归冒充在最后小改动后又全跑一遍。最终关键浏览器证据与构建绑定另见本次交付输出。
- 1366桌面与390大字号的图式隔离/原生时间/有界依据ID截图已视觉检查；状态/任务区域无横向溢出。初期组件失败来自`unknown && JSX`类型及antd加载图标进入按钮名称；前者改为显式布尔，后者补稳定aria-label。先前失败JSON保留，没有削弱验证。

当前限制：这是对冻结代码/契约的前端合成验收，没有在AH运行真实SDK或真实组合HTTP。主会话将本阶段独立提交转AI后，AI负责AB+公共Runtime/HTTP+AH的配对审查与组合验证，再由主会话安排日用切换；旧proof仍不能用于语义能力，AH没有重签、开启或部署。真实个人图谱、学校模型、GPU、圆屏声音/打断与端到端测量均未在AH验收，无所有者下载需求。本阶段可独立合入，不堵在尚无导出字段的延迟模块。

## 自动任务ID接口修正（当前契约）

第二阶段主体提交 `ca1e488439a79b970dbc5dc884e87c0c1c9149ea` 后，主会话转交AI组合审查发现：AB自动任务使用`add:<sha256>`、`add:<sha256>:expiry`及`management:`命名，AI初版HTTP和AH初版前端白名单都错误拒绝冒号。主会话授权各自修正所拥有层，不改任务权限。

AH重新核对AB冻结的`semantic.task_id`：非空/strip后非空、最多256个Unicode码点、拒绝C0控制字符。`hySemanticTaskIdentifier`现按该原生规则检查，含Python的空白集合和按码点计长，不截断或trim原ID；`hySemanticTaskPathIdentifier`另在HTTP单路径段边界拒绝`/`、反斜杠、纯`.`/`..`和不可URL编码字符串。这项路径限制落实主会话“无斜杠/路径穿越”要求，不冒称AB原生验证本身已拒绝斜杠。冒号、中文、百分号、问号和井号作为不透明ID，经`encodeURIComponent`编码，回执必须与原ID精确相同。

输入可容纳最多512个UTF-16代码单元，以支持256个非BMP码点；是否有效仍由256码点原生规则判断。冷链接、单任务GET和读取表单统一使用HTTP路径边界检查；没有新增提交、取消、启用、自动重试或跨范围读取。

`components-task-id-fix.json`的28项针对性测试通过，覆盖原生自动ID冷链接、编码GET、精确回执、256码点、Python空白/C0控制、路径拒绝和原有只读状态；TypeScript及`build-task-id-fix/`独占构建通过。`browser-task-id-fix.log`的5项全部通过：新增自动add/management冷链接/返回及原4项桌面/390px只读语义路径，输出与截图保留在同名独占目录。既有第二阶段44项/29项历史验证不改写为本修正后全量重跑。

AI同时负责公共HTTP白名单及RPC缺失/忙碌错误映射修正，AH未编辑其文件；新前端提交须与AI该修正配对验证。AH仍未运行真实SDK/组合HTTP、未更改日用或后台写入，整个分支不推送、不合main。
