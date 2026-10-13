# 智慧圆屏

一个以长程记忆研究为主体、面向日常陪伴的个人软件系统；SmartRing-Plus 圆屏终端是基于 ESP32-S3 的智能圆形显示屏开发板。

记忆核心保持提取、存储、检索、上下文构建与管理职责可分离，通过适配层接入小智服务和圆屏。设备负责采集、显示与播放，记忆与实验逻辑在电脑端运行。

项目原名 LongMemory-SmartRing；产品展示名已更新，内部 `longmemory` 包、命令、协议与数据库标识保留，以兼容历史数据和接口。

## 日常使用

**唯一日常入口：双击项目根目录 [启动智慧圆屏.cmd](启动智慧圆屏.cmd)。**

1. 在启动面板核对当前模式、模型、角色和记忆选择。
2. 点击“启动服务并打开网页”，由面板管理网页、记忆与圆屏语音服务。
3. 结束时使用面板停止服务；关闭启动器也会停止它管理的服务。

当前默认是圆屏语音、CosyVoice3、保留的官方模型与助手角色、模型辅助提取和关键词＋本地 BGE 混合召回。BGE 将文字编码成向量，用于补充关键词检索。

文字模式暂停圆屏定时联系；圆屏模式按保留的主动交流设置和事件账本运行。低频记忆整理、L1/L2 影子模型复核暂时关闭。

详细操作与恢复边界先查下面三份现行指南；历史命令执行前须核对当前目录和状态。

## 当前已恢复能力

以下是 2026-10-13～14 新电脑恢复记录的摘要；本次文档整理未重新运行业务验收。

| 范围 | 本机已完成 | 依据 |
|---|---|---|
| 文字与记忆 | 原代码、Git 历史与个人数据恢复；文字入口、记忆页面、BGE CPU 离线编码、隔离写入与重启召回通过 | [文字与记忆恢复](docs/guides/恢复文字与记忆-20261013.md) |
| 原日用语音 | Silero 判停、SenseVoice 听写、记忆查询、官方模型回答、CosyVoice3 合成与 Opus 编解码通过；所有者确认实机声音、连续对话、打断和记忆回答正常 | [语音恢复](docs/guides/恢复语音-20261013.md) |
| 固件编译 | ESP-IDF 5.5.4、ESP32 最小工程、ESP32-S3 原圆屏完整编译及独立干净目录重建通过；组件摘要、镜像和分区容量核验通过 | [固件编译恢复](docs/guides/恢复固件编译-20261014.md) |

**本轮恢复没有烧录或更新设备固件。** SDK 5.5.4 与机器默认 6.1 并行，编译通过不代表新产物已在设备运行。

历史功能、旧测试数量与重装前实机记录不代表本机全仓回归或完整 V1 发布验收。VoxCPM2、sanoTTS、AuK 与豆包备用等历史候选/替代链路不属于本次已恢复主链路。

## 环境与本机资源

主项目实际位置为 `D:\03-项目\01-正式项目\智慧圆屏`。下表的相对位置均以主项目根为基准，独立工作树不携带运行资源或个人数据。

| 日用 Python 环境 | 位置 | 固定版本与职责 |
|---|---|---|
| 主项目 | `.venv/` | Python 3.12.13；文字、记忆与 CPU BGE，使用原 `uv.lock` |
| 小智 | `local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/.venv/` | Python 3.10.20；语音服务、听写与圆屏通信 |
| CosyVoice | `local/runtime/CosyVoice/.venv/` | Python 3.10.20；GPU 语音合成 |

三套环境分别维护，避免不同 torch 相互覆盖。固件 SDK 另用 EIM 管理的 Python 3.11.15 专属环境，不混入日用环境。

前端位于 `web/react-chat/`，固定 Node 24.19.0、pnpm 11.19.0 和原 `pnpm-lock.yaml`。依赖安装、资源下载和联网拉取由所有者执行，按现行指南重建，不直接复用备份中的外部资源。

| 本机资源 | 实际位置 |
|---|---|
| BGE 模型 | `local/runtime/models/bge-small-zh-v1.5/7999e1d3359715c523056ef9478215996d62a620/` |
| 小智、CosyVoice 与模型 | `local/runtime/`；精确版本和模型子目录见语音恢复指南 |
| WeText 缓存 / FFmpeg | `local/runtime/modelscope-cache/` / `local/tools/ffmpeg/bin/` |
| ESP-IDF 5.5.4 SDK | `D:\Dev\esp\v5.5.4\esp-idf` |
| 固件工作源码 / 构建产物 | `D:\Dev\esp-projects\smart-ring\src` / `D:\Dev\esp-projects\smart-ring\build-idf554` |

固件原生构建使用登记的 ASCII 路径；本仓库保存补丁、固定版本记录与编译入口，后续源码修改须留下可审计补丁。

## 目录导航

| 目录 / 文档 | 用途 |
|---|---|
| `src/longmemory/` | 独立记忆核心、适配层与程序入口 |
| `web/react-chat/`、`scripts/` | 网页控制台、启动与开发工具 |
| `tests/`、[datasets](datasets/README.md)、`experiments/` | 测试代码、评估输入、实验配置与结果；与个人数据隔离 |
| [测试产物管理](docs/development/test-artifacts.md) | 当前自动临时目录、清理边界与历史测量资料归位 |
| `firmware/smartring_plus/` | 项目自有固件补丁和恢复记录 |
| `config/examples/`、`local/config/` | 公开脱敏模板、私有配置与偏好；[配置管理](docs/development/configuration.md) |
| `data/`、`local/runtime/`、`local/archive/` | 日用数据、专属资源、历史恢复档案；[资料归属](docs/development/local-assets.md)；真实内容不提交 Git |
| [前端模块](docs/development/frontend-structure.md)、[自动化质量检查](docs/development/continuous-integration.md) | 实际源码归类、提交后的自动检查及验收边界 |
| [系统架构](docs/architecture/overview.md)、[运行流程](docs/architecture/workflows.md) | 当前职责边界与运行步骤 |
| [V1 日用范围](docs/requirements/v1-personal-companion.md)、[ROADMAP](ROADMAP.md) | 阶段完成标准与 P1～P5 优先级 |
| `docs/adr/`、`docs/research/` | 架构决策记录（ADR）与可追溯研究证据 |

未来功能见[产品能力地图](docs/requirements/product-capability-map.md)与[自定义功能清单](docs/requirements/自定义功能清单.md)；候选清单不代表已实现或已授权开发。

## 历史与维护

- [近期变更](CHANGELOG.md)：本机恢复摘要与本轮文档整理。
- [历史档案索引](docs/history/README.md)：完整旧首页、累计 CHANGELOG、基线提交与完整性校验依据。
- [原 README 快照](docs/history/README-20261014.md)与[完整历史变更记录](docs/releases/CHANGELOG-through-20261014.md)：保留历史过程、实验结果和当时的候选语境。

密钥、个人数据库、真实对话、音频与私有备份不进入版本库；查看/删除记忆的边界以现行操作指南为准，批量清理须单独授权。

许可证尚未决定；引入第三方代码须核对其许可证并保留声明。
