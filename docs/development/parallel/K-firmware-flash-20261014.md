# K：0013 应用更新与重启前校验

日期：2026-10-14，Asia/Shanghai。分支 `codex/firmware-0013-flash-20261014`，基线 `0554c77ff0e502f0b65876913d53f9106437f95a`。会话 ID：`01a13a9a-6ace-7a71-9238-5b9abc4f8d10`。本记录与[操作及验收指南](../../guides/圆屏动态表情烧录-20261014.md)属于本次公开交付；个人备份、原始串口日志和最小操作助手只留私有目录。

## 结果与授权

已完成完整原 Flash 备份、独立设备摘要校验、实际活动槽判断、一次仅应用写入、独立应用读回、受保护区域设备摘要校验及重启。2026-10-14 21:54:53 前后的 12 秒被动启动观察捕获应用版本 2.2.3 和 `unknown → starting → activating → idle`，未捕获崩溃标记，随后关闭串口。实际动画、声音、插话打断和记忆仍待所有者验收，不能由读回或 idle 状态代替。

本次直接人类授权为：“COM3 就是原来的圆屏，现在授权你先备份，再只烧录应用分区，保留现有配置和壁纸，烧录后我们再验收动态表情和语音。”其覆盖基线规则中本轮不烧录约定；主会话已将这项新增授权登记到 main 的 `06dcb5e`。K 是唯一 COM3 操作会话，未另开串口任务、未向其他会话发送消息。

使用已安装的 ESP-IDF 5.5.4 专属 Python 与 esptool 4.12.0；SDK 提交核对为 `735507283d5b2f9fb363a1901172dbd9e847945d`。未安装或下载资源、未升级环境、未重建或覆盖已有产物、未编辑外部 `src` / `motion0013`。未修改主项目配置、个人数据库或日用语音服务。

## 私有备份与实机范围

持久目录：主项目 `local/archive/firmware/device-backups/0013-20261014-213032-648301/`，实际根为 `D:\03-项目\01-正式项目\智慧圆屏`。该范围已核对 Git 忽略；其中包含 Wi-Fi 等私人内容，禁止提交、上传或展示正文。

| 私有文件 | 用途 |
|---|---|
| `original-full-flash.bin` | 完整 16,777,216 字节原 Flash，含恢复所需配置和资源 |
| `backup-verification.json` | 本地 SHA-256 / MD5、独立整片设备 MD5 匹配、身份一致性 |
| `original-active-app.bin` | 从实际活动槽提取并验证 checksum / 镜像 validation hash 的原应用 |
| `original-active-slot.bin` | 原活动槽全部 4,128,768 字节，用于仅应用分区精确回退 |
| `prewrite-manifest.json`、`rollback-plan.json` | 实际分区、OTA 选择、擦写范围及准确单槽回退命令 |
| `write-attempt.json`、`write-result.json` | 同一连接内身份/安全/整片摘要门槛和唯一写入尝试 |
| `protected-regions-verification.json`、`postwrite-verification.json` | 设备区域摘要证明、新应用独立读回和擦除填充核对 |
| `reboot-observation.json` | 限时启动观察与串口关闭记录 |

COM3 再次枚举为 Espressif 原生 USB（VID 303A / PID 1001 / MI 00），实机为 ESP32-S3 QFN56 v0.2、16 MB quad Flash。多次探针、备份连接、写入前同一打开句柄和重启前核对设备身份一致；稳定身份与安全信息原文仅存私有日志。安全启动、Flash 加密和安全下载限制均未启用，没有绕过安全保护。

实际分区表在 `0x8000`，MD5 有效，且与 `build-motion0013`、原恢复 `build-idf554` 的分区表完全一致。

| 实际分区 | 起始地址 | 字节数 | 本次行为 |
|---|---:|---:|---|
| nvs | `0x9000` | 16,384 | 保持 |
| otadata | `0xd000` | 8,192 | 保持 |
| phy_init | `0xf000` | 4,096 | 保持 |
| ota_0 | `0x20000` | 4,128,768 | 当前活动槽；仅此槽内更新 |
| ota_1 | `0x410000` | 4,128,768 | 保持 |
| assets | `0x800000` | 2,097,152 | 保持 |
| wallpaper_a | `0xa00000` | 3,145,728 | 保持 |
| wallpaper_b | `0xd00000` | 3,145,728 | 保持 |

