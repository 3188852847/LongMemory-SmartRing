# 智慧圆屏

智慧圆屏是带长期记忆的个人聊天伙伴。你可以在网页上打字，也可以对着桌上的 ESP32-S3 圆屏说话。电脑负责处理对话和记忆，圆屏负责收音、显示和播放。

## 开始使用

双击根目录的 [启动智慧圆屏.cmd](启动智慧圆屏.cmd)，选择“文字聊天”或“圆屏陪伴”，点击“开启陪伴”。网页里可以查看一条记忆来自哪句话，也可以纠正它。用完后在启动面板点击“停止服务”。只关网页会保留后台服务。

- 聊天、查询记忆或调整声音，见 [使用说明](docs/guides/使用说明.md)。
- 打不开面板、圆屏没连上或没有声音，见 [启动排障](docs/guides/统一启动.md)。
- 查看现在优先维护什么，见 [路线图](ROADMAP.md)。

## 代码在哪

| 找什么 | 位置 |
| --- | --- |
| 对话和长期记忆 | `src/longmemory/` |
| 网页界面和启动面板 | `web/react-chat/`、`scripts/development/launcher/` |
| 圆屏语音接入和固件 | `scripts/development/xiaozhi/`、`firmware/smartring_plus/` |
| 合成测试与研究实验 | `tests/`、`datasets/`、`experiments/` |

个人数据与私有配置留在本机。维护时按需查[本机目录与依赖](docs/guides/本机目录与依赖.md)、[架构总览](docs/architecture/overview.md)或[工程文档索引](docs/README.md)。
