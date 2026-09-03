# 圆屏音量通道：先验证，后做控制台

本文保留独立 CLI 技术验证流程。2026-09-03 用户已确认唤醒圆屏后控制通道操作可用；后续[本机控制台](local-console.md)复用此通道，不修改学校模型或发起模型探测。
只读/控制命令使用任何 PowerShell 都可以，代码执行固定使用小智 .venv，不需要 ESP-IDF 终端。

## 本步做了什么

- 现有包装启动器可选开启本机 8766 HTTP 控制端口，命令行客户端在独立进程调用。
- 用当前设备上报的 MCP 工具和参数检查，不根据旧固件猜测能力。
- 只允许读取音量及设置 5–60 的音量；先读旧值、等待设置回执、再读回。
- 不改人格/记忆/数据库/固件，不打开任意模型工具，不加防火墙放行规则。
- data/control/device-control.token 首次显式启动时自动生成，后续复用；不复制、截图、分享或提交该文件。

## 1. 停止旧服务，再显式启动

在旧服务终端 Ctrl+C，确认返回命令提示符。不要同时开两套小智服务。
连接能访问学校模型的网络，沿用已验证有线 IP；若 IP 变化，先沿原指南核对配置和防火墙。

```powershell
Set-Location "D:\ESP32-Workspace\xiaozhi-esp32-server\main\xiaozhi-server"
$xiaozhiSetup = "D:\02-项目\LongMemory-SmartRing\scripts\development\xiaozhi\setup.py"
.\.venv\Scripts\python.exe $xiaozhiSetup start --lan-ip 192.168.124.45 --allow-insecure-http --device-control
```

应出现 `设备控制已开启：http://127.0.0.1:8766`。原先的记忆和语音初始化仍保留。
若出现上游版本不符、端口占用等错误，停止并发回固定错误信息，不自行跳过检查或终止未知进程。
上游 app 的任务失败不一定自动退出整个进程；因此不能只凭其他启动日志认定控制端口开启。

## 2. 新开终端，只查看握手状态

```powershell
Set-Location "D:\ESP32-Workspace\xiaozhi-esp32-server\main\xiaozhi-server"
$deviceControl = "D:\02-项目\LongMemory-SmartRing\scripts\development\xiaozhi\control.py"
.\.venv\Scripts\python.exe $deviceControl status
```

期待 connection_count=1、ready=true、read_volume_supported=true、set_volume_supported=true。
status 不主动向设备请求工具、不调用模型、不改音量，只查看当前连接缓存。
如果 device_offline，轻触圆屏唤醒或进行一次普通合成对话后再查；配网成功不等于此时有活动 WebSocket。
若 tools_not_ready，可稍后再查一次；若工具不支持或重复连接，停在这里，不继续设置。

## 3. 读取，再设置一次

```powershell
.\.venv\Scripts\python.exe $deviceControl read-volume
.\.venv\Scripts\python.exe $deviceControl set-volume 30
```

第二条会依次执行读值、设为 30、再读值。记录第一次音量，以便需要时恢复。
返回 acknowledged=true 仅表示设备回复接受；只有 verified=true 且 readback_volume=30 才表示设备状态读回一致。
随后让圆屏说一句话，由人确认实际听感。30 不是音量声压测量值，也不是“增加 30%”。
若超时，操作可能已经生效；不要连续重试设置，先 read-volume 核对。
支持状态不等于实际调用通过；独立进程模拟测试也不等于实机通过。

## 4. 回退

停止服务，使用步骤 1 的启动命令，但去掉末尾 --device-control。
无需重刷固件、修改 YAML、删除数据库或恢复助手角色。关闭控制端口不自动撤销已设置的设备音量。
如要恢复旧音量，可在仍开启控制时执行 set-volume 旧值（旧值必须落在当前 5–60 验证范围，否则先讨论）。

## 接口约定（版本 1 技术验证）

| 方法与路径 | 用途 | 返回重点 |
| --- | --- | --- |
| GET /api/device | 查看连接和已上报工具的支持状态 | ready、支持标志、固定错误原因 |
| GET /api/device/volume | 从当前连接读取设备音量 | volume |
| POST /api/device/volume | JSON 仅含 volume 整数 | previous/requested/readback、acknowledged、verified |

只接受固定 Host=127.0.0.1:8766、Bearer 本地令牌和回环来源；拒绝浏览器 Origin/Fetch Metadata。
没有通用工具执行、文件访问、原始配置或密钥查询入口。未来网页需独立的会话/CSRF设计，不直接使用该令牌。
HTTP 200 不一定表示设置读回一致，必须检查 verified；408/504 等失败也不能当作确定未执行。

## 完成标准与当前状态

离线：认证/Origin/Host/方法/参数/请求大小限制、上游 MCP 工具列表与回执解析、独立 CLI→HTTP 调用、超时/错误/取消/读回不一致覆盖。
实机：当前 B V2 上报两个工具、读当前值、设置适度音量、接收回执并读回一致、听感确认。
2026-09-03：170 项离线回归通过（新增 28 个控制单元用例和 1 个跨进程传输集成用例）。集成使用小智 Python 3.10、已安装 aiohttp 3.13.2 与真实上游 MCP 客户端/解析代码，设备回执由模拟器提供；未加载模型或连接真实圆屏。
默认 Windows pytest 临时目录拒绝访问，改用项目内唯一 .pytest-tmp/control-* 新目录后全量通过；未更改测试断言或清理既有目录。
关键上游文件只读哈希核验和 git diff --check 通过，控制令牌路径确认被 Git 忽略。
后续用户反馈：进入聆听状态后连接与读写工具均就绪，并确认音量操作可用。由此进入设备控制页面阶段；不据此宣称其他厂商固件无需适配。网页体验与 CLI 通过是不同验收项。
