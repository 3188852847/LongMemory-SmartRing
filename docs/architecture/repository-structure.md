# 仓库结构约定

## 从陪伴体验读代码

当前产品面向一个人、一位伙伴、两个入口。圆屏可以呈现桌宠并进行语音交流，网页也要能与这位伙伴互动。记忆服务于相处，例如记住称呼、接上昨天的话题、允许用户纠正。以下为 2026-11-21 以提交 `00691b2c` 为起点的源码梳理，已同步日用聊天归档和 Hy-Memory 装配的改动。需求对照采用《智慧圆屏个人陪伴智能体产品需求说明书》V1.3 第 8、12、15 和 19 章，并纳入本次明确的网页桌宠方向。

## 源码与入口

| 从哪里看 | 这段代码做什么 | 核心文件 |
| --- | --- | --- |
| 双击启动 | 根命令进入内部启动器。控制器根据选择拉起网页服务及圆屏所需的语音服务。启动面板和聊天网页是两个入口。 | [根命令](../../启动智慧圆屏.cmd) · [内部启动命令](../../scripts/development/launcher/Start.cmd) · [服务启动参数](../../scripts/development/launcher/runtime.py) |
| 网页上发一句话 | 页面带着聊天编号发送消息。后端读取这段聊天的历史，调用记忆与回答模型，将完成的轮次存进会话旁库。刷新后可以按聊天编号继续。 | [聊天页](../../web/react-chat/src/pages/ChatApp.tsx) · [接收消息](../../src/longmemory/entrypoints/api/routes/chat.py) · [生成回答](../../src/longmemory/entrypoints/api/chat_backend.py) · [会话存储](../../src/longmemory/entrypoints/api/chat_store.py) |
| 对圆屏说一句话 | 设备与小智语音服务交换音频。小智的记忆适配器把识别后的文字送到电脑上的记忆服务，并回报完成的轮次；语音链路使用选定的合成服务完成播报。 | [小智启动与接入](../../scripts/development/xiaozhi/launch_with_memory.py) · [圆屏记忆适配](../../scripts/development/xiaozhi/longmemory_provider.py) · [CosyVoice 声音服务](../../scripts/development/cosyvoice/service.py) |
| 想知道它为何记得 | 电脑上的运行服务为当前对话准备记忆上下文；日用装配入口连接 Hy-Memory。网页提供查来源、纠正和管理入口。 | [运行服务](../../src/longmemory/application/memory_runtime.py) · [引擎装配](../../src/longmemory/bootstrap.py) · [管理接口](../../src/longmemory/entrypoints/api/routes/memory_engine.py) |
| 设置它是谁 | 网页角色设置保存名字、提示词和修订记录。网页保存后，圆屏配置有单独的核对与应用步骤。用户画像描述用户，助手角色描述伙伴。 | [角色存储](../../src/longmemory/entrypoints/api/role_settings.py) · [两端角色接口](../../src/longmemory/entrypoints/api/routes/assistant_role.py) |
| 在圆屏或网页看表情 | Otto 有 21 种命名表情。固件按设备状态和服务端情绪决定显示；网页预览从本地服务读取动图，手动切表情只改变浏览器预览。已有真机控制包括音量、亮度等，桌宠互动要单独接入。 | [固件显示规则](../../scripts/development/otto_firmware/otto_state.h) · [固件接入补丁](../../firmware/smartring_plus/patches/0014-otto-gif-face.patch) · [网页预览](../../web/react-chat/src/features/device/OttoPreview.tsx) · [设备控制接口](../../src/longmemory/entrypoints/api/routes/device.py) |
| 更换回答模型 | 网页和圆屏可有各自的模型选择。现有配置支持学校和官方档案及兼容接口。V1.3 要求模型和数据都留在自有局域网，需验证实际推理、提取与语音依赖的去向。 | [模型配置与选择](../../src/longmemory/infrastructure/config/model_profiles.py) · [回答模型适配](../../src/longmemory/adapters/llm/openai_compatible.py) |

