# 自动化质量检查

GitHub Actions 的 Quality 工作流在 Windows 上运行后端和前端两个并行检查。日常推送验证主要使用路径，面向 `main` 的拉取请求（PR）和手动运行执行完整检查。[工作流与用例选择](../../.github/workflows/quality.yml)

| 状态检查 | 推送到 `main` | 面向 `main` 的 PR 或手动运行 |
| --- | --- | --- |
| Backend synthetic tests | HTTP 聊天恢复与重放、原记忆引擎跨进程召回、Hy 适配层重启后回读来源与召回、启动器启停、圆屏语音协议与回答收尾 | 运行报告审计自测，再执行完整 pytest 并审计 JUnit 报告 |
| Frontend and browser tests | 聊天页、Hy 记忆工作区和启动面板的 Vitest，随后检查 TypeScript 并构建生产页面 | 全部 Vitest、类型检查和生产构建，再用固定 Chromium 执行 Playwright |

推送的文档例外包括 `docs/` 下的 Markdown、`docs/documentation-manifest.json`、`web/README.md` 和根目录的 `README.md`、`AGENTS.md`、`CHANGELOG.md`、`ROADMAP.md`。仅当一次 `main` 推送的全部改动都在这些路径内时，Quality 才跳过本次推送。改动包含 `src/` 下的提示词或工作流本身时仍执行快速检查。PR 保留两个状态检查。需要为某个分支完整复查时，在 GitHub 的 **Actions → Quality → Run workflow** 选择该分支运行。

## 报告与环境

快速检查要求 pytest 和 Vitest 的 JUnit 报告各有实际执行的用例，任何失败、错误或跳过都会使相应检查失败。完整后端报告在 `data/test-tmp/ci/backend.xml`，只允许已登记的用例因清单中指定的资源条件而跳过。[报告审计](../../scripts/ci/backend_quality.py) · [资源清单](../../scripts/ci/backend_resources.py)

后端使用锁定的 console 和 dev 依赖、临时数据库及合成输入。前端使用项目指定的 Node、pnpm 和锁文件。仅完整前端检查准备浏览器后端并安装 Chromium，在独立回环端口运行临时控制台，核对浏览器用例的收集和执行结果。模型、专用 SDK 和圆屏实机体验另行验收。[浏览器检查入口](../../scripts/ci/browser_quality.mjs)

## 本地复查

已有依赖时，可从仓库根目录运行完整后端检查。

```powershell
.\.venv\Scripts\python.exe scripts/ci/test_backend_quality.py
.\.venv\Scripts\python.exe scripts/ci/backend_quality.py
```

工作树验收应让测试及其子进程使用该树的 `src`。前端命令见[前端验证与日常命令](frontend-structure.md#验证与日常命令)。远端通过状态以对应提交的 Quality 运行结果为准，历史故障和验收证据见[依赖与后端回归](parallel/AI-hy-advanced-low-latency-20261021.md)、[前端合成测试](parallel/AH-hy-observability-20261021.md)和[整合验收](parallel/review-integration-20261121.md)。
