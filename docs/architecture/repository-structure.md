# 仓库结构约定

更新：2026-10-14。当前目录概览见 [README](../../README.md)，本文件解释归属；实际模块说明见 [架构总览](overview.md)、[前端结构](../development/frontend-structure.md)。不创建无用途空目录，不把规划目录写成已实现能力。

## 源码与入口

- 根目录日常入口仅 `启动智慧圆屏.cmd`；内部 CMD 在 `scripts/development/launcher/Start.cmd`，React 主机为 `web_app.py`，旧 `app.py` 是 Tk 兼容回退。
- `src/longmemory/core/conversation`、`core/memory` 使用单数领域命名；领域异常在 `core/common/exceptions.py`，不建第二套 infrastructure/errors。
- `methods/` 保存中立契约、白名单工厂和包装，公共类型不绑定现有 L1 模型；`longmemory_v1` 复用 core，不复制算法，见 [方法边界](method-boundary.md)。
- SQLite 实现在 `adapters/storage/`；连接、完整 schema 定义及逐版本迁移在 `infrastructure/database/`，API/CLI 入口负责装配。
- `web/react-chat/` 按实际 `app/`、`pages/`、`features/`、公共组件、API、样式组织，聊天和启动面板共用视觉组件；构建产物由 Python 静态托管，不新增常驻前端进程。
- 固件审计补丁与协议资料在项目中；实际原生工程/SDK 位于登记的 ASCII 兼容区，不联接中文路径，不复制厂商 SDK 内部结构进主仓库。

## 配置、资源与证据

| 目录 | 归属与限制 |
|---|---|
| `config/examples/` | 可提交脱敏模板 |
| `local/config/` | 私有人工配置与偏好；小智 YAML 为唯一管理来源，厂家路径只是生成消费副本 |
| `local/runtime/`、`local/tools/` | 官方固定来源的专属服务/环境/模型/工具，不入 Git |
| `data/` | 个人库/旁库、受控媒体、备份、日志及运行令牌，按内容最小披露，不当公共资料 |
| `tests/` | 测试代码 |
| `datasets/` | 合成或公开的固定测试输入，不放个人对话 |
| `experiments/` | 实验配置、独立输出及分析，不覆盖旧结果 |
| `data/test-tmp/` | 新测试隔离临时产物；pytest 每进程目录并只清自身 |
| `local/archive/` | 私有恢复包、原始快照、配置备份/回执及旧测试证据，不执行旧脚本 |
| `docs/history/`、`docs/releases/` | 可提交文档历史/阶段记录，明确当时语境，不混入原始个人产物 |
| `docs/guides/`、`docs/architecture/`、`docs/requirements/` | 分别维护当前操作、职责/流程、功能与验收边界 |
| `docs/development/parallel/` | 本轮各独立会话的实现/验证/限制记录，主会话整合 |

README/CHANGELOG/ROADMAP 保留当前导航、近期摘要和排期；原完整文档归档需来源 commit、原文 SHA-256、链接重定位及反向还原证据，历史 ADR/研究/测量不批量重写。当前文档与备份路径的精确规则见 [配置管理](../development/configuration.md)、[本地资料](../development/local-assets.md)、[测试产物](../development/test-artifacts.md)。

## 并行工作树

每个独立会话仅编辑分配的 worktree/分支，所有终端操作显式指定 workdir。共享私有配置、三套环境、服务和设备不随工作树复制；可只读复用已安装解释器，但须确认源码导入来自自己工作树，测试使用合成库/临时端口，不联接共享可变 node_modules。本轮分工以 [任务书](../development/并行优化-20261014.md)为准，只有主会话整合/推送。

[整理前全文](../history/current-docs-before-20261014/docs/architecture/repository-structure.md)保留旧结构约定及其上下文。
