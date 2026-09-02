# LongMemory-SmartRing

一个面向个人智能终端的长程记忆研究项目。

本项目以独立、可测试的 LongMemory Core 为研究主体，后续通过适配层接入 Xiaozhi Server 和 SmartRing-Plus 智能圆屏。

> SmartRing-Plus 是基于 ESP32-S3 的智能圆形显示屏开发板，不是可穿戴戒指。

## 当前状态

项目处于 **V0.1 首个纵向闭环已跑通、继续补齐版本能力** 阶段。

已经完成：

- [x] 明确 LongMemory Core、Xiaozhi 与圆屏终端的系统边界
- [x] 确定 Python 3.12、uv、SQLite、pytest 和模块化单体路线
- [x] 确定 V0.1 只实现 L0 原始对话与 L1 原子记忆
- [x] 建立工程骨架、协作规则、需求、ADR 和研究计划
- [x] 完成 SmartRing-Plus-B 基础硬件识别验证
- [x] 实现 L0 原始消息与 L1 原子记忆领域模型及来源追踪
- [x] 实现 SQLite 建表、L0/L1 持久化和跨应用实例重开验证
- [x] 实现确定性的第一人称陈述提取 Baseline
- [x] 实现基础关键词检索、受控上下文构建和 Fake 回答生成器
- [x] 实现聊天应用服务和 `build_application()` 装配入口
- [x] 建立单元、SQLite 集成和写入—重开—回忆端到端测试

尚未完成：

- [ ] 可交互的 PC 端 CLI
- [ ] 记忆查看、删除和撤销应用用例
- [ ] 重复记忆处理和助手回答的 L0 持久化
- [ ] 关键路径脱敏日志和可观察信息
- [ ] 固定评估数据集与无记忆 Baseline 对照实验
- [ ] 真实模型适配器

当前闭环采用确定性规则和 Fake 回答生成器，目的是验证架构、持久化和测试链路。它不是通用语义记忆系统，也不代表已经接入真实 LLM。

## V0.1 目标

V0.1 需要证明：

> 用户输入一条值得记忆的信息后，系统保存其原始来源和规范化记忆；程序完全退出并重新启动后，仍能根据新问题找到该记忆并用于回答。

最小闭环：

```text
输入
  → 保存 L0 原始对话
  → 提取并保存 L1 原子记忆
  → 完全退出并重新启动
  → 检索相关 L1
  → 构建受控上下文
  → 生成回答
  → 验证来源与结果
```

### In Scope

- PC 端 CLI 文本交互
- 单用户本地实验
- L0、L1、SQLite 和来源追踪
- 基础提取、检索、上下文注入和回答
- 查看、删除和撤销记忆
- 固定测试集、必要日志和无记忆 Baseline

### Out of Scope

- SmartRing-Plus 实机接入和 Xiaozhi 正式集成
- ASR、TTS、Web UI 和公网部署
- 独立向量数据库、知识图谱和多模态记忆
- L2/L3、复杂冲突消解、遗忘、衰减和主动提醒
- 多用户和生产级权限系统

## 架构边界

```text
entrypoints
    ↓
application
    ↓
core ← contracts → adapters
    ↑
infrastructure
```

- `core`：领域模型、契约和记忆规则，不依赖 CLI、SQLite 或模型 SDK。
- `application`：组织一轮聊天和记忆管理用例。
- `adapters`：SQLite 与 LLM 的可替换实现。
- `infrastructure`：配置、连接、建表、日志和依赖装配。
- `entrypoints`：CLI，以及后续 API 和 Xiaozhi 入口。

领域异常统一放在 `core/common/exceptions.py`，不创建重复的 `infrastructure/errors/`。

## 当前仓库结构

下面是当前采用的唯一骨架。目录存在不代表功能已经实现。

