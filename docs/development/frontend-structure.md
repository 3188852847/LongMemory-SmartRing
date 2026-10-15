# 前端源码组织

本轮工作区、共享动态、草稿保护和安全摘要已整合，当前验收见[收口记录](parallel/收口-20261014.md)。下方 94 文件分类和 181 项测试数字属于第一批模块整理记录，不代替本轮验收。

2026-10-14 新增 `launcher.html`/`app/launcher-main.tsx` 独立启动入口与 `features/launcher/`。它与控制台共用视觉组件和外观 Provider，控制 API 由独立本机主机提供，不依赖聊天服务先启动。`features/voice/` 新增 CosyVoice3 声音档案编辑，配置/试听/上传仍各有明确操作边界。见 [React 启动面板](../guides/React启动面板.md) 与 [参考声音](../guides/参考声音与克隆.md)。

2026-10-15 P/Q 组合增加 `features/device/OttoPreview.*` 的固定原图预览与静态首帧降级、`features/experiments/ExperimentPreparation.*` 的真实命令准备入口；聊天次要操作首次展开才挂载，收起后保留已挂载状态。`features/observability/` 继续由页面提供数据和刷新回调，兼容旧响应，并展示显式语音轮次、缺失阶段和只读日志容量。具体入口见 [React 聊天页](../guides/React聊天页.md)及[观测契约](observability-contract.md)，本轮源码与组合检查见 [S 报告](parallel/S-20261015.md)；尚未切换日用进程。

2026-10-14 将 `web/react-chat/src/` 原来平铺的 94 个文件按真实职责归类。运行路径、API、页面交互与样式保持原有行为；前端仍使用 React、React Router、TanStack Query 和 antd，没有新增依赖或升级锁文件。

| 路径 | 职责 |
|---|---|
| `app/` | `main.tsx` 挂载应用；`ConsoleApp.tsx` 装配共享上下文和路由；外观上下文、查询客户端 |
| `pages/` | 聊天、总览、设备、圆屏预览、记忆、质量、场景、画像、设置、实验等页面入口及页面测试 |
| `features/chat/` | 会话操作、发送快捷键、聊天失败说明和记忆证据显示 |
| `features/memory/` | 手动记忆、整理状态、记忆操作失败说明 |
| `features/device/` | 圆屏观察状态和壁纸管理 |
| `features/voice/` | 语音播放、声音设置、VAD、TTS 切换和比较 |
| `features/settings/` | 模型、角色、记忆后端与个性化设置；`proactive/` 保存主动交流设置 |
| `features/experiments/` | 实验作业、回放与实验失败说明 |
| `features/diagnostics/` | 当前服务状态诊断 |
| `features/observability/` | 请求与阶段安全摘要、只读刷新和未知结果说明 |
| `features/data-workspace/` | 六个数据页面共用的任务区、筛选和详情布局 |
| `components/` | 跨页面复用的外壳、导航和页头 |
| `api/` | `index.ts` 统一导出客户端与按领域划分的传输类型；`client.ts` 处理请求 |
| `styles/` | 控制台全局样式 |
| `tests/setup.ts` | jsdom 测试环境设置 |

`vite-env.d.ts` 继续位于源码根目录。没有现成职责的 `hooks/`、`utils/` 或独立顶层 `types/` 不提前建立：目前外观 hook 与上下文放在一起，接口传输类型集中在 `api/types/`。新的功能优先放进所属业务组，确认被多个业务共用后才提取为公共模块。

单元与组件测试继续紧邻被测模块，以 `*.test.ts` / `*.test.tsx` 命名；Vitest 仍递归收集 `src/` 下测试。浏览器测试放在 `e2e/`。页面只组合所属功能和公共组件，API 调用通过 `api/`；这次分类没有声称已建立自动强制的依赖边界规则。

聊天页面从原 `main.tsx` 提取为 `pages/ChatApp.tsx`，路由提取为 `app/ConsoleApp.tsx`。聊天页面通过 `useQueryClient()` 取得应用共享查询客户端，继续复用原来的缓存和刷新行为。`index.html` 的源码入口、相对导入、共享 `web/assets/` 引用和 Vitest 环境设置路径一并修正。

## 验证与日常命令

在 `web/react-chat/` 的既有前端环境中运行：

```powershell
pnpm.cmd build
pnpm.cmd test
pnpm.cmd test:e2e
```

浏览器测试只连接一次性 Fake 控制台和临时合成数据库，不读取私人 env 或正式记忆，不调用模型与实体圆屏。固定浏览器版本由 Playwright 安装管理。已装有兼容 Chromium 系浏览器时，可在当前终端显式指定其可执行文件，使用一次性浏览器 profile 进行本地验证：

```powershell
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH = '<本机已安装的浏览器可执行文件绝对路径>'
pnpm.cmd test:e2e
Remove-Item Env:PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
```

不要指定日常浏览器用户目录。CI 不设置这个覆盖变量，继续使用 Playwright 对应版本的 Chromium。

本次整理使用 Node 24.19.0 和原有依赖的隔离副本验证，未安装或下载依赖。TypeScript 类型检查、生产构建及 Vitest 的 39 个文件 / 181 个测试通过。本机已安装 Edge 的四项浏览器测试通过，覆盖聊天保存与刷新恢复、页面导航、窄窗口、只读实验护栏、重复记忆合并与恢复；使用工作树独立 Fake 服务、临时合成数据库和临时浏览器 profile。默认 Playwright Chromium 二进制尚未安装，本地系统浏览器验收不能代替 CI 固定浏览器版本结果。
