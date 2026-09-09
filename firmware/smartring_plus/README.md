# SmartRing-Plus B V2 固件集成

这里保存 LongMemory-SmartRing 对厂家 B V2 固件的**基线身份和补丁入口**，不复制厂家全量源码。

当前本机工作对象：

- 厂家 ZIP 副本：`D:\SmartRing-Plus-main\examples\esp-idf\11_xiaozhi\xiaozhi-esp32-main_smartring_plus_B_V2`
- 干净短路径构建副本：`D:\sr-bv2`
- 补丁实验副本：`D:\sr-bv2-lvgl-assets`
- 板型：`viewe-smartring-plus`
- 应用：v2.2.3
- 工具链：ESP-IDF v5.5.4、Python 3.11.15、CMake 3.30.2、Ninja 1.12.1、Xtensa GCC 14.2.0

`upstream-baseline.json` 固定关键文件与构建产物哈希。它只证明我们使用的 ZIP 内容和本机构建身份，不证明对应某个未经核实的上游 Git commit。

后续流程：

1. 从干净的厂家副本创建新的短路径工作副本。
2. 核对清单中的关键文件哈希。
3. 应用 `firmware/patches/` 中明确命名的补丁。
4. 使用全新 build 目录构建并记录 map、应用、assets 与分区余量。
5. 先做离线审查；烧录仍需单独说明写入范围和恢复路径。

每次补丁实验的机器可读结果保存在 `experiments/`。0005 已完成受限运行时皮肤协议的构建、应用分区烧录、精确回读和重启保持；0006 在其上增加 160 字节的轻量状态动画，并已完成构建、仅应用分区烧录和独立读回，真机逐态观感仍待观察。记录固定产物、验证阶段与未验收项，不把本机工作副本或二进制提交进主仓库。

详细决定见 [ADR-0090](../../docs/adr/0090-audited-upstream-firmware-overlay.md)，实机证据见[固件审计](../../docs/research/round-display-firmware-audit-2026-09-08.md)。
