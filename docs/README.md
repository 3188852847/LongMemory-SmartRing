# 文档入口

本页按任务导航；当前优先级见 [ROADMAP](../ROADMAP.md)，规则与授权边界见 [AGENTS](../AGENTS.md)。完整清单及分类依据保存在 [documentation-manifest.json](documentation-manifest.json)，维护方法见 [文档维护机制](development/documentation-maintenance.md)。清单覆盖公开 `docs/**/*.md` 与根入口，不读取私有配置、个人库、音频或实验结果。

## 从任务开始

| 要做的事 | 首先阅读的权威入口 | 按需要追加 |
|---|---|---|
| 日常操作 | [使用说明](guides/使用说明.md) | [React 启动面板](guides/React启动面板.md)、[统一启动](guides/统一启动.md) |
| 判断启动窗口与服务生命周期 | [React 启动面板](guides/React启动面板.md) | [启动器契约](development/launcher-contract.md)；恢复档案中的旧 Tk 语义不直接作为当前操作依据 |
| 核对本机布局与依赖 | [本机目录与依赖](guides/本机目录与依赖.md) | [配置管理](development/configuration.md)、[本地资料](development/local-assets.md) |
| 核对恢复证据 | [文字与记忆恢复](guides/恢复文字与记忆-20261013.md)、[语音恢复](guides/恢复语音-20261013.md)、[固件编译恢复](guides/恢复固件编译-20261014.md) | 这些分别管理恢复证据；历史数字不能证明当前改动已通过验收 |
| 调整参考声音或回答角色 | [参考声音与克隆](guides/参考声音与克隆.md)、[助手角色设置](guides/助手角色设置.md) | [声音设置](guides/声音设置.md)；真实克隆听感须另验收 |
| 理解架构或寻找源码 | [架构总览](architecture/overview.md)、[运行流程](architecture/workflows.md)、[仓库结构](architecture/repository-structure.md) | [记忆流程](architecture/memory-pipeline.md)、[方法边界](architecture/method-boundary.md)、对应 ADR |
| 修改前端或配置管理 | [前端结构](development/frontend-structure.md)、[配置管理](development/configuration.md) | [视觉系统](architecture/visual-system.md)、[并行任务书](development/并行优化-20261014.md) |
| 运行测试或核对 CI | [测试产物](development/test-artifacts.md)、[CI 说明](development/continuous-integration.md) | [开发环境](development/setup.md)；本地测试与远程结果分别记录 |
| 判断能力、计划和历史验收 | [ROADMAP](../ROADMAP.md)、[产品能力地图](requirements/product-capability-map.md) | [自定义功能清单](requirements/自定义功能清单.md)、[历史索引](history/README.md)；候选不是执行授权 |
| 追查设计理由或研究方法 | `docs/adr/` 中对应的架构决策记录（ADR） | `docs/research/` 的对应报告；用清单检索主题，不默认通读全部文档 |

同一“事实范围”只指定一个权威文档。例如日常生命周期归 React 启动指南，恢复步骤归对应恢复指南，研究指标归原报告；这里提供链接，不复制版本表、操作命令或测试数字。权威入口表示维护归属，**不表示整篇语义已经核对**。语义核对范围、证据和待办由清单中的 `review` 与 `known_gaps` 明示。

## 状态怎样读

| 清单状态 | 阅读方式 |
|---|---|
| `current` 现行 | 当前任务的维护入口；仍需核对对应实现与生效边界 |
| `reference` 参考 | 设计、协议、实验或候选背景；不直接替代日常指南或执行排期 |
| `historical` 历史 | 保留当时状态、路径、数字与证据；不据此推定当前机器验收 |
| `draft` 草案 | 有明确草案证据的方案；未接受决定不转写为当前能力 |
| `pending` 待核对 | 尚无足够证据确定当前用途；沿关联文档与代码核对后再分类 |
| `superseded` 已被替代 | 有明确替代文档和范围；保留原文与有效的剩余约束 |

时间早不等于失效。ADR 若只被部分替代，仍列为参考，并在 `superseded_by` 写明具体范围；不把其余有效约束一并废除。研究报告与阶段记录的“通过”只属于其记录的代码、环境、数据与时间。

## 快速检索与检查

在当前工作树根目录，使用该项目已安装的 Python；以下命令不安装依赖、不访问网络、不写文档：

```powershell
python -X utf8 -B scripts/development/check_docs.py --query 启动
python -X utf8 -B scripts/development/check_docs.py --changed scripts/development/launcher/web_app.py
python -X utf8 -B scripts/development/check_docs.py --only docs/README.md --strict
python -X utf8 -B scripts/development/check_docs.py --json
```

独立工作树使用已授权的解释器绝对路径，并显式指定工作目录，详见 [维护说明](development/documentation-maintenance.md)。检查器提示失效本地文件链接、旧目录和变更影响候选；它不验证外网链接、标题锚点、模型行为、硬件或整篇语义。历史旧路径只作提示，保留原记录；待核对项不能自动转为已验收。
