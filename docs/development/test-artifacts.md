# 测试产物管理

## 当前范围与完成标准

本次只调整 pytest 自动临时目录、增加隔离生命周期测试和开发说明。验收要求是：
真实子进程使用独立目录与合成 SQLite 文件；正常结束只清理自身目录；显式
`--basetemp` 的父目录可以自动创建，目标路径被尊重。Windows 中文路径与 Tk
兼容处理继续保留。安装依赖、启动服务、使用个人库、运行测量脚本、迁移或删除
历史证据、固件与设备操作均不在本次范围内。

## 自动临时目录的生命周期

`tests/conftest.py` 根据当前 pytest 根目录分配：

```text
data/test-tmp/pytest/run-<进程 PID>-<随机标识>/
```

每次自动运行各自分配目录，`tmp_path` / `tmp_path_factory` 及其 SQLite 测试文件
都位于本次目录内。正常退出（包括断言失败后正常退出）尝试删除本次目录；共享
的 `data/test-tmp/pytest/` 保留，因为其他进程可能已经配置但尚未首次使用夹具。
清理不扫描同级目录，也不处理历史 `.pytest-tmp/`、`.test-runtime/`。

强制终止、解释器崩溃或 Windows 文件占用可能留下 run 目录；清理失败不代表
测试数据已消失。残留不会在下一次运行自动回收，排查时先确认对应进程已结束、
文件是可重建的测试夹具，再按精确目录单独处理。本次没有执行历史清理。

调用者显式指定 `--basetemp` 时，本项目只递归补建其父目录，不提前创建或清空
目标；退出钩子不拥有也不删除该目标。**pytest 首次使用显式 basetemp 时会清空
目标目录已有内容**，不能指向项目数据、历史证据或另一个进程正在使用的目录。
显式路径也应每次唯一，例如：

```powershell
$runName = 'manual-' + [guid]::NewGuid().ToString('N')
uv run --no-sync python -m pytest --basetemp "data/test-tmp/manual/$runName"
```

`data/test-tmp/` 整体被 Git 忽略。脚本保存到 `scripts/` 或 `tests/`；数据集保存到
`datasets/`；需要追溯的实验配置和结果保存到 `experiments/`，不能依赖临时目录
长期保留。私有结果仍需使用被忽略的 `experiments/results/` 或 `experiments/runs/`
子目录；脱敏后的分析报告才进入 `docs/research/`。

## 独立回归验证

```powershell
uv run --no-sync python -m pytest tests/unit/development/test_pytest_temp_lifecycle.py
```

测试将当前工作树的 `tests/conftest.py` 复制到中文且含空格的合成子工程，用现有
解释器启动真实 pytest 子进程。子进程禁用插件自动加载，隔离继承的 pytest 参数
与 `PYTHONPATH`，明确从当前工作树 `src/` 导入 `longmemory` 并核对来源。只写
合成 SQLite 数据，不访问本机配置或服务。

覆盖成功及断言失败后的正常退出清理、历史同级目录保留、绝对与相对显式路径
及其父目录创建、两个活跃进程各自持有 SQLite 后先后退出、首次夹具创建前的
共享父目录保留。强制终止或文件占用后的残留回收不属于自动清理保证。

2026-10-14 独立工作树本地验证使用主项目既有 Python 3.12.13 环境，显式指定当前
工作树作为命令工作目录，并由子进程断言确认导入当前工作树源码：

| 检查 | 实际结果 |
|---|---|
| `test_pytest_temp_lifecycle.py` | 6 项通过，含真实并行进程和延迟首次夹具创建 |
| `test_sqlite_stores.py`、`test_schema_migrations.py` 与 `test_launcher_doubao.py::test_secret_dialog_is_blank_and_saves_only_on_user_action` | 共 14 项通过，覆盖合成库持久化/迁移及 Windows Tk 对话框 |
| Git 忽略规则与退出后工作树 `data/test-tmp/pytest/` | 新旧临时路径均被忽略，自动 run 目录无残留，共享父目录保留 |