```text
LongMemory-SmartRing/                              # 项目根目录
├─ .github/                                        # GitHub 协作和自动化配置
│  ├─ ISSUE_TEMPLATE/                              # Issue 模板预留
│  └─ workflows/                                   # CI 工作流预留，首个测试通过后启用
├─ data/                                           # 本地运行数据，真实内容不提交
│  ├─ databases/                                   # SQLite 数据库
│  ├─ logs/                                        # 运行与调试日志
│  ├─ exports/                                     # 用户主动导出的数据
│  ├─ backups/                                     # 迁移或危险操作前的备份
│  └─ audio/                                       # 后续语音阶段的本地音频
├─ datasets/                                       # 固定、可版本化的评估输入
│  ├─ synthetic/                                   # 人工合成样例
│  ├─ benchmarks/                                  # 外部公开 Benchmark
│  ├─ regression/                                  # 固定回归数据
│  └─ README.md                                    # 数据来源、格式和许可
├─ docs/                                           # 长期文档和决策记录
│  ├─ requirements/                                # 版本范围与完成标准
│  │  └─ v0.1.md                                   # V0.1 需求
│  ├─ architecture/                                # 架构和数据流
│  │  ├─ overview.md                               # 总体模块边界
│  │  ├─ memory-pipeline.md                        # 记忆纵向流水线
│  │  └─ repository-structure.md                   # 仓库结构约定
│  ├─ adr/                                         # Architecture Decision Record
│  │  ├─ 0001-modular-monolith.md                  # 模块化单体
│  │  ├─ 0002-l0-l1-memory-model.md                # L0/L1 模型
│  │  └─ 0003-local-sqlite-storage.md              # 本地 SQLite
│  ├─ development/                                 # 开发和排障指南
│  │  ├─ setup.md                                  # uv 与 PyCharm 环境
│  │  └─ troubleshooting.md                        # 已确认故障记录
│  ├─ research/                                    # 研究问题和评估设计
│  │  ├─ research-questions.md                     # 当前研究问题
│  │  ├─ baseline-plan.md                          # Baseline 计划
│  │  └─ evaluation-plan.md                        # 分阶段指标
│  ├─ hardware/                                    # 圆屏硬件事实与验证记录
│  ├─ deployment/                                  # 后续部署文档
│  └─ versions/                                    # 版本状态和复盘
│     └─ v0.1.md                                   # V0.1 版本记录
├─ experiments/                                    # 实验配置、运行产物和报告
│  ├─ configs/                                     # 可复现实验配置
│  ├─ runs/                                        # 每次实验的原始运行产物
│  ├─ results/                                     # 结构化结果
│  └─ reports/                                     # 可阅读报告
├─ firmware/                                       # 后续圆屏终端集成
│  ├─ smartring_plus/                              # 本项目设备端内容
│  │  ├─ main/                                     # ESP-IDF 应用入口
│  │  ├─ components/                               # 自有 ESP-IDF 组件
│  │  ├─ assets/                                   # 圆屏资源
│  │  └─ docs/                                     # 设备端说明
│  ├─ configs/                                     # 可提交的设备配置示例
│  ├─ patches/                                     # 针对明确上游版本的补丁
│  └─ README.md                                    # 上游边界和使用约定
├─ notebooks/                                      # 探索性分析，稳定逻辑迁回源码
├─ scripts/                                        # 可重复执行的辅助脚本
│  ├─ development/                                 # 本地开发辅助
│  ├─ evaluation/                                  # 批量评估
│  ├─ maintenance/                                 # 导入导出和维护
│  └─ migration/                                   # 数据结构迁移
├─ src/                                            # Python src layout 根目录
│  └─ longmemory/                                  # LongMemory 主包
│     ├─ __init__.py                               # 包标识和版本
│     ├─ __main__.py                               # python -m longmemory 入口
│     ├─ bootstrap.py                              # 依赖装配
│     ├─ core/                                     # 不依赖外部技术的核心层
│     │  ├─ common/                                # 公共类型和领域异常
│     │  │  ├─ identifiers.py                      # 稳定标识符
│     │  │  └─ exceptions.py                       # 领域异常
│     │  ├─ conversation/                          # L0 原始对话
│     │  │  ├─ models.py                           # 会话与消息模型
│     │  │  └─ contracts.py                        # L0 存储契约
│     │  └─ memory/                                # L1 及未来记忆能力
│     │     ├─ models.py                           # 记忆与来源模型
│     │     ├─ contracts.py                        # 记忆存储和模型契约
│     │     ├─ extraction/                         # 记忆判断与规范化
│     │     │  ├─ policy.py                        # 提取规则
│     │     │  └─ service.py                       # 提取服务
│     │     ├─ retrieval/                          # 基础召回和上下文构建
│     │     │  ├─ service.py                       # 检索服务
│     │     │  └─ context_builder.py               # 受控上下文
│     │     ├─ l0_conversation/                    # L0 后续扩展位置
│     │     ├─ l1_atomic/                          # L1 后续扩展位置
│     │     ├─ l2_scenario/                        # L2 预留，V0.1 不实现
│     │     ├─ l3_persona/                         # L3 预留，V0.1 不实现
│     │     ├─ conflict_resolution/                # 冲突处理预留
│     │     ├─ forgetting/                         # 遗忘机制预留
│     │     └─ consolidation/                      # 记忆整合预留
│     ├─ application/                              # 用例编排层
│     │  ├─ chat/                                  # 一轮聊天闭环
│     │  │  ├─ contracts.py                        # 回答生成器契约
│     │  │  ├─ dto.py                              # 聊天输入输出
│     │  │  └─ service.py                          # 聊天用例
│     │  └─ memory_management/                     # 查看、删除和撤销
│     │     ├─ dto.py                              # 管理输入输出
│     │     └─ service.py                          # 管理用例
│     ├─ adapters/                                 # 外部技术适配器
│     │  ├─ storage/                               # SQLite 存储实现
│     │  │  ├─ sqlite_conversation_store.py        # L0 SQLite 实现
│     │  │  └─ sqlite_memory_store.py              # L1 SQLite 实现
│     │  └─ llm/                                   # LLM 实现
│     │     ├─ fake.py                              # 可预测测试模型
│     │     └─ openai_compatible.py                 # 后续真实模型适配
│     ├─ infrastructure/                           # 跨模块基础设施
│     │  ├─ config/                                # 环境变量和运行配置
│     │  │  └─ settings.py                         # 类型化设置
│     │  ├─ database/                              # SQLite 连接和结构
│     │  │  ├─ connection.py                       # 连接与事务
│     │  │  ├─ schema.py                           # 初始结构
│     │  │  └─ migrations/                         # 可追溯迁移
│     │  └─ logging/                               # 日志配置
│     │     └─ setup.py                             # 脱敏日志初始化
│     ├─ entrypoints/                              # 外部入口
│     │  ├─ cli/                                   # V0.1 命令行入口
│     │  │  ├─ app.py                              # CLI 启动
│     │  │  ├─ commands.py                         # 管理命令
│     │  │  └─ presenter.py                        # 输出格式
│     │  ├─ api/                                   # 后续 HTTP API
│     │  │  └─ routes/                             # API 路由预留
│     │  └─ xiaozhi/                               # 后续 Xiaozhi 入口
│     │     ├─ adapter.py                          # 协议适配
│     │     └─ mapping.py                          # 消息映射
│     ├─ evaluation/                               # 评估逻辑
│     │  ├─ metrics.py                             # 分阶段指标
│     │  ├─ runner.py                              # Baseline/实验组运行器
│     │  └─ reports.py                             # 报告输出
│     └─ prompts/                                  # 可版本化 Prompt 资源
│        ├─ extraction/                            # 提取 Prompt
│        ├─ generation/                            # 回答 Prompt
│        ├─ evaluation/                            # 辅助评估 Prompt
│        └─ consolidation/                         # 后续整合 Prompt
├─ tests/                                          # 自动化测试代码
│  ├─ unit/                                        # 快速单元测试
│  │  ├─ core/                                     # 核心规则测试
│  │  ├─ application/                              # 用例编排测试
│  │  └─ adapters/                                 # 适配器测试
│  ├─ integration/                                 # 多模块和真实 SQLite 测试
│  │  ├─ database/                                 # 数据库集成
│  │  └─ memory_pipeline/                          # 记忆流水线集成
│  ├─ e2e/                                         # 写入—重启—回忆闭环
│  ├─ regression/                                  # 已修复问题回归
│  ├─ data/                                        # 测试内部小型 fixture
│  └─ conftest.py                                  # pytest 公共夹具
├─ web/                                            # 后续 Web 管理界面
│  ├─ public/                                      # 静态资源
│  ├─ src/                                         # 前端源码
│  │  ├─ api/                                      # 后端请求
│  │  ├─ components/                               # 通用组件
│  │  ├─ features/                                 # 业务功能
│  │  └─ styles/                                   # 全局样式
│  └─ README.md                                    # V0.1 不选型
├─ .env.example                                    # 安全配置示例
├─ .gitattributes                                  # 换行和二进制属性
├─ .gitignore                                      # 密钥、数据和构建产物排除
├─ .python-version                                 # Python 版本固定
├─ AGENTS.md                                       # 人机协作规则
├─ CHANGELOG.md                                    # 已完成变更
├─ ROADMAP.md                                      # 后续版本计划
├─ pyproject.toml                                  # Python 项目与工具配置
├─ uv.lock                                         # 由 uv 自动生成的依赖锁
└─ README.md                                       # 项目总览与真实状态
```

