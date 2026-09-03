# SmartRing-Plus 圆屏终端

本目录预留给后续设备集成。V0.1 不在主仓库复制上游 SmartRing-Plus 或 Xiaozhi 全量源码。

- `smartring_plus/`：本项目的设备端入口或上游引用说明。
- `configs/`：可提交的构建与设备配置示例。
- `patches/`：对明确上游版本的补丁。
- `diagnostics/`：独立硬件诊断程序；目前包含 [AXP2101 只读电源诊断](diagnostics/axp2101_readonly/README.md)，不属于 LongMemory Core，不自动烧录。

本机验证使用的上游仓库位于独立工作区，不作为当前 LongMemory Core 的实现依赖。
