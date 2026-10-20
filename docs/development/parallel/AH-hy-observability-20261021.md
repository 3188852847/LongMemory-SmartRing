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

## 离线发布构建交付

主会话确认AI当前前端Git tree与AH一致，指定AH用既有实体依赖构建。本轮开始硬核对：HEAD=`70cad5b765c16632e808b8861b4dff875b09d3f8`、工作树clean、`web/react-chat` tree=`43ecb03553163f675e437193345f26a7f77942f4`；共享`web/assets` tree=`3cc3fce0066fb30dcea0ac15e383fbde1a491929`。构建完成后只追加本记录，记录提交不改变上述前端tree或构建输入。

产物根目录为AH树内 `data/test-tmp/ah-release-70cad5b-20261021/`，以下文件均被Git忽略，没有提交产物或原始日志：

| 路径 | 内容 |
|---|---|
| `dist/` | 本轮新建的独占发布候选，不是生产dist |
| `artifacts.files.json`、`artifacts.sha256` | 全部45个相对文件、字节数和逐文件SHA-256；清单包含`.vite/manifest.json` |
| `release-binding.json` | 源提交/前端与共享资源Git tree、Node路径/版本、实际依赖版本、命令、锁文件身份、产物tree/manifest摘要、引用校验、扫描与截图关联 |
| `asset-references.json` | HTML/CSS/JS/manifest的264处本地资源引用，均存在；manifest导入键同时校验 |
| `typecheck.log`、`build.log`、`verification.log` | 未截断原始日志；既有大chunk警告保留 |
| `verify-release.cjs` | 本任务冻结源码的只读核验脚本，仅将清单和绑定写入该证据目录 |
| `delivery-receipt.json` | 对上述清单、绑定、脚本与原始日志的外围文件摘要 |

在本树 `web/react-chat/` 用既有Node24.19.0执行，无安装、复制或联接node_modules：

```powershell
node node_modules/typescript/bin/tsc --noEmit
node node_modules/vite/bin/vite.js build --outDir ../../data/test-tmp/ah-release-70cad5b-20261021/dist
node ../../data/test-tmp/ah-release-70cad5b-20261021/verify-release.cjs
```

固定工具为TypeScript7.0.2、Vite8.2.2，包声明仍为pnpm11.19.0；没有调用本机其他版本pnpm。`pnpm-lock.yaml` Git blob=`ab2596b2d7c2fda56690dbe7ccf9778461183924`，工作文件SHA-256=`c0e083751833a86c21a0f4cfa7cf66d8a8621d1459b91a66991dcfbe6ad6fdd9`；package.json和其他构建输入逐项摘要在绑定中。既有632个包内链接全部仍指向AH实体依赖目录，主依赖/开发依赖的实际版本与原声明逐项一致。

实际结果：45文件、1,835,506字节；规范tree SHA-256=`278ed5f109b2ffcce9246e5f26719dd6add19d94f9b5e7d28bcee4dc48a9a1ef`；`.vite/manifest.json` SHA-256=`fff8f17b610f6bb55cd83f518a831eb73a9359c6f89332ace572c0caa774df53`。tree算法为：相对路径统一`/`并按UTF-8字节排序，依次连接`路径UTF8 + NUL + 文件SHA256 ASCII + LF`，再SHA-256；不是JSON文件摘要。

全部文件与本树此前同提交/同tree的`build-task-id-fix/`及其已保存绑定逐文件一致，没有新增构建差异。因此关联原5项浏览器通过及7张原始截图，不重复运行无新增变化的组件/浏览器测试；本次重新视觉查看1366桌面与390大字图式/来源截图，正文、隔离与部分覆盖说明可读，无横向溢出。截图路径和逐张摘要在发布绑定中。

构建资源引用无缺失；产物仅包含预期HTML/JS/CSS及manifest，无source map或额外文件。全部产物文本的固定凭据、私有机器路径及合成fixture标记扫描0发现；前端无`.env`文件、生产源码未引用测试fixture，未读私有配置或个人数据。扫描结果表示所列检查范围，不替代组合运行与所有者实机验收。

