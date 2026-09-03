# AXP2101 电源状态只读诊断

用于 SmartRing-Plus-B 圆屏终端的独立 ESP-IDF 程序，排查“外部有供电，但小智报告 0% / 未充电”。**不是充电修复固件，也不是小智插件。**

## 边界

- I²C：SDA GPIO8、SCL GPIO9、100 kHz、地址 0x34；0x03 返回 0x4A 后才解码（识别依据为本机厂商 BSP）。
- 每 5 秒通过原生 USB Serial/JTAG 输出原始寄存器、读错误、VBUS 有效、电池检测/存在、充电使能、电流方向、充电阶段、电压和估算百分比。
- I²C 的发送阶段只有一个寄存器地址字节，随后读取；**不发送配置值**。不使用厂商 `bsp_battery_init()`，不改变充电参数，不操作 GPIO47，不访问 IRQ 清除寄存器。
- 不初始化显示、声音、WiFi、NVS 或小智。未来若烧录，屏幕可能不显示；这是预期，不可据此判断故障。
- PMIC 是电源管理芯片。`vbus_good=yes` 只说明芯片检测到有效外部输入，不能单独证明电池充电。
- `pmic_current_direction` 与 `pmic_charge_stage` 原样解释两个不同状态字段，不人为合并；如不一致，需检查多次采样和供电条件。
- 无效/缺失值为 `UNKNOWN`。电池检测未启用时，不把“未检测”当成“没电池”；百分比是芯片估算，校准未核实。电压读取失败/ADC 未启用/非默认调试通道/原始零值时不报 0 mV。
- 独立诊断程序的负载与小智不同；重新启动以及换到电脑 USB 后的读数，**不是之前充电器供电下的小智运行快照**。此限制也意味着不能凭诊断时充电正常就断言小智运行时一直正常。

## 文件用途

```text
firmware/diagnostics/axp2101_readonly/  # 独立电源诊断工程
├── main/                            # 寄存器读取及纯解码逻辑
│   ├── main.cpp                     # USB 日志与只读 I²C 采样
│   ├── decode.hpp                   # 处理位字段、未知值及测量有效性
│   └── CMakeLists.txt               # 组件与编译期测试注册
├── CMakeLists.txt                   # ESP32-S3 工程入口
├── sdkconfig.defaults               # 16MB Flash、USB Serial/JTAG 控制台
├── build.ps1                        # 仅编译；临时英文目录保留生成物
└── README.md                        # 安全边界、解读及验证说明
tests/firmware/                      # 嵌入式离线测试，不混入 Python 业务模块
└── axp2101_decode_test.cpp           # 编译期 static_assert 合成用例
```

## 本机离线编译

在 LongMemory 项目根目录的 PowerShell 执行（不需要接设备）：

```powershell
& .\firmware\diagnostics\axp2101_readonly\build.ps1
```

脚本使用本机已安装的 ESP-IDF 5.5.4、配套 Python/GCC/CMake/Ninja，无新第三方依赖，不调用会修改 EIM 当前版本的激活脚本。工具版本和路径写在脚本中；其他电脑应先核对安装再调整。构建目录放在新建 `%TEMP%\axp-<随机编号>\app` 下；采用短路径避免 Windows 依赖文件路径长度限制，不会删除旧目录。末尾显示应用 `.bin` 的哈希及产物路径。SDK 可能打印烧录示例命令，**打印不代表执行，不要此时跟着烧录**。

编译同时检查合成寄存器解码，包括0/100%边界、缺失读数、保留状态、检测/ADC/电量计禁用与调试通道。它只能验证软件处理逻辑，不能证明芯片型号、接线、真实充电或读数校准。

## 进入实机前

先完整备份**当前已经配网的小智固件**并计算哈希，保留旧原厂备份不覆盖。备份可能含 WiFi 凭据等隐私数据，不提交 Git。确认备份与恢复路径后，另行决定是否烧录。

“只读”指运行时不写 PMIC 配置，不表示烧录过程不会改 Flash。首次准备步骤仅编译；后续经用户确认已在 COM3 烧录并采样，详见 [硬件实测记录](../../../docs/hardware/README.md)。

## 本次验证记录（2026-09-03）

- ESP-IDF 5.5.4 / Xtensa GCC 14.2.0 编译成功，30 条 C++ 编译期断言通过；生成配置确认 USB Serial/JTAG 控制台和 16MB Flash。
- LongMemory 原有 Python 测试：92 passed。它们不是电源硬件测试。
- 应用产物：`C:\Users\12280\AppData\Local\Temp\axp-3a732d55\app\build\axp2101_readonly.bin`，186224 字节。
- 应用 SHA256：`2AACA686D0F50AD527EB679F880AAF4CB11A57CBAF3B4EE12301DB15D26B90B1`。
- 同一 build 目录包含 bootloader、分区表和烧录参数；上述应用文件**不是可在 0x0 烧录的完整合并镜像**。当前不提供烧录步骤。
- 临时目录可能被系统清理，可用脚本重建。编译时间/路径会影响生成物哈希，不保证跨次构建二进制逐字节相同。

## 依据与当前假设

- 厂商本地 `01_i2c_scan/managed_components/viewesmart__smartring_plus/bsp_axp2101.c` 和 `include/bsp/board_config.h`：地址/引脚/芯片识别。
- 厂商仓库 `datasheet/C3036461_专业电源管理(PMIC)_AXP2101_规格书_WJ1748715.PDF`：第28页 ADC 单位/读取顺序，第31–32页状态，第34页模块使能，第39–40页 ADC/调试通道，第49页电池检测及 0xA4 电量寄存器。
- 本机小智 `main/boards/viewe-smartring-plus/` 源码使用 GPIO1 ADC，充电检测脚为 `GPIO_NUM_NC`；这支持“电量读取路径不匹配”的假设，但**未证明烧录的预编译 B 固件与这份源码完全一致**，也不排除真实充电故障。