### 骨架约定

- Python 包目录使用 `__init__.py`，它可以合法为空。
- 普通空目录使用 `.gitkeep`，避免 Git 丢失目录。
- `uv.lock` 必须由 uv 生成，不能手工创建空文件。
- 未实现模块只表示扩展位置，不写成当前功能。
- `src/` 本身不是 Python 包，因此不放 `src/__init__.py`。
- 许可证尚未决定，因此暂不保留空 `LICENSE`。

## 开发环境

```powershell
cd "D:\02-项目\LongMemory-SmartRing"
uv sync
uv run python --version
uv run pytest -p no:cacheprovider
```

当前自动化测试覆盖领域模型、记忆提取、基础检索、聊天编排、SQLite 重开持久化和最小端到端闭环。`-p no:cacheprovider` 仅关闭 pytest 的本地缓存写入，不影响测试行为。

PyCharm 解释器选择：

```text
D:\02-项目\LongMemory-SmartRing\.venv\Scripts\python.exe
```

## 数据与隐私

- L0、L1 默认保存在运行 LongMemory 的电脑或私有服务器，不放在圆屏中。
- `.env`、真实对话、SQLite、原始音频和运行日志不得提交。
- API Key 只通过环境变量或本地密钥配置提供。
- 测试优先使用合成数据。
- 每条 L1 必须保留 L0 来源，且支持查看和删除。

## 路线图

```text
V0.1  PC 文本版 L0/L1 持久记忆闭环
V0.2  语义检索和混合召回
V0.3  分类、重要度和去重
V0.4  冲突更新
V0.5  遗忘、衰减和整合
V0.6  L2 场景记忆和 L3 用户画像
V0.7  Xiaozhi Server 适配
V0.8  SmartRing-Plus 圆屏终端接入
V0.9  长周期实验和主动记忆
```

## 参考资料

- [SmartRing-Plus](https://gitee.com/VIEWESMART/SmartRing-Plus)
- [Xiaozhi AI 开发资料](https://xiaozhi.dev/)
- [Xiaozhi ESP32](https://github.com/78/xiaozhi-esp32)
- [Xiaozhi ESP32 Server](https://github.com/xinnan-tech/xiaozhi-esp32-server)
- [TencentDB Agent Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory)

## 许可证

许可证尚未决定。正式引入第三方代码前，需要分别核对其许可证和保留声明要求。