没有运行全量测试、服务端接口或历史语音测量，也没有进行新环境安装验收。

## 主目录历史盘点与归位建议（2026-10-14）

以下是对主目录的只读文件类型盘点和当前分支已提交文档引用检查，**不是新电脑
运行验收**。没有执行历史脚本、复算测量、展开或提交私有测量正文，也没有移动
或删除这些文件。建议目标仅供后续独立迁移审查，本轮未实施。

| 当前内容 | 盘点类型与数量 | 已提交引用 | 建议归位与保留边界 |
|---|---|---|---|
| `.pytest-tmp/run-14712-b27a403b` | 17 个文件，`.cc`、`.db` | 没有发现此 run 名的具体引用；旧根目录有文档引用 | 保持原位；新自动夹具进入 `data/test-tmp/pytest/`，历史是否归档须另审查 |
| `.pytest-tmp/run-31932-57f97ddb` | 16 个文件，`.db` | 同上 | 同上 |
| `.pytest-tmp/run-36412-a6beec25` | 20 个文件，`.cc`、`.db` | 同上 | 同上 |
| `.pytest-tmp/run-45900-7f7672da` | 6 个文件，`.db` | 同上 | 同上 |
| `.test-runtime/asr_prefetch_integration.py` | Python 实验脚本 | 研究报告提到同目录两份固定种子实验脚本，未逐名引用 | 审查绝对路径和依赖后，考虑 `scripts/development/xiaozhi/`；保留原始快照及与结果的配对关系 |
| `.test-runtime/benchmark_asr_prefetch_seed.py` | Python 基准脚本，引用集成脚本 | 同上 | 同上；不能直接移动而破坏同目录导入 |
| `.test-runtime/asr-prefetch-integration-results.json` | JSON 实验结果 | [实时优先语音报告](../research/voice-realtime-first-2026-09-15.md) 明确逐名引用 | 考虑被忽略的 `experiments/results/voice-realtime-first-20260915/`；保留原文、摘要、环境与原引用映射，不提交私有正文 |
| `.test-runtime/asr-prefetch-seed-results.json` | JSON 实验结果 | 同上 | 同上 |
| `.test-runtime/doubao-loopback-check.py` | Python 回环检查脚本，导入实时语音与本地 WebSocket 模块 | 未发现文件名具体引用 | 审查是否含本机路径、凭证、服务访问后，考虑 `scripts/development/xiaozhi/`；本轮不执行 |
| `.test-runtime/waiting_decode.py` | Python 解码检查脚本，导入 Opus 与语音等待模块 | 未发现文件名具体引用 | 审查输入路径与数据来源后，考虑开发诊断脚本或合成测试；本轮不执行 |
| `.test-runtime/web_smoke.py` | Python 网页/语音检查脚本，导入 HTTP 与模型客户端模块 | 未发现文件名具体引用 | 审查联网、账号和配置依赖后，考虑开发诊断脚本；不能直接纳入默认离线测试 |

盘点没有发现上述 4 个 run 名或后 3 份脚本名的精确 Git 跟踪引用；这不证明它们
没有外部引用或没有保留价值。文件类型根据目录元数据与静态结构判断，不代表
脚本可在当前环境运行。

根目录旧引用还见 [代码健康说明](../architecture/code-health.md)、
[设备控制探测记录](../deployment/device-control-probe.md)、
[本机目录与依赖](../guides/本机目录与依赖.md)、
[重装系统与重建环境](../guides/重装系统与重建环境.md) 及 `CHANGELOG.md`。
研究报告还引用历史 `.test-runtime/pytest-final-realtime-20260915-62f491`；本次
顶层盘点未见该目录，不能据此宣称已删除、已恢复或已复验。历史文档保留当时
路径与结果，当前测试入口以本说明和 [开发环境](setup.md) 为准。
