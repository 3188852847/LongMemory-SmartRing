# 已确认故障记录

## 手工创建空 `uv.lock` 导致 uv 解析失败

- 现象：`missing field version`。
- 原因：`uv.lock` 是 0 字节手工占位文件，而不是 uv 生成的 TOML 锁文件。
- 处理：移走空文件后执行 `uv lock` 或 `uv add` 重新生成。
- 预防：`uv.lock`、依赖元数据和构建产物不得用空文件代替命令输出。

## Windows 并行编译 ESP-IDF 示例触发 GCC 内部错误

- 范围：SmartRing-Plus 官方 ESP-IDF 示例的本机验证。
- 现象：并行构建在 `esp_lcd_panel_rgb.c` 触发 GCC internal compiler error；`ninja -C build -j 1` 成功。
- 当前规避：该上游示例需要重新编译时使用单任务构建。
