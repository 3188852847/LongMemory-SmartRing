# SmartRing-Plus 圆屏固件能力审计（2026-09-08）

## 结论

本机现已取得厂家仓库中的 B V2 小智源码目录，并完成原样构建、分区核对、实机烧录和联网基线验收。设备启动日志确认 ESP-IDF v5.5.4、应用 v2.2.3、ESP32-S3、16 MB Flash、8 MB PSRAM，以及 AXP2101、ES8311、CST816S 和 ST77916 初始化成功。该副本来自 GitHub ZIP，没有 `.git` 元数据，当前只能用取得日期、依赖锁与产物哈希固定，不能声称已固定上游提交号。

浏览器模拟器由此前假设的 466×466 修正为 360×360。厂家仓库总说明将硬件记录为 1.85 英寸圆形 IPS 屏，板级源码使用 ST77916；除非取得 B V2 的相反证据，不把 AMOLED 当作已确认事实。

## 核对对象与版本边界

- 既有厂家仓库：`D:\ESP32-Workspace\SmartRing-Plus`，其中只有此前审计的旧源码。
- 2026-09-08 取得的厂家 ZIP 副本：`D:\SmartRing-Plus-main`；该目录没有 `.git` 元数据。
- 当前 B V2 源码：`examples/esp-idf/11_xiaozhi/xiaozhi-esp32-main_smartring_plus_B_V2`。
- 原下载路径首次解析 `espressif/esp_video 1.3.1` 时，组件目标路径达到 261 字符；本机 `LongPathsEnabled=0`，Python `shutil.copytree` 因传统 Windows 路径限制失败。为避免修改全局策略，已把排除 `build`、`managed_components`、`dependencies.lock` 等生成物的干净工作副本复制到 `D:\sr-bv2`，后续只在该短路径构建。
- 同一 ZIP 还包含通用目录 `examples/esp-idf/11_xiaozhi/xiaozhi-esp32-main-2.0`，不能与 B V2 专用目录混用。
- 已烧录 B V2 二进制：`G:\00-下载\XIOAZHI2.0-SmartRing_Plus_B_V2.bin`；项目硬件记录已保存其大小、哈希、分区与应用元数据。
- B V2 工程的组件清单要求 ESP-IDF `>=5.5.2`；此前 v5.4.4 环境不能作为该工程的构建环境。

源码目录名与厂家提供信息一致，但构建产物与此前厂家预编译整包并非逐字节一致。当前仅把本次源码构建和实机启动视为新的可复现开发基线，不反推两个二进制的功能差异。

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

1. **已满足**：以取得日期、依赖锁与构建产物哈希固定当前 ZIP 基线；仍缺上游提交级身份。
2. **已满足**：使用 ESP-IDF v5.5.4 独立生成全新构建目录，没有沿用 v5.4.4 缓存。
3. **已满足**：核对 16 MB 分区和写入布局，并仅烧录构建声明的五个分区，保留了 NVS 配网数据。
4. **已满足第一版**：用基线清单、前置哈希与统一补丁建立可审计的第三方源码覆盖层；未把厂家全量源码或角色版权素材复制进主仓库。
5. **待完成**：依次实机验收聆听、思考、回应、打断和故障恢复；任何单项失败都可恢复到已验证的厂家 B V2 整包备份。

## 首次原样构建结果

2026-09-08 在短路径 `D:\sr-bv2` 使用 ESP-IDF v5.5.4、Python 3.11.15、CMake 3.30.2、Ninja 1.12.1 和 Xtensa GCC 14.2.0 完成厂家源码的原样构建。构建配置确认：

- 项目版本 `2.2.3`；目标 `esp32s3`。
- 板型 `CONFIG_BOARD_TYPE_VIEWE_SMARTRING_PLUS=y`。
- Flash 大小 `16MB`，分区表 `partitions/v2/16m.csv`。
- 写入布局：bootloader `0x0`、partition table `0x8000`、OTA data `0xd000`、应用 `0x20000`、expression assets `0x800000`。
- 依赖锁文件 SHA-256：`CFA751E181E1CBFDCA7DD96C5C3A7147B1B660495EB7E5CAC2A2C604E58157CE`。
- 合并固件长度 `11128541` 字节，SHA-256：`49284A8220EF6F9D93B6E1621A6A1CF90C1072BDCEA0EB9DA2B6027AA4DCE057`。
- 发布包 `v2.2.3_viewe-smartring-plus.zip` 长度 `3832731` 字节，SHA-256：`7D4869E8C9DDF06A38B058CD374E35A3FC8439FC5D30FC8A52BD548F88998473`。

此前下载并实机运行的厂家文件 `XIOAZHI2.0-SmartRing_Plus_B_V2.bin` 长度为 `8740713` 字节，SHA-256 为 `89DD0336C694C6ADB978DE7C6BEE7B87AA62B34BC3A736369B77C0425051A102`，与本次合并固件不同。因此当前结论是“所获源码能够成功构建并作为实机开发基线运行”，不是“逐字节复现厂家预编译固件”。本次没有根据该差异猜测功能变化，也没有从 `0x0` 写入整份合并镜像覆盖 NVS。

## 首次实机基线结果

2026-09-08 经用户明确授权，将本次原样构建的五个分区写入 COM3。未写入 `0x9000` NVS，既有 Wi-Fi 配置得以保留；所有写入均通过设备端哈希校验。重启后确认：

