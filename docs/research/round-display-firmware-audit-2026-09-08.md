# SmartRing-Plus 圆屏固件能力审计（2026-09-08）

## 结论

本机厂家仓库中的旧小智源码足以证明 SmartRing-Plus 板级实现已有 360×360 显示、基础会话状态、电量读取和唤醒词打断入口，但不足以作为当前 B V2 固件的修改基线。本机不存在厂家所述 `xiaozhi-esp32-main_smartring_plus_B_v2` 目录，因此本阶段不修改或编译旧固件。

浏览器模拟器由此前假设的 466×466 修正为 360×360。厂家仓库总说明将硬件记录为 1.85 英寸圆形 IPS 屏，板级源码使用 ST77916；除非取得 B V2 的相反证据，不把 AMOLED 当作已确认事实。

## 核对对象与版本边界

- 本机厂家仓库：`D:\ESP32-Workspace\SmartRing-Plus`。
- 本机旧源码：`examples/esp-idf/11_xiaozhi/xiaozhi-esp32-main-2.0`。
- 本机仓库记录的旧 HEAD：`842111f973b468c202ed9855aac23fd9b791e762`。
- 已烧录 B V2 二进制：`G:\00-下载\XIOAZHI2.0-SmartRing_Plus_B_V2.bin`；项目硬件记录已保存其大小、哈希、分区与应用元数据。
- 厂家曾说明新源码目录为 `examples/esp-idf/11_xiaozhi/xiaozhi-esp32-main_smartring_plus_B_v2`，但该目录在本机不存在。

旧源码与 B V2 二进制不是同一个可复现构建基线。下面的源码发现只能作为能力线索，不能证明 B V2 的具体行为或文件位置。

## 已核实的旧源码能力

| 能力 | 旧源码证据 | 对中立协议的含义 |
|---|---|---|
| 分辨率与显示栈 | 板级 `config.h` 为 360×360；使用 ST77916、LVGL/EmoteDisplay | 模拟器应以 360×360 和约 255×255 中央安全区为基准 |
| 基础会话状态 | 状态机有 `starting`、`wifi_configuring`、`idle`、`connecting`、`listening`、`speaking`、`upgrading`、`activating`、`audio_testing`、`fatal_error` | 可直接映射启动、配网、待机、聆听、回应、更新与致命错误 |
| 字幕与情绪 | 服务端 `stt`、`tts` 和 `llm.emotion` 消息分别进入用户字幕、助手字幕和 `SetEmotion` | 角色表现可以继续与业务状态分离 |
| 打断 | 说话或聆听时检测唤醒词会发送 `abort`，原因可为 `wake_word_detected` | 有打断入口，但旧状态机没有独立 `interrupted` 状态或播放完成回执 |
| 电量 | 板级实现提供电量、充电与放电状态读取 | UI 可以预留边缘电量层；B V2 已改用 AXP2101 的事实仍以已记录的新版二进制/源码线索为边界 |

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

1. 取得厂家当前 B V2 源码目录，并固定提交号；不得用旧目录覆盖或猜测替代。
2. 核对 B V2 的分辨率、板级目录、LVGL/资源格式、电源管理和状态机差异。
3. 确认自定义固件的恢复镜像与烧录步骤仍有效，再创建独立开发分支。
4. 第一版只实现几何占位状态，不加入角色版权素材；先验收聆听、思考、回应、打断和故障恢复。

## 未执行事项

本次未联网拉取厂家仓库，未写入厂商目录，未编译或烧录固件，未连接圆屏，未修改数据库。网络获取依照项目约定由用户执行。
