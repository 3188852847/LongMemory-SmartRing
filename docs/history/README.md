# 项目历史档案

归档日期：2026-10-14（Asia/Shanghai）。当前使用入口与恢复状态见[项目首页](../../README.md)，近期变更见[CHANGELOG](../../CHANGELOG.md)。

## 完整原文与来源

本轮把根目录的长篇过程记录移入档案，完整保留基线提交 `9db0a9eb764e27d4a93233fe03e032117c340e81` 的两份文档。该提交为 `docs: verify restored ESP-IDF 5.5.4 firmware builds`。

| 来源文件 | 完整档案 | 原文行数 | 原文 SHA-256（Git blob 字节，UTF-8 / LF） |
|---|---|---:|---|
| `README.md` | [README 快照](README-20261014.md) | 558 | `bd63d9aabde086e301fe3fb3394a755f32016a482c01921c109a9b9822821d25` |
| `CHANGELOG.md` | [完整变更记录](../releases/CHANGELOG-through-20261014.md) | 1477 | `2ba27a95609c7fce51e7ff174e6defcde7f9f78832c75790974338548f67b2a1` |

两份档案各增加四行归档说明；原文的标题、段落、代码块、数字、历史结论与候选清单全部保留。只改变实际 Markdown 相对链接的目标：原 `docs/...` 改为 `../...`，原根目录 `ROADMAP.md` 改为 `../../ROADMAP.md`；外部链接与原有锚点保留。README 共重定位 120 处链接，CHANGELOG 共重定位 8 处链接。正文内的旧目录、代码块和命令原样保留，不能直接视为现行操作步骤。

归档完整性按以下方式核对：剥离新增的四行说明，反向还原上述链接目标，再与基线 Git blob 逐字节比较。原文也始终可从 Git 读取：

```powershell
git show 9db0a9eb764e27d4a93233fe03e032117c340e81:README.md
git show 9db0a9eb764e27d4a93233fe03e032117c340e81:CHANGELOG.md
```

## 阅读边界

- 档案保留每项记录的日期与原先语境。“未完成”“当前”“已验收”均指该段记录当时的状态。
- 重装前的测试数量、性能测量、固件烧录和实机反馈是历史证据，不能证明新电脑完成同项验收。
- 新电脑的文字、记忆、语音与固件编译边界，以[文字与记忆恢复](../guides/恢复文字与记忆-20261013.md)、[语音恢复](../guides/恢复语音-20261013.md)、[固件编译恢复](../guides/恢复固件编译-20261014.md)及后续明确记录为准。
- 原 README 的旧启动命令、历史外部资源路径和旧仓库目录保留作历史资料；日常使用根目录 `启动智慧圆屏.cmd`。
- 未来候选和早期路线标识不构成已实现能力或新增授权；现行优先级见[ROADMAP](../../ROADMAP.md)。

## 已有阶段档案

### ROADMAP 归档（2026-10-14 路线更新）

[旧 ROADMAP 完整档案](ROADMAP-through-20261014.md)来自提交
`075ea23ca2b8e351e083cdfc2cbb8083e43031e0` 的 `ROADMAP.md`，原文 323 行，
Git blob 字节 SHA-256 为 `ddd7f6ce8d5f9c8d00a83daf67cfac6cc94552073f5d99a81271ae6485fde48f`。
档案增加四行说明，仅把 53 处 Markdown 链接的 `docs/` 前缀改为 `../`；正文、
历史结论、数字、阶段标识和候选内容保留。去掉四行说明并反向还原链接后，应与
来源 Git blob 逐字节一致。可用以下命令读取原文：

```powershell
git show 075ea23ca2b8e351e083cdfc2cbb8083e43031e0:ROADMAP.md
```

现行根 ROADMAP 已按新电脑恢复结果与近期体验讨论更新。旧档案不是当前任务清单，
不把旧机器的烧录、性能测量或未来版本规划作为本机验收与新增授权。

### 现行规则与指南整理前快照

[来源与反向还原清单](current-docs-before-20261014/manifest.json)保留来源提交、原文 SHA-256 与链接重定位信息。八份 AGENTS、现行指南和架构文档的整理前原文均核对了反向逐字节还原；当前入口见[文档导航](../README.md)，快照不是现行操作或新增授权。

### 日用与发布记录

- [2026-09-15 语音阶段交接](../releases/voice-stage-handoff-2026-09-15.md)
- [2026-09-15 V1 接续审计](../releases/v1-followup-audit-2026-09-15.md)
- [V1 RC1 就绪检查](../releases/v1-rc1-readiness.md)
- [V1 RC1 日用观察](../releases/v1-rc1-observation.md)

研究记录继续保存在 `docs/research/`，架构决策记录（ADR）继续保存在 `docs/adr/`；本轮不改写已有研究、操作指南或决策历史。
