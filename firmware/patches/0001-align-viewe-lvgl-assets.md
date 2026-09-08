# 0001：对齐 Viewe LVGL 显示与资源策略

状态：离线构建、实机烧录与启动日志验收已完成；逐项视觉状态验收未完成。

## 目的

B V2 板级实现实际创建 `SpiLcdDisplay`，但原配置的 Emote message style 会令资源加载器选择 `EmoteStrategy`。本补丁移除 Emote style，保留微信式 LVGL 对话布局，并让 Kconfig/构建显式生成 LVGL default assets。

## 修改范围

- 只修改 `main/boards/viewe-smartring-plus/config.json`。
- 不改板级引脚、电源、电池、音频、触摸、网络、MCP、分区表或角色素材。
- 保留构建名称 `viewe-smartring-plus`，因为上游发布脚本要求它与 CMake 板型一致；实验身份由独立目录、补丁清单和产物哈希区分。

## 应用前条件

目标文件 SHA-256 必须为：

```text
2bc31333ebe34bf5711e5d33384260cc8c545952a5e2821e7875196826f8c719
```

完整基线见 `firmware/smartring_plus/upstream-baseline.json`。哈希不一致时停止，不强行应用。

## 验证门槛

1. 全新构建成功且不访问网络下载新依赖。
2. `sdkconfig` 中 `CONFIG_USE_WECHAT_MESSAGE_STYLE=y`、未启用 `CONFIG_USE_EMOTE_MESSAGE_STYLE`、`CONFIG_FLASH_DEFAULT_ASSETS=y`。
3. 记录应用镜像、资源镜像及 OTA 分区余量，与基线比较。
4. 静态确认 `Assets` 走 `LvglStrategy`；构建成功不能替代启动日志。
5. 离线结果通过后另行说明烧录范围和恢复方法；补丁文件本身不执行烧录。

## 构建与实机结果

- 补丁可在基线文件上干净应用。
- 上游发布脚本要求构建名称保持 `viewe-smartring-plus`；曾尝试的实验名在配置阶段被拒绝，现已修正。
- 显式禁用 Component Manager 会令 CMake 无法注册本地 `xiaozhi-fonts` 与 ESP-SR 组件，资源生成脚本收到空路径并停止。因此后续构建需启用组件管理器；由于它可能访问网络，该步由用户在本机执行。
- 用户在 ESP-IDF v5.5.4 环境启用 Component Manager 后完成全新构建。
- 应用镜像为 `3,957,712` 字节，较原样基线减少 `168,704` 字节；应用分区余量由 `2,352` 字节增至 `171,056` 字节（约 4%）。字体静态库仍约 `1.33 MB`，因此本补丁只缓解、没有根治体积约束。
- `generated_assets.bin` 为 `352,105` 字节；完整产物哈希记录在 `firmware/smartring_plus/experiments/0001-lvgl-assets.json`。
- 经用户明确授权，仅向 COM3 写入构建声明的 bootloader、partition table、OTA data、application 与 generated assets 五个分区；未写入 `0x9000` NVS，所有写入均通过哈希校验。
- 重启日志确认 `Assets` 校验并挂载 8 MB 分区，原来的 `Assets partition is disabled` 与 `Emote display is not initialized` 错误均消失。
- 设备的电源、音频、触摸、ST77916、LVGL 和 Wi-Fi 正常初始化；仍需用户完成视觉观察以及聆听、思考、回应和打断的逐项验收。
- `microchip_ai` 和 `cloud_slash` 会先触发 PNG 表情集合的“未找到”警告，再按 `LcdDisplay::SetEmotion()` 的既定逻辑回退到 Font Awesome 图标；两个名称及 `font_awesome_20_4` 均已编入固件。该警告属于可优化的日志噪声，不能据此判定图标缺失；真实显示仍以视觉验收为准。
- OTA 重试是因为验证时电脑端 `192.168.124.111:8003` 服务已停止，不是本补丁导致的崩溃。
