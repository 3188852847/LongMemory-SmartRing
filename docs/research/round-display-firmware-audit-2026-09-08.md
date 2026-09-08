# SmartRing-Plus 圆屏固件能力审计（2026-09-08）

## 结论

本机现已取得厂家仓库中的 B V2 小智源码目录。静态核对确认该目录是 ESP-IDF 工程，并包含 SmartRing-Plus 专用板级实现、360×360 显示、AXP2101 电源管理、电量读取、背光、触摸和会话状态入口。该副本来自 GitHub ZIP，没有 `.git` 元数据，当前只能固定到取得日期和文件内容，不能声称已固定上游提交号；本阶段尚未修改、编译或烧录该源码。

浏览器模拟器由此前假设的 466×466 修正为 360×360。厂家仓库总说明将硬件记录为 1.85 英寸圆形 IPS 屏，板级源码使用 ST77916；除非取得 B V2 的相反证据，不把 AMOLED 当作已确认事实。

## 核对对象与版本边界

- 既有厂家仓库：`D:\ESP32-Workspace\SmartRing-Plus`，其中只有此前审计的旧源码。
- 2026-09-08 取得的厂家 ZIP 副本：`D:\SmartRing-Plus-main`；该目录没有 `.git` 元数据。
- 当前 B V2 源码：`examples/esp-idf/11_xiaozhi/xiaozhi-esp32-main_smartring_plus_B_V2`。
- 原下载路径首次解析 `espressif/esp_video 1.3.1` 时，组件目标路径达到 261 字符；本机 `LongPathsEnabled=0`，Python `shutil.copytree` 因传统 Windows 路径限制失败。为避免修改全局策略，已把排除 `build`、`managed_components`、`dependencies.lock` 等生成物的干净工作副本复制到 `D:\sr-bv2`，后续只在该短路径构建。
- 同一 ZIP 还包含通用目录 `examples/esp-idf/11_xiaozhi/xiaozhi-esp32-main-2.0`，不能与 B V2 专用目录混用。
- 已烧录 B V2 二进制：`G:\00-下载\XIOAZHI2.0-SmartRing_Plus_B_V2.bin`；项目硬件记录已保存其大小、哈希、分区与应用元数据。
- B V2 工程的组件清单要求 ESP-IDF `>=5.5.2`；此前 v5.4.4 环境不能作为该工程的构建环境。

源码目录名与厂家提供信息一致，但尚未证明它能够逐字节复现已烧录的 B V2 二进制。静态源码能力也不能代替编译、烧录和实机行为验证。

## 已核实的 B V2 源码能力

| 能力 | B V2 源码证据 | 对中立协议的含义 |
|---|---|---|
| 分辨率与显示栈 | 板级 `config.h` 为 360×360；使用 ST77916、LVGL/EmoteDisplay | 模拟器应以 360×360 和约 255×255 中央安全区为基准 |
| 基础会话状态 | 状态机有 `starting`、`wifi_configuring`、`idle`、`connecting`、`listening`、`speaking`、`upgrading`、`activating`、`audio_testing`、`fatal_error` | 可直接映射启动、配网、待机、聆听、回应、更新与致命错误 |
| 字幕与情绪 | 服务端 `stt`、`tts` 和 `llm.emotion` 消息分别进入用户字幕、助手字幕和 `SetEmotion` | 角色表现可以继续与业务状态分离 |
| 打断 | 说话或聆听时检测唤醒词会发送 `abort`，原因可为 `wake_word_detected` | 有打断入口，但旧状态机没有独立 `interrupted` 状态或播放完成回执 |
| 电量与电源 | `config.h` 和板级实现使用 AXP2101，提供电量、充放电状态、300 mA 充电配置与低电关机入口 | UI 可以预留边缘电量层；参数写入和关机策略属于高风险硬件行为，修改前必须另行验证 |
| 背光与触摸 | 板级实现创建 PWM 背光并恢复亮度，CST816S 触摸产生按下、释放与移动事件 | 具备后续扩展设备控制和圆屏交互的代码入口，不等于当前服务端已暴露相应控制 API |
| 构建配置 | `config.json` 指定 `esp32s3`、16 MB Flash 和 `partitions/v2/16m.csv` | 后续必须使用 B V2 板型配置，不能复用 hello_world 的 2 MB 配置 |