此交付只作为AI按相同前端tree审查的可部署候选。主会话另负责备份、正式dist切换/服务恢复与生产保护核验；AH没有修改生产dist、服务、config、管理proof、个人库或固件，也没有推送/合入main。

## L2/L3/L4来源可信标签接力

主会话要求消费AB提交`92d40492658d0f972435bc73d218e1f683bba649`的新增来源标签。已只读核对其`layer_data.py`及`provenance.py.describe`：可选`provenance`对象精确包含`status/semantic_source_complete/dependency_basis/injection_allowed`。当前只接已冻结的L2/L3/L4，不猜AB后续L0/L7字段。

`HyStoredRecord`新增该可选类型和校验：对象缺省时保留未知；存在时校验四字段、枚举、布尔及AB的来源完整性关系，不用层名、active状态、来源ID数量或注入许可推断来源完整。`injection_allowed`与来源完整性独立：未证实概括仍可能被当前策略允许注入，界面照实分别呈现，不能把允许注入显示成已证实来源。

新增只读`HyRecordProvenance`，在列表正文后显示“用户原话/用户明确纠正/未证实模型推断/来源可信类型未知”，同时显示“当前允许注入/当前禁止注入/注入许可未知”；详情显示完整性与依赖依据。`scope_context_envelope`明确解释为潜在上下文依赖范围，不是模型真实引用或逐句归因；`legacy_unobserved`不解释成没有依赖；用户明确纠正只说明该条来源，不冒充模型推断已确认或未来意图已执行。没有新API、管理按钮、自动读取或依赖。

实际验证：`components-provenance-v1.json`相关3个文件33项通过；TypeScript与独占`build-provenance-ui-v1/`通过；`browser-provenance-v1.log`逐层14项通过，包含新增1366/390大字号的来源类型/未知/注入许可、冷详情链接、非零滚动、刷新恢复、浏览器前后退及原分页/状态/图覆盖/单任务/只读GET。新增桌面与窄屏详情截图已视觉核查，依赖说明可读且无横向溢出。全部数据为合成响应，不是个人库或AB真实SDK验收。

核心展示先独立提交供AI接入。**此前`70cad5b`/tree`43ecb035…`的45文件发布候选从本次前端变更起失效，只保留历史证据，不能用于本轮发布；新的dist、manifest、tree摘要与资源引用校验将在精确新提交/tree上重新生成，不沿用旧SHA。** 依赖锁、生产dist、日用服务/config、个人库及proof均未修改，无联网/安装。

### 来源标签新版发布候选

核心提交为`66e76b2f83caaf4b5adaae9f2e2c31e9c0c8b30a`，前端Git tree为`629d4cdac8470e1dd56ed453a32b931a8384a9b7`。确认该HEAD且clean后，使用AH既有实体依赖与Node24.19.0，重新执行`tsc --noEmit`和Vite8.2.2离线构建到全新`data/test-tmp/ah-release-provenance-66e76b2f-20261021/dist/`，没有安装/复制/联接node_modules。锁文件、package.json、共享`web/assets` tree与上一发布记录相同，精确身份重新写入新绑定。

新目录继续提供`artifacts.files.json`完整相对清单/字节数/逐文件SHA-256、`artifacts.sha256`、`asset-references.json`、`release-binding.json`、`delivery-receipt.json`、核验脚本及未截断`typecheck/build/verification.log`。新外围回执显式记录旧`70cad5b`候选已失效，以及AB来源契约提交；所有文件保留在忽略目录，不提交产物。

新产物45文件、1,838,677字节；规范tree SHA-256=`6c5d8af45189996439cc93a741c0f6ce7797c998bcb80c73973a14f7fdfb132e`；manifest SHA-256=`93931ebb21d7e500becfe819a58c777554eb3d46d3d2885d70eec8d6c18357b5`。tree算法沿前述UTF-8相对路径字节排序、路径+NUL+文件摘要+LF后SHA-256，包含manifest。264处本地资源引用与manifest导入键均通过；固定凭据/私有路径/fixture标记（含新增“合成来源样例”）扫描0发现。

