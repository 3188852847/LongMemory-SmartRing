# SmartRing-Plus B V2 固件集成

这里保存 LongMemory-SmartRing 对厂家 B V2 固件的**基线身份和补丁入口**，不复制厂家全量源码。

2026-10-14 开始恢复固件编译环境。当前恢复流程见[固件编译恢复指南](../../docs/guides/恢复固件编译-20261014.md)：原 ESP-IDF 5.5.4、官方厂家固定提交、项目累计补丁与全新组件；安装和真实编译尚待验收，不烧录圆屏。实际源码/build 使用 `D:\Dev\esp-projects\smart-ring`，SDK 使用已登记的 `D:\Dev\esp\v5.5.4\esp-idf`；本目录保存补丁、版本和摘要。`restore/` 累计补丁包括早期项目改动与 0012 状态，历史阶段补丁继续保留，不能在累计补丁之上重复应用。

以下为重装前的工作对象和验证记录，不是新电脑的现有安装：

- 厂家 ZIP 副本：`D:\LongMemory-local\firmware\vendor\SmartRing-Plus-main\examples\esp-idf\11_xiaozhi\xiaozhi-esp32-main_smartring_plus_B_V2`
- 干净基线归档：`D:\LongMemory-local\archive\firmware\sr-bv2-baseline`；旧构建缓存不可直接改目录复用。
- 补丁工作区：`D:\LongMemory-local\firmware\current`；直接从此路径构建，旧路径联接已移除。
- SDK：`D:\LongMemory-local\tools\Espressif\.espressif\v5.5.4\esp-idf`；已安装工具仍在 `C:\Espressif\tools`。
- 板型：`viewe-smartring-plus`
- 应用：v2.2.3
- 工具链：ESP-IDF v5.5.4、Python 3.11.15、CMake 3.30.2、Ninja 1.12.1、Xtensa GCC 14.2.0

2026-10-06 目录整理及旧联接移除已完成；历史实验记录保留当时路径，现位置与恢复依据见
[本机目录与依赖](../../docs/guides/本机目录与依赖.md)。原 `build`、`build-wallpaper-0007`、
`build-wallpaper-0008` 连同回退镜像保存在 `D:\LongMemory-local\archive\firmware\pre-path-migration`。
新路径完整离线构建已通过，产物在工作区的 `build-relocated`，未烧录。
后续在正确初始化上述 SDK 环境后使用 `idf.py -B build-relocated build`；不要复用归档中的旧 CMake 缓存。

`upstream-baseline.json` 固定关键文件与构建产物哈希。它只证明我们使用的 ZIP 内容和本机构建身份，不证明对应某个未经核实的上游 Git commit。

后续流程：

1. 从干净的厂家副本创建新的短路径工作副本。
2. 核对清单中的关键文件哈希。
3. 应用 `firmware/patches/` 中明确命名的补丁。0007、0010 与 0011 使用零上下文补丁以避免补丁文件中的伪空白告警，须先核对各自实验记录中的基线哈希，再使用 `git apply --check --unidiff-zero` 和 `git apply --unidiff-zero`。
4. 使用全新 build 目录构建并记录 map、应用、assets 与分区余量。
5. 先做离线审查；烧录仍需单独说明写入范围和恢复路径。

每次补丁实验的机器可读结果保存在 `experiments/`。0005 已完成受限运行时皮肤协议；0006 增加轻量状态动画；0007/0008 完成受限 GIF 真机显示并取消几何脸叠加。0009 将基础 assets 缩至 2 MiB，并增加两个 3 MiB 动态壁纸槽、设备端 SHA-256 校验、显式激活和回退；ESP-IDF v5.5.4 离线构建、首次分区迁移、运行时发布及重启精确回读已通过，回退和中断保护仍待演练。0010 在 0009 上增加服务端 AEC 与直连 WebSocket v2 时间戳音频实验，离线构建、仅应用分区烧录及独立读回已通过；自然插话正例已确认，仅回声负例和远场仍待观察。0011 在 0010 上增加“动态壁纸 / 几何皮肤”显式模式切换，只改 NVS 指针并保留 A/B 壁纸内容；补丁应用检查、ESP-IDF v5.5.4 离线构建、仅应用分区烧录和独立校验已通过，模式往返真机验收待完成。0012 将停止采音与控制连接分离，并补齐连接失败退出路径；离线构建、仅应用分区烧录和独立校验已通过，持久会话真机验收待完成。记录固定产物、验证阶段与未验收项，不把本机工作副本、个人媒体或二进制提交进主仓库。

0007 与此前只更新应用的实验不同：它要求成对写入 `0x20000` 的应用镜像和 `0x800000` 的 assets 镜像。不要只写其中一个，也不要因此改写 NVS、分区表或 OTA 数据。

0008 仅改变显示策略，复用 0007 的同一 assets 镜像，因此只更新 `0x20000` 应用分区。0009 首次迁移必须成套更新分区表、应用和 2 MiB 基础 assets；迁移完成后，普通换壁纸走独立 A/B 槽，不再重刷应用或覆盖基础 assets。

0010 的分区表和基础 assets 与 0009 哈希一致，只需在明确实机试验时更新 `0x20000` 应用分区；本机已保存 0009 的 v1 应用回滚镜像。服务端 AEC 在厂家配置中标为不稳定，完成“回声不误触”和自然插话正例前不得作为默认功能。

0011 继续复用 0009 的分区表、基础 assets 和 A/B 壁纸内容，只需更新 `0x20000` 应用分区。切换到皮肤模式不会擦除壁纸；旧 0010 应用镜像仍是恢复点。

0012 继续复用 0011 的分区、NVS、assets、壁纸和皮肤数据，只需更新 `0x20000` 应用分区。新行为由 `persistent_session` 能力声明门控；0011 应用镜像是本次恢复点。

详细决定见 [ADR-0090](../../docs/adr/0090-audited-upstream-firmware-overlay.md)，实机证据见[固件审计](../../docs/research/round-display-firmware-audit-2026-09-08.md)。