## 状态映射草案

| 旧小智状态/事件 | 中立显示状态 | 可信度与缺口 |
|---|---|---|
| `starting` | `booting` | 可直接映射 |
| `wifi_configuring` | `system_state=provisioning` | 可直接映射 |
| `idle` | `idle` | 可直接映射 |
| `listening` | `listening` | 可直接映射；不等于仅仅在线 |
| `speaking` | `speaking` | 设备状态可用；服务端 `queued` 仍不能冒充设备播放完成 |
| `upgrading` | `system_state=updating` | 可直接映射 |
| `fatal_error` | `error` | 旧状态过粗，不能区分网络、模型或电脑服务故障 |
| `connecting`、`activating`、`audio_testing` | 暂不强行合并 | 需结合 B V2 的页面和事件语义决定 |
| 首个有效 STT 结束至首个 TTS 开始 | `thinking` | 旧设备状态机没有该状态，需要协议事件或设备端派生规则 |
| `abort` + 恢复采集 | `interrupted` | 旧协议能发中止，缺少独立显示状态和完成确认 |
| VAD/ASR 无有效文本 | `no_speech` | 旧源码未发现可靠的独立状态，需要 B V2 或服务端显式事件 |
| 分类后的模型/电脑服务错误 | `model_unavailable` / `server_unavailable` | 不能从旧 `fatal_error` 猜测，需服务端分类消息 |

## 进入设备端实现前的门槛

1. 以 Git 提交或归档哈希固定当前 B V2 上游基线；ZIP 目录不能提供提交级溯源。
2. 准备 ESP-IDF >=5.5.2 的隔离环境，先做不连接设备的原样构建，不沿用 v5.4.4 构建缓存。
3. 核对构建产物的分区、Flash 大小和板型，再确认恢复镜像与烧录步骤仍有效。
4. 创建独立设备端开发分支；第一版只实现几何占位状态，不加入角色版权素材。
5. 依次实机验收聆听、思考、回应、打断和故障恢复；任何单项失败都可恢复到已验证的厂家 B V2 二进制。

## 首次原样构建结果

2026-09-08 在短路径 `D:\sr-bv2` 使用 ESP-IDF v5.5.4、Python 3.11.15、CMake 3.30.2、Ninja 1.12.1 和 Xtensa GCC 14.2.0 完成厂家源码的原样构建。构建配置确认：

- 项目版本 `2.2.3`；目标 `esp32s3`。
- 板型 `CONFIG_BOARD_TYPE_VIEWE_SMARTRING_PLUS=y`。
- Flash 大小 `16MB`，分区表 `partitions/v2/16m.csv`。
- 写入布局：bootloader `0x0`、partition table `0x8000`、OTA data `0xd000`、应用 `0x20000`、expression assets `0x800000`。
- 依赖锁文件 SHA-256：`CFA751E181E1CBFDCA7DD96C5C3A7147B1B660495EB7E5CAC2A2C604E58157CE`。
- 合并固件长度 `11128541` 字节，SHA-256：`49284A8220EF6F9D93B6E1621A6A1CF90C1072BDCEA0EB9DA2B6027AA4DCE057`。
- 发布包 `v2.2.3_viewe-smartring-plus.zip` 长度 `3832731` 字节，SHA-256：`7D4869E8C9DDF06A38B058CD374E35A3FC8439FC5D30FC8A52BD548F88998473`。

此前下载并实机运行的厂家文件 `XIOAZHI2.0-SmartRing_Plus_B_V2.bin` 长度为 `8740713` 字节，SHA-256 为 `89DD0336C694C6ADB978DE7C6BEE7B87AA62B34BC3A736369B77C0425051A102`，与本次合并固件不同。因此当前结论仅为“所获源码能够成功构建”，不是“逐字节复现厂家预编译固件”。在完成首次实机基线验收前，不基于该差异猜测功能变化，也不使用从 `0x0` 写入整份合并镜像的方式覆盖 NVS。

## 未执行事项

本次由用户下载厂家仓库 ZIP、安装构建依赖并运行原样构建；助手核对源码、构建配置和产物并更新项目文档。尚未烧录或连接圆屏，未修改数据库。
