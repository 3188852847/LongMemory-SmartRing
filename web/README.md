# Web 界面

新增 `experiments.html`、`assets/experiments.js`、`assets/experiment-view.mjs` 与 `assets/experiments.css`：研究档案和四组逐题对照、独立人工复核版本保存。固定读取三种实验协议，动态文本不解析为 HTML。运行按钮暂不提供，不新增前端依赖，见[实验中心指南](../docs/deployment/experiment-console.md)。

本目录是本机控制台的前端位置；已实现“设备与状态”“记忆管理”和“文字聊天”页，助手角色与完整运行记录页仍显示待接入。

按 ADR-0008 已新增 `chat.html`、`assets/chat.js` 和 `assets/chat-view.mjs`：临时网页会话和逐轮过程展示，共用指定的已有长期记忆库。不默认播放网页回答到设备；刷新另开聊天，服务重启不恢复聊天历史列表。网页与小智配置需核对，尚未自动同步。实验数据另行隔离，现有前端选型和本机安全约束不变。

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