OTA（应用更新选择数据）第 0 份记录序号为 1、状态 VALID（2）、CRC 有效；第 1 份未初始化。依据固定 SDK 的有效性与最大有效序号规则，`(1 - 1) % 2 = 0`，确定当前活动槽为 `ota_0`。没有用构建文件的默认地址冒充实机活动地址，没有改 OTA 选择。原应用与新应用均是 ESP32-S3 / xiaozhi 2.2.3 / ESP-IDF 5.5.4，镜像内板型标识均为 `viewe-smartring-plus`，镜像 checksum 和 validation hash 有效。

## 实际更新与独立核验

产物来源：[0013 实验记录](../../../firmware/smartring_plus/experiments/0013-continuous-round-face.json)与[0013 审计补丁](../../../firmware/smartring_plus/patches/0013-continuous-round-face.patch)。实际使用 `D:\Dev\esp-projects\smart-ring\build-motion0013\xiaozhi.bin`；没有新增 assets、依赖或改变皮肤 schema / 协议 / 状态机。历史实验文件中的 `flashed=false` 保留当时离线阶段事实，本记录登记后续实机更新。

| 镜像 | 字节数 | SHA-256 |
|---|---:|---|
| 原活动应用 | 3,984,224 | `1fc065d6c7badff0b8ec1ec6723cf3e9635d5c7b3db4e66a16143943dbd609e8` |
| 0013 应用 | 3,986,384 | `2749e5266efc136b4502a9f4e9bdbec4179077bcf8e4f1bb77b60d49d0cdb24f` |

21:51:17 写入前，在同一 COM3 打开句柄内再次核对 MAC、ESP32-S3、安全信息、Flash ID，以及整片设备 MD5 与已验证备份一致，再将已连接设备交给本机 esptool 官方 `main(argv, esp=...)`。命令只含一个地址/文件对：`0x20000` 与上述 0013 应用；`flash_mode/freq/size` 全为 `keep`，压缩传输，结束保持下载模式。没有使用 `idf.py flash`、`@flash_args`、`--force`、全片擦除、eFuse 操作或任何其他分区写入。

写入字节范围为 `[0x20000, 0x3ed3d0)`，实际擦除对齐范围为 `[0x20000, 0x3ee000)`，完全位于 `[0x20000, 0x410000)` 应用槽内。只调用一次写入；工具报告应用传输 26.9 秒，21:51:52 返回。没有自动回刷或第二次应用写入。

重启前的独立核验如下；设备端 MD5 计算与本地摘要分开执行，不将工具内置成功提示算作全部验证：

1. 完整备份 16 MB 读取自带设备 MD5 校验；另用 `verify_flash` 对整片设备再计算 MD5，与完整备份匹配。第二次核验采用芯片摘要，**没有执行第二次整片串口重读**。
2. 写后设备区域 MD5 与原备份切片分别匹配：`[0, 0x20000)`、`[0x410000, 0x1000000)`，覆盖全部非目标应用分区及间隙；应用槽内未擦写尾部 `[0x3ee000, 0x410000)` 也匹配。校验参数全为 `keep`，没有修改主机校验镜像头。
3. 独立读取 `[0x20000, 0x3ee000)` 共 3,989,504 字节，耗时 91.0 秒。前 3,986,384 字节与 0013 文件逐字节一致，SHA-256 为上表摘要；剩余 3,120 字节全为擦除值 `0xff`。这不是仅依赖烧录返回值。
4. 上述范围覆盖整个 Flash：擦写范围由独立字节读回核对，其余全部由设备摘要核对。21:54:31 完成重启前校验，再执行固定 SDK 重启并被动接收 12 秒日志，随后关闭串口。

