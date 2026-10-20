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
