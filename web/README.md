# Web 界面

选型更新：`react-chat/` 已承载 React + TypeScript + Vite + antd 的文字聊天、L0/L1 记忆、L2 场景、L3 用户画像、设备状态、圆屏状态预览、设置中心与实验中心，由 Python 统一提供 React 路由和构建资源。统一启动默认进入 `/chat-react`；原生入口只作为迁移期回退。React Router、共享 AppShell/PageHeader、TanStack Query 和 Vitest/React Testing Library 已建立，导航按“日常使用 / 长期记忆 / 控制与观察”分组，设置按四个标签页组织，并覆盖窄屏与低高度窗口。圆屏预览只模拟 466×466 状态布局，不连接设备。见[体验及构建指南](../docs/guides/React聊天页.md)。以下描述主要记录保留的历史原生实现。

P2 已新增聊天页 `appearance.mjs`（校验/存取/应用显示偏好）、`appearance.js`（控件绑定）与 `chat-appearance.css`（局部主题）。沿用原生前端，见 ADR-0020。本浏览器持久缓存仅用于外观枚举和最后选中会话 ID，不保存聊天正文。

`experiments.html`、`assets/experiments.js`、`assets/experiment-view.mjs` 与 `assets/experiments.css` 提供研究档案和逐题对照、独立人工复核。新增 `assets/experiment-jobs.mjs` 隔离单作业预检/明确确认、只读进度轮询、停止后续题与结果打开。动态文本不解析为 HTML，不新增前端依赖；启动开关、模型配置和风险说明见[实验中心指南](../docs/deployment/experiment-console.md)。

本目录是本机控制台的前端位置。当前日常入口均已迁移到 React；`chat.html`、`memories.html`、`experiments.html` 等原生页面仅作兼容回退，不再代表当前信息架构。

按 ADR-0008 已新增 `chat.html`、`assets/chat.js` 和 `assets/chat-view.mjs`，随后增加独立旁库会话恢复：同一浏览器可刷新、重启续聊，支持列表、切换和重命名。共用指定的已有长期记忆库，不默认播放网页回答到设备。网页与小智配置需核对，尚未自动同步。实验数据另行隔离。

2026-09-03 按用户决定新增控制台里程碑，覆盖原“V0.1 不选型”的预留状态。
方案：静态 HTML + 原生 JavaScript 模块 + 本地 CSS + JSON API，由 Python 后端统一提供静态资源。
暂不安装前端框架、模板引擎或构建工具；不使用 CDN、远程字体、第三方统计。

页面规划：设备与状态、记忆管理、助手角色、运行记录。助手角色不等于 L3 用户画像。
记忆文本、来源和模型回答只用 textContent/value 展示，不当作 HTML、事件或脚本。
用户已确认设备网页可以控制圆屏。记忆页支持显式指定已有库、只读分页/文字搜索和来源查看；删除需启动开关及单条确认，L0 保留，不自动迁移。启动和体验见[控制台指南](../docs/deployment/local-console.md)。
静态页只从本机白名单加载 CSS/JS/SVG；动态内容用纯文本 DOM API。设备令牌仅存后端，会话 Cookie、Origin/Host、CSRF 和 CSP 限制已实现。离线 HTTP/状态映射测试覆盖跨站拒绝、超时、断线和回执不一致。用户已验证设备网页控制；助手未进行浏览器视觉/断网检查，记忆页真实交互仍未验证。
`assets/state.mjs` 为纯状态逻辑，`assets/app.js` 负责交互；`public/` 和 `src/` 暂保留原骨架，不由后端公开。页面无需 Node 构建，只有前端单元测试需要 Node。

`memories.html` 是列表与来源详情，`assets/memories.js` 只通过本机认证 API 请求记忆；`assets/memory-view.mjs` 包含可测试的时间、状态、分页文案。没有自动抓取全部来源或将个人记忆放入浏览器持久缓存。
只读 WebMCP 查询为可选渐进增强；当前没有支持上下文可验证，不宣称已验证。不支持此 API 的浏览器仍可正常用按钮操作。
框架评审触发条件和整体边界见 [ADR-0007](../docs/adr/0007-local-console-and-device-control.md)。
