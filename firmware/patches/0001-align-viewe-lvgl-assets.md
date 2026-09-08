# 0001：对齐 Viewe LVGL 显示与资源策略

状态：仅离线构建实验，未授权烧录。

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
5. 离线结果通过后另行说明烧录范围和恢复方法，本补丁本身不执行烧录。

## 当前预检结果

- 补丁可在基线文件上干净应用。
- 上游发布脚本要求构建名称保持 `viewe-smartring-plus`；曾尝试的实验名在配置阶段被拒绝，现已修正。
- 显式禁用 Component Manager 会令 CMake 无法注册本地 `xiaozhi-fonts` 与 ESP-SR 组件，资源生成脚本收到空路径并停止。因此后续构建需启用组件管理器；由于它可能访问网络，该步由用户在本机执行。
- 尚未得到实验应用或 assets 镜像，不能声称体积改善或资源加载问题已解决。