网页当前默认进入聊天页，圆屏预览在单独的页面。把桌宠放到网页日常入口时，可以先复用已有表情渲染，保留预览页供调试。[页面路由](../../web/react-chat/src/app/ConsoleApp.tsx)

## 两个入口之间还缺什么

- **同一段对话。** 网页把消息追加到选中的 `chat_id`，为该聊天构造历史；圆屏适配器持有自己的 `session_id`。即使两端都能召回同一条长期记忆，圆屏刚说的“第二个方案”也未必出现在网页当前对话里。V1.3 的 SC-06 / MVP-ACC-03 需要两端能选中同一段聊天，按顺序读取同一组话轮。[网页消息处理](../../src/longmemory/entrypoints/api/routes/chat.py) · [圆屏会话来源](../../scripts/development/xiaozhi/longmemory_provider.py)
- **同一位可互动的伙伴。** 可以复用 Otto 的画面和优先级。当前网页请求的是素材清单和图片。在已核对的网页、设备控制和固件入口中，尚未找到“用户点伙伴 → 服务端接受互动 → 两端按当前状态给出反馈”的完整通路。V1.3 的 CORE-INT-01 已包含轻点反馈；让它成为网页的日常交互，是本轮进一步明确的方向。[预览接口](../../src/longmemory/entrypoints/api/otto_preview.py) · [圆屏预览页](../../web/react-chat/src/pages/RoundDisplayApp.tsx)
- **日用运行条件。** 主控制台当前绑定电脑本机地址。若要从另一台局域网设备在浏览器继续聊天，要同时设计进入和撤销访问的方式。全部模型在本机运行、圆屏播报时自然插话，是 V1.3 的产品目标；这次未启动模型、未触碰设备，无法给出本机资源或实机延迟结论。[服务入口](../../src/longmemory/entrypoints/api/server.py) · [本机部署与恢复](../guides/本机目录与依赖.md)

## 建议先做的一小段体验

圆屏待机时伙伴在场，打开网页也能看见它。在网页点一下，它用表情回应；网页打字时圆屏保持安静。随后在圆屏说“刚才那个方案”，网页能打开同一段对话继续聊。

技术上先在现有电脑后端明确三件事：保存哪一份角色设定、两端如何选中同一段对话、一次轻点应呈现什么反馈。名字和称呼需要跨重启保留，“正在听”随真实语音状态结束，离线时错过的一次招呼可以过期。网页和固件各自绘制画面；完整家园、养成数值和游戏等这段体验可用后再排。

## 配置、资源与证据

- Python 源码位于 `src/longmemory/`。从 `entrypoints/` 找入口，`application/` 找业务流程，`core/` 找领域规则，`methods/` 找 Hy-Memory 的适配代码，`adapters/` 找模型、设备与存储的具体接法，`infrastructure/` 找配置和数据库结构。角色提示词放在 `prompts/`。
- `web/react-chat/` 是现行网页；`web/` 顶层的静态页面供兼容入口使用。`scripts/development/` 同时包含正式启动器、小智适配、声音服务和离线工具，有运行时依赖。[前端说明](../../web/README.md)
- `local/config/` 存人工配置，`local/runtime/` 存各自的运行环境和模型；`data/` 存日用数据。真实数据库、音频、密钥和设备备份留在本机。[配置管理](../development/configuration.md)
- 历史实验结果在 `experiments/`，合成输入在 `datasets/`，现行功能验证在 `tests/`。
- 固件目录保存本项目的补丁、资源描述和恢复资料，实际原生工程按机器指南单独维护。网页预览、仓库补丁和设备当前运行画面需要分别核对。[固件编译与工程位置](../guides/恢复固件编译-20261014.md)

旧的目录安排可查[历史仓库说明](../history/current-docs-before-20261014/docs/architecture/repository-structure.md)。当前阶段的安排见[路线图](../../ROADMAP.md)。
