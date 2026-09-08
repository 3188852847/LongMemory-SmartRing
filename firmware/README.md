# SmartRing-Plus 圆屏终端

本目录用于可审计的设备集成。主仓库不复制上游 SmartRing-Plus 或 Xiaozhi 全量源码。

- `smartring_plus/`：厂家 B V2 的来源身份、关键哈希、构建基线与设备端入口说明。
- `configs/`：可提交的构建与设备配置示例。
- `patches/`：对明确上游版本的补丁。
- `diagnostics/`：独立硬件诊断程序；目前包含 [AXP2101 只读电源诊断](diagnostics/axp2101_readonly/README.md)，不属于 LongMemory Core，不自动烧录。

本机验证使用的上游仓库位于独立工作区，不作为 LongMemory Core 的实现依赖。固件补丁策略见 [ADR-0090](../docs/adr/0090-audited-upstream-firmware-overlay.md)。
