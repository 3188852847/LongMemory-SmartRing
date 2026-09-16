# 0012：圆屏持久控制会话与连接失败恢复

状态：能力协商、补丁应用/反向检查、ESP-IDF v5.5.4 离线构建、仅应用分区烧录和独立读回
均已通过；首次持续连接观察到再次断连，静默 120 秒保活尚未通过验收。按用户决定转入
正常使用观察，再次唤醒和真实断网恢复留待后续体验反馈。

## 目的

0011 圆屏在服务端 120 秒静默结束后会失去 WebSocket，个别失败重连会长期显示“连接中”。
本补丁让支持新协议的圆屏停止采音后保留控制通道，并确保显式连接失败可以回到待机。

## 修改范围

- `websocket_protocol.cc`：声明 `persistent_session` 能力；内部消费无正文 heartbeat；拒绝无效
  JSON 时不再继续取字段。
- `application.cc`：处理 `session.idle`，只在聆听态停止采音并回到待机；连接失败关闭残留通道；
  连接中再次切换可取消。
- 配套服务端按能力门控发送 idle 和 heartbeat。旧固件沿用原超时逻辑。
- 不改变 AEC/WebSocket v2、视觉模式、NVS、分区表、assets、壁纸槽或记忆数据。

## 构建证据

- 补丁 SHA-256：`FC77B8B29C961DD6E5C0F8E7022FFA48626B149EF87EE24E70C7A99588DF22CF`。
- 修改前 `application.cc`：`BA4FA50B33632FEE82DE167AABE0929E2B95D282D3F3EC082D122F2DF09E6142`；
  修改后：`7DD4F8E6A174193B5186CBD0D26FE4047960B1066E581C159A08138356B6975D`。
- 修改前 `websocket_protocol.cc`：`718E29E7F79841A7517BA290E56AFA8BD57F94DBFA837E821D5F97BCB1AD8DF4`；
  修改后：`9AF223BD22ED36F1ADFB854FD9AF367BA06D79C37B55D4FCC1DADBC06438BC3A`。
- 新应用镜像：3,984,224 字节，SHA-256
  `1FC065D6C7BADFF0B8EC1EC6723CF3E9635D5C7B3DB4E66A16143943DBD609E8`。
- 应用分区 4,128,768 字节，剩余 144,544 字节（约 4%）；ESP32-S3 checksum 与 validation
  hash 均有效。
- 分区表和基础 assets 哈希与 0009～0011 相同。

构建前 0011 应用、两个源码和 sdkconfig 已保存到
`D:\sr-bv2-lvgl-assets\backups\0012-pre-persistent-session`。首次试烧只应把新
`xiaozhi.bin` 写入应用偏移 `0x20000`；回退时把 `xiaozhi-0011.bin` 写回同一偏移。

## 2026-09-16 烧录记录

- 目标：COM3，ESP32-S3 revision v0.2，MAC 尾号 `6d:38`。
- 只向 `0x20000` 写入 3,984,224 字节的 0012 应用；写入哈希通过。
- 独立执行 `verify_flash`，结果为 `digest matched`。
- 擦除范围为 `0x00020000-0x003ecfff`；未写 NVS、分区表、assets 或壁纸 A/B 槽。
- 串口日志确认新镜像启动、Wi-Fi 和 OTA 正常，设备随后处于待机。首次唤醒前没有 WebSocket
  属于现有固件行为。
- 首次唤醒后，服务端 `hello` 已确认设备声明 `persistent_session`。连接在 21:46:09 仍存在，
  服务端于 21:46:13 记录到断连；本次断连原因尚未定位，因此不能把静默保持标为通过。
- 按用户决定不再继续专项测试，后续通过正常使用反馈决定是否恢复排查。

## 真机验收

1. 启动服务并确认设备 hello 声明 `persistent_session`。
2. 完成一轮对话后保持静默超过 120 秒；设备应回到待机，服务端连接数仍为 1，且不播放结束语。
3. 再次唤醒并正常问答，确认没有重新连接等待。
4. 临时断开 Wi-Fi 或停止服务后恢复，再次唤醒应能重新连接；连接失败时不得永久停在“连接中”。
5. 验证自然插话、动态壁纸/皮肤模式和音量设置没有回归。