新发布字节与本次`build-provenance-ui-v1/`浏览器已测目录逐文件一致；原14项通过日志、26张截图及新增桌面/窄屏来源详情截图按摘要关联到新绑定，不把旧发布截图冒充新版来源展示。常规测试未无理由重复运行。类型检查、构建和引用核验通过，保留既有大chunk提示；这仍是前端合成验收，真实前后端来源策略由AI组合验证。记录提交仅改本文件，前端tree保持上述新值，不改生产资源、不推送、不合main。

### L0/L7同四字段适配与聚合边界

主会话随后要求L0/L7也消费同四字段，最终AB提交/DTO有异时再转接。本轮原先层级guard不是通用的，因此在上述核心提交后补充L0/L7解析与只读显示；仍不猜新的状态枚举。缺标签的L0/L7也显示来源/注入未知。L7保留原“未来意图/已过期”说明，不把来源核对当执行完成；L0聚合显式提示“记录级来源标签不能证明整份聚合画像的语义来源完整”，完整性字段标题限定为记录级，各字段来源继续单独核对，即使标签返回true也不推定整份聚合画像完整。

该增量使`66e76b2f`发布候选同样成为历史失效候选；它与更早`70cad5b`候选都不得用于本轮最终部署。下次发布绑定将以本增量的精确新提交/tree重建，保留所有旧目录和摘要作为历史证据。

`components-provenance-l0-l7.json`相关3文件36项通过；类型检查与`build-provenance-l0-l7/`通过。增量浏览器`browser-provenance-l0-l7.log`的4项通过，覆盖1366/390的L0聚合限定、L7来源/意图分离，以及L2冷链接、非零滚动、刷新和前后退；没有无理由全量重跑原14项。新增窄屏聚合/意图截图已检查。当前仍是按主会话同四字段契约的合成展示验证，AB真实SDK/正式导出配对由AI负责，AH未接触日用资源。

### 当前交付候选：54ae8a40

上述兼容增量提交为`54ae8a4094e91f81cd6d2ea229bdb3b495297e8f`，前端Git tree=`85c8bf6945a3fea0b6f2bdb3da3546b0873a09ec`。确认该HEAD/tree且clean后，再次使用本树既有实体依赖，离线执行类型检查与发布构建，输出独占`data/test-tmp/ah-release-provenance-54ae8a40-20261021/dist/`。Node24.19.0/TypeScript7.0.2/Vite8.2.2、pnpm11.19.0声明和原锁文件身份均未变，无安装/复制/联接依赖。

当前产物45文件、1,838,948字节；规范tree SHA-256=`c5b2779d2b63980b9183561467ac423e30012dbf3a38d57216d0c28b86bb9ac5`；manifest SHA-256=`8760f1c25b01a876394af413b58734d479b021b4404fa7771b0ede6bfa3201eb`。全相对清单、逐文件SHA-256、原始日志、264处通过的本地资源引用、0发现的固定隐私/凭据/fixture扫描、源码/工具/锁文件/截图绑定均在新目录中，文件名沿用前述`artifacts.files.json/artifacts.sha256/asset-references.json/release-binding.json/delivery-receipt.json`。新回执同时列出70cad5b与66e76b2f两个旧候选已失效，不能按旧SHA发布。

新产物与本次L0/L7增量浏览器已测`build-provenance-l0-l7/`逐文件相同，关联原4项通过及8张当前截图，无需无理由重复组件/浏览器。当前目录不含生产dist或私有数据；AH只提交本记录，不部署/推送/合main。AB最后L0/L7来源输出提交与本同四字段视图仍待主会话转AI做真实配对确认，未用合成截图代替SDK或所有者验收。
