# ESP-IDF 最小编译验收工程

仅包含 `app_main` 和 SDK 标准库，不依赖 managed component。2026-10-14 验收时将这三个源码文件复制到 `D:/Dev/esp-projects/smart-ring/sdk-probe`，在 ESP-IDF 5.5.4 专属子进程中编译 ESP32，并在另一个空 build 目录重建；没有烧录。

不要直接把本仓库的中文路径作为 CMake 工程目录。设置进程内 `IDF_COMPONENT_MANAGER=0`，对两个独立目录分别执行 `idf.py --no-ccache -B <ASCII-build> -DIDF_TARGET=esp32 reconfigure`，然后使用 SDK 专属 Ninja 的 `-C <ASCII-build> -j4 all`。目录和环境管理要求见 [固件恢复指南](../../../docs/guides/恢复固件编译-20261014.md)。

这是交叉编译器的最低验收，不代表圆屏应用、其他芯片、串口或硬件运行已经通过。