- 应用 `xiaozhi` v2.2.3 和 ESP-IDF v5.5.4 正常启动，圆屏外观正常。
- AXP2101 电源管理、300 mA 充电配置、ES8311 音频、CST816S 触摸、ST77916 显示和 61% 背光恢复均完成初始化。
- 设备连接 SSID `A312`，从 `http://192.168.124.111:8003/xiaozhi/ota/` 获得 WebSocket 地址并成功上线；服务端识别设备固件已是最新 v2.2.3。
- 网络握手实际公开 3 个 MCP 工具：读取设备状态、设置扬声器音量、设置屏幕亮度。源码启动阶段还注册了系统信息、重启和升级等本地工具，但它们没有出现在本次远端工具清单中，不能写成控制台现有能力。
- 控制适配器报告连接数 1，状态读取、音量、亮度和主动播报可用；主题切换不可用，固件未声明 AEC。
- 启动日志出现 `Assets partition is disabled for board viewe-smartring-plus` 和表情显示未初始化提示；目前基础画面正常，但角色资源系统仍须在修改 UI 前单独定位。
- 应用分区构建余量仅约 `0x930` 字节，设备端继续加代码前必须先解决分区或体积预算，不能直接堆叠完整状态 UI。
- 本次所选模型接口返回 HTTP 404，且 VoxCPM2 环回端口 `18768` 未启动，因此没有把回答生成或真实声线纳入固件基线结论。
- 停止服务时，上游把内部生成的会话结束提示按用户消息交给 Memory 插槽；LongMemory 保存了 1 条 L0、没有生成 L1。这是服务输入来源标注缺口，不是用户事实，后续应在适配边界按消息来源排除，不能靠匹配某一句提示文本掩盖。

本次服务端验证还将可追溯的旧 LongMemory 小智适配器升级到当前项目版本；35 项定向测试通过。旧版本可由 Git 提交 `894b5fb` / `ff15db0` 与原 SHA-256 恢复，升级过程没有生成独立 `.bak` 文件。

### 体积与资源策略诊断

基线 map 的最大单项是 `lib78__xiaozhi-fonts.a`，占 `1,327,418` 字节，几乎全部为 Flash data；其后才是 LVGL、推理库、C++ 运行库和主程序。板型 `config.json` 同时写入 `CONFIG_USE_WECHAT_MESSAGE_STYLE=y`、`CONFIG_USE_EMOTE_MESSAGE_STYLE=y` 和 `CONFIG_FLASH_EXPRESSION_ASSETS=y`，但板级 `InitializeSt77916Display()` 明确创建 `SpiLcdDisplay`，注释也说明使用 LVGL chat UI。由于 `display.h` 在 Emote message style 下不定义 `HAVE_LVGL`，`Assets` 选择 `EmoteStrategy`，最终尝试把 expression assets 挂到不存在的 `EmoteDisplay`，与实机警告一致。

这表明当前首先要验证的是“显示类型与资源策略一致性”，而不是直接扩大应用分区。实验只在隔离副本中改为 LVGL 对应的默认资源路径，未改分区表。上游跟踪方式见 [ADR-0090](../adr/0090-audited-upstream-firmware-overlay.md)。

补丁 `0001-align-viewe-lvgl-assets.patch` 已通过原基线的干净应用检查，并应用到独立副本 `D:\sr-bv2-lvgl-assets`。首次预检发现上游发布脚本要求 build 名与 CMake 板型一致，补丁因此保留原名；显式禁用 Component Manager 又会令 CMake 无法注册本地字体和 ESP-SR 组件，最终由用户在 ESP-IDF v5.5.4 环境启用 Component Manager 完成全新构建。

实验应用镜像为 `3,957,712` 字节，SHA-256 为 `340CCB674F9EEBB663CF88EA9261EA81668DF5C9A9760A15FF4C46BCF12A9B6E`；相较原样基线减少 `168,704` 字节，应用分区余量由 `2,352` 增至 `171,056` 字节，约占分区 4%。`generated_assets.bin` 为 `352,105` 字节，SHA-256 为 `C31A144A0DF77BFD8F70545D3AF12E3B23F1501CC3B4865EBD91E0FCAC965478`。字体静态库仍约 `1.33 MB`，所以该实验只是恢复正确资源策略并提供有限代码余量，不代表体积问题彻底解决。

2026-09-08 经用户授权，将上述实验构建声明的五个分区写入 COM3，未写入 NVS，全部通过设备哈希校验。启动日志确认 8 MB Assets 分区完成校验和挂载，原来的 `Assets partition is disabled` 与 `Emote display is not initialized` 错误消失；电源、音频、触摸、ST77916、LVGL 和 Wi-Fi 均正常初始化。`microchip_ai` 与 `cloud_slash` 会先触发 PNG 集合的“未找到”警告，但源码随后会把它们映射到已编入的 Font Awesome 图标；这是日志噪声而非已证实的资源缺失。验证尾部的 OTA 连接失败来自电脑端 `192.168.124.111:8003` 已停止，并非固件启动失败。

## 未执行事项

尚未接入中立显示状态协议或更换角色资源，也未完成聆听、思考、回应、说话打断和分类故障的逐项视觉验收。除上述被错误归档的 1 条上游内部提示 L0 外，本轮没有生成新的长期事实或迁移数据库。
