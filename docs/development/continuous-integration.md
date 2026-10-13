# 自动化质量检查

CI（持续集成）在每次 PR 或 `main` 推送后重建测试环境并检查代码。
入口是 [quality.yml](../../.github/workflows/quality.yml)；两个 Windows 2025 job 并行，
也支持在 GitHub Actions 页面手动运行。当前项目的 CMD、PowerShell、Tk 和
Playwright 启动器使用 Windows，所以第一版选择与日用系统相同的平台。

## 检查范围

| Job | 检查 | 运行资源 |
| --- | --- | --- |
| Backend synthetic tests | 全部 pytest 中可在主项目依赖运行的合成测试、API、数据库迁移、脚本和配置路径回归；审查实际报告的跳过项 | `.python-version` 的 Python 3.12.13；uv 0.12.23；`uv sync --locked --extra console --group dev` |
| Frontend and browser tests | Vitest；TypeScript 检查与 Vite 构建；Chromium Playwright | `web/react-chat/.node-version` 的 Node 24.19.0；`packageManager` 对应 pnpm 11.19.0；原锁文件 |

没有安装 `semantic` extra、torch、BGE、语音模型、厂家源码或 ESP-IDF。
浏览器通过现有 `playwright_console.py` 启动一次性 Fake 控制台、临时数据库和
离线设备替身，仅监听回环地址 18777；不连接日用控制台和圆屏。
前端 job 用主项目 console 环境启动这个替身，不混用语音专属 Python。

## 允许的专属依赖例外

[backend_quality.py](../../scripts/ci/backend_quality.py)检查 JUnit 报告，
未在清单中的 skip、collection error 或失败都会使检查失败。
因此 aiohttp/Pydantic 等主项目必需依赖缺失不能靠 `importorskip` 通过质量门。

| 例外 | 原因与后续验收 |
| --- | --- |
| `test_transport::test_real_http_and_upstream_mcp_with_simulated_device` | 全新检出没有小智上游源码和 Python 3.10；在语音恢复环境另行验收 |
| `test_xiaozhi_bridge` 的真实上游 dialogue、Python 3.10→3.12 两项 | 同上；该文件其他合成协议回归仍执行 |
| `test_round_wallpaper_library` 的真实 FFmpeg 往返一项 | FFmpeg 是用户下载的专属工具；同文件其他合成边界检查执行 |
| `test_sync_memory_config`、`test_sync_model_config`、`test_sync_role`、`test_sync_tts_backend`、`test_sync_vad_config`、`test_voice_settings` 的模块 collection skip | PyYAML 属于语音环境，主项目 `console/dev` 没有声明该依赖；在现有语音环境执行 |
| `test_launcher` 的网络同步保留配置、拒绝歧义格式两项 | 同样依赖语音环境的 PyYAML；其他启动器回归执行 |
| 精确排除 `tests/unit/development/test_cosyvoice_streaming.py`（16 项） | 被测语音脚本无条件导入 requests，而 requests 不在主项目 console/dev 中；该文件仍由完整本机回归和语音验收执行 |
| `test_cosyvoice_segments` 的实际 v6 installer 分段一项 | 同样通过 streaming 脚本依赖 requests；只 deselect 该项，其他分段策略合成用例执行 |
| `test_local_config_layout` 的 UI 同步后生成 vendor 配置一项 | 同样依赖 PyYAML；该文件其他迁移/回滚/模板/路径隔离用例执行 |
| `test_local_config_layout` 的符号链接创建防护一项 | 仅允许 Windows 不授予创建合成 symlink 权限这一原因；同文件实际 junction 防护用例仍执行 |

例外是明确的验收边界，不是上述功能已经在线验证的证据。不要为让 CI 变绿
扩大目录排除范围或直接允许所有 skip。新增配置迁移等测试默认进入全 pytest。

## 依赖、权限与产物

所有 action 固定完整 commit，并在注释注明官方 release；Python/Node 按已有
版本声明，依赖用锁文件检查而不重新解析。工作流只使用 `contents: read`，
checkout 不保留凭证，不使用个人 Secret 或 `pull_request_target`。
同分支新任务取消旧任务，两项检查都有超时；没有发布、烧录或自动合并步骤。

GitHub 托管 runner 为一次性环境，CI 中的依赖和 Chromium 安装仅发生在那里；
不改变本机工具、代理和环境。此次实现没有在本机安装或下载新依赖。
第一版关闭跨运行缓存与产物上传，避免把测试目录之外的配置、数据库或日志
带进共享制品；合成测试结果可直接在 job 日志中查看。
后端 JUnit 位于忽略的 `data/test-tmp/ci/backend.xml`。

## 本地复查与验收状态

已经配置主项目依赖时，可以从项目根目录执行：

```powershell
.\.venv\Scripts\python.exe scripts/ci/test_backend_quality.py
.\.venv\Scripts\python.exe scripts/ci/backend_quality.py
```

CI 的后端入口显式选择当前检出 `src` 并检查来源；在多工作树环境不会让
本机另一工作树的 editable 安装替代待检查代码。pytest 使用每进程独立临时目录。
上述入口不负责依赖安装；用户需要重建依赖时仍自行执行已审阅命令。

2026-10-14：工作流 YAML 已由现有解析器读取，质量报告护栏的 5 项合成自测通过。
本地验证通过屏蔽 yaml/requests/torch/transformers 等未声明依赖，模拟
`console/dev` 的导入边界：本分支后端入口运行 1904 项通过、12 个明确跳过、
1 项 requests 专属用例 deselect（另 16 项 requests 专属文件未收集）。
此数量是并行配置/前端分支合并前的验证；合并后应按实际报告重新核对。
这不等于在干净机器成功安装依赖。
首次 GitHub Actions 在线安装和运行尚待推送后的实际结果，不能用本地检查
代替远程成功。尚未修改仓库分支保护；若要禁止失败 PR 合并，需要仓库所有者
把这两个 job 配置为必需状态检查。

官方依据：[uv GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/)、
[setup-uv v6.8.0](https://github.com/astral-sh/setup-uv/releases/tag/v6.8.0)、
[checkout v4.2.2](https://github.com/actions/checkout/releases/tag/v4.2.2)、
[setup-node v4.4.0](https://github.com/actions/setup-node/releases/tag/v4.4.0)、
[Playwright CI](https://playwright.dev/docs/ci)。