这里的“保持”由**新应用运行前**的设备内容校验支持；设备启动后正常运行产生的自身持久化行为没有另做静态比对。未解析私人 NVS 正文，未改变当前壁纸或显示模式。启动窗口未捕获加载地址提示及壁纸加载提示，不能据此断言没有加载壁纸；捕获的版本和 idle 状态也不能单独区分同版本的不同镜像。

## 过程问题与回退边界

第一次完整读取使用 115200、RAM stub，未开启中间进度，因设置的 600 秒等待上限过短而超时，未形成备份，也未执行 Flash 写入。主会话允许在确认仅自有只读进程后调整读取；停止身份护栏发现进程已退出，没有执行 Stop-Process。保留该失败记录后，重新连接已核对的同一设备，用 460800 和可见进度完成一次有效完整读取，实测 384.0 秒 / 349.5 kbit/s。`--no-stub` 只用于安全/几何探针；不把它误写成完整读取的慢路径原因。失败记录与完整读取进度日志只留私有目录。

仅应用回退方案已在写入前保存：`0x20000` 加私有 `original-active-slot.bin`（4,128,768 字节，SHA-256 `a90253956055816186f3f864fb4f7f2d09f642d5f00440fca8291727e706cff9`），恢复精确应用槽，包括原尾部。执行回退前仍须重新核对设备、安全状态及该文件摘要；保持其他分区和 OTA 数据，再做独立应用读回及受保护区域核验。**本次没有执行回退，也不自动将完整 16 MB 备份回刷。**

待所有者按[验收指南](../../guides/圆屏动态表情烧录-20261014.md)观察静止微动、状态连续性、插话、正常声音与记忆。若当前壁纸遮住几何脸，由所有者决定是否切换，不自动改配置制造通过。K 仅本地提交本分支；主会话负责审查、实机反馈登记、main 合入、推送和后续归档。合入提交、实机验收和远程 CI 尚未登记。

所有者随后澄清视觉方向：希望的是 Otto 动态表情包效果，尚未确认当前 0013 表情或语音通过。主会话另行核对资源来源、格式及许可；这属于后续讨论，不表示本次已部署 Otto 素材，也不新增下载、改显示模式或再次烧录授权。K 在设备操作完成后不再打开 COM3。

## 可追溯来源

- 本机固定 SDK：`components/bootloader_support/src/bootloader_common_loader.c` 的 OTA CRC / 有效性 / 序号选择，`bootloader_utility.c` 的槽映射，`esp_flash_partitions.h` 的状态定义；`components/app_update/otatool.py` 的 CRC 计算。
- 本机 esptool 4.12.0：`cmds.py` 的 `write_flash` / `verify_flash` / `read_flash`，`loader.py` 的区域摘要、RAM stub 与连接，`__init__.py` 的已连接设备入口及退出行为；先核对 CLI help 和实际实现再执行。
- [Espressif v4 基本命令](https://docs.espressif.com/projects/esptool/en/release-v4/esp32/esptool/basic-commands.html)、[v4 波特率选项](https://docs.espressif.com/projects/esptool/en/release-v4/esp32/esptool/basic-options.html)用于核对完整读取和 460800 参数；本机版本行为以已装 SDK 为准。

## 公开交付验证

使用已安装的项目 Python 3.12.13，只读运行 `check_docs.py --only <本报告> --only <验收指南> --strict`：两份文档与清单通过，零 warning / error，一条 note。该 note 是检查器将路径组件 `experiments` 视为私有边界而跳过 0013 JSON 链接；该文件实际为 Git 已跟踪公开实验记录，已人工读取核对。清单的精确 0013 glob 实际只匹配该 JSON 和审计补丁，保留二者源码关联。

首次误用 SDK Python 3.11 运行文档检查，因检查器需要 Python 3.12 的 `Path.is_junction` 而退出；切回文档维护规定的项目 Python 后通过。没有为此改检查器或环境。`git diff --check` 通过；公开交付仅报告、指南、清单三文件，不含固件、备份、私有助手或原始日志。这里的通过只证明公开记录结构，不替代设备证据或所有者验收。
