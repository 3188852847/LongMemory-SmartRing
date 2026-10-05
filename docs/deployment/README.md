# 部署文档

## 最新进展（2026-09-03）

用户已确认设备网页可控制圆屏；本机控制台设备页和记忆管理页已实现，使用说明见[本机控制台](local-console.md)。网页端口 8765、小智内部控制桥 8766，均为回环地址。记忆库需显式指定，默认只读；助手角色和运行记录仍待接入。以下早期阶段记录不代表当前进展。

后续验收更新：LongMemory 已由用户启用，猫名召回与毛色未知的问答日志符合预期；用户明确确认重启召回和来源查看完成。圆屏合成最小验收通过，准备阶段的待办保留作历史。人格候选另见 [elysia.skill 审查与启用方式](../third_party/elysia-skill-review.md)。

用户已提供圆屏接入自建小智后的 ASR、回复音频生成发送和再次监听日志。源码文件 `G:/00-下载/viewe-smartring-plus.txt` 已确认启动且 Wi-Fi 未连接时触屏松开或短按 BOOT 调用 EnterWifiConfigMode。以下早期步骤保留为过程记录，不再代表当前阻塞。

下一阶段的完整操作见 [圆屏接入 LongMemory 七步](xiaozhi-longmemory-demo.md)。适配代码与离线验证已完成，尚未替用户启用，实机记忆验收待执行。

V0.1 的 LongMemory 已在电脑本地运行；V0.1-Demo 开始准备圆屏的自有语音服务端。以下为准备计划，不代表已经部署成功。

## 第一步：取得小智服务端源码

- 仓库：<https://github.com/xinnan-tech/xiaozhi-esp32-server>。
- 先使用此前接口检查所针对的源码快照 `eb4b28c59ed7ed885258498cf757ce14352d620e`，避免下载过程中主分支变化；它不是“最新稳定版”的声明。
- 固定快照 ZIP：<https://github.com/xinnan-tech/xiaozhi-esp32-server/archive/eb4b28c59ed7ed885258498cf757ce14352d620e.zip>。
- 2026-09-03：本轮网页读取未成功，按用户偏好不反复重试，由用户下载后提供本地路径。收到后检查压缩包和实际源码，再决定依赖安装命令。
- 暂不安装依赖、不启动网络监听、不更改圆屏服务器地址、不调用校园网模型。
- 源码与运行环境将独立放置，不把第三方完整代码和依赖塞入 LongMemory 仓库或现有 `.venv`。

## 环境准备进展（2026-09-03）

- 用户已下载并解压指定快照；2026-10-06 整理后位于 `D:\LongMemory-local\runtime\xiaozhi-esp32-server`，实际 Python 服务目录为其 `main\xiaozhi-server`。
- 已检查实际依赖清单：上游推荐 Python 3.10；用户以 uv 创建独立 `.venv` 并生成 `requirements.windows.lock.txt`，反馈安装、依赖一致性和关键 Python 库导入检查通过。解释器配置显示 Python 3.10.20。
- 用户确认 FFmpeg 可通过当前终端 PATH 调用。该 PATH 配置尚未持久化为启动脚本，不代表 PyCharm 运行按钮自动继承。
- Opus 初次失败定位为 `opuslib_next` 的 `find_library("opus")` 未找到 DLL，不是 Python 包未安装。
- conda-forge Windows 64 位包 `libopus-1.6.1-h6a83c73_0.conda` 的 SHA256 已核对为 `c3678f111866235b44fa65265966abae7d90b6387178f1459afaedcee8b4a997`，包内 DLL 为 `Library/bin/opus.dll`。
- 用户按步骤放入服务目录下 `native/libopus-1.6.1/Library/bin` 并配置当前终端 PATH，实际静音编解码测试通过：640 字节 PCM 编码为 3 字节 Opus，解码返回 640 字节。该结果只验证此测试帧可编解码，不证明识别/合成或设备链路已完成。
- 已检查 SenseVoiceSmall 配套配置、分词文件和示例音频存在，`model.pt` 尚待下载；完整服务尚未启动，学校模型未由助手调用。

## 下一阶段：音频组件验证（待用户执行）

1. 从上游部署说明指定的模型发布页下载 `model.pt`：<https://modelscope.cn/models/iic/SenseVoiceSmall/resolve/master/model.pt>，放入服务目录 `models/SenseVoiceSmall`。不要用其他来源的同名权重替换。
2. 使用本机 CPU 加载该模型，识别仓库自带 `example/zh.mp3`；单独验证 ASR，不连接圆屏或学校模型。
3. 用本地已有 ONNX 文件检查 SileroVAD 是否可加载；该项只验证模型加载，不代表端点检测效果。
4. 用 EdgeTTS 合成一条明确的测试文本并播放。EdgeTTS 是外部在线服务，文本将发送至微软服务；不使用真实个人对话。
5. 通过后再配置完整服务和学校模型。已检查小智 OpenAI 兼容提供器使用 `stream=True`，学校模型此前非流式调用通过不能代替流式验证。Memory 适配尚未实施。

## 后续顺序

1. 完成独立 ASR、VAD 和 TTS 验证。
2. 准备本地配置与启动脚本，验证服务能在电脑启动；不提前开放公网或改变设备地址。
3. 接通圆屏与自有服务端的基础语音链路。
4. 接入独立 LongMemory，完成跨会话、重启后的记忆演示。

学校模型仍由用户在校园网验证；不把厂家服务上的正常对话当成自有服务端部署成功。

## 本机服务配置与启动工具

用户已反馈上述 ASR、VAD、TTS 三项检查全部通过。准备进入完整服务启动，尚未完成真实流式调用或服务端启动验收。

- 工具：[setup.py](../../scripts/development/xiaozhi/setup.py)。使用外部小智 `.venv` 的 Python 执行，不使用 LongMemory 解释器。
- 模板：[local.example.yaml](../../scripts/development/xiaozhi/local.example.yaml)。`init` 在外部服务的 `data/.config.yaml` 创建私有副本；已有配置时拒绝覆盖。
- 仅在私有副本中填写 `LLM.CampusLLM.base_url` 和 `api_key`，保持 `model_name` 与已验证接口一致。此 YAML 不自动展开 `${环境变量}`；不要把真实值填写到模板、截图或发给助手。
- `check-config`：解析配置并验证本机地址、模块选择和运行文件是否存在；无模型请求，不代表完整服务可启动。
- `check-stream`：通过 OpenAI SDK 发送固定合成句，使用 `stream=True`，要求收到非空 `delta.content`；不输出密钥或响应正文，无自动重试。HTTP 需加 `--allow-insecure-http` 明确接受明文风险。用户负责在校园网运行。
- `start`：启动上游 `app.py`。自动为子进程补齐 FFmpeg、Opus 和本环境 Scripts 的 PATH，开启本地 Hugging Face 文件模式，不更改系统永久环境变量。
- 所有首次启动限定 `127.0.0.1:8000/8003`；Memory=nomem、Intent=nointent。不要把此阶段称为长期记忆集成成功。
- 默认 FFmpeg 路径对应已检查的本机 WinGet 安装；迁移后可用 `--ffmpeg-dir` 指定，服务目录可用 `--server-dir` 指定。
- 本地日志或启动日志中的地址文字不等于监听成功。启动后另外检查监听地址以及 `http://127.0.0.1:8003/xiaozhi/ota/` 的 GET 响应，再检查 WebSocket 握手。
- 2026-09-03：新增脚本 12 项纯离线测试通过，完整 Python 回归 104 项通过；使用小智 Python 核对模板合并与子进程 Opus/FFmpeg 路径检查通过。未调用学校模型、未启动实际服务。

在小智 PowerShell 终端执行（每项通过再进行下一项）：

```powershell
$xiaozhiSetup = "D:\02-项目\LongMemory-SmartRing\scripts\development\xiaozhi\setup.py"
.\.venv\Scripts\python.exe $xiaozhiSetup init
# 用编辑器填写外部服务 data/.config.yaml 后再继续
.\.venv\Scripts\python.exe $xiaozhiSetup check-config
# 切换校园网，明确接受 HTTP 合成测试风险后
.\.venv\Scripts\python.exe $xiaozhiSetup check-stream --allow-insecure-http
.\.venv\Scripts\python.exe $xiaozhiSetup start --allow-insecure-http
```

局域网开放、设备鉴权、圆屏 OTA/WS 配置以及长期记忆适配是下一阶段，不通过修改监听地址绕过本轮检查。

## 用户完成本机服务验收（2026-09-03）

- 用户在校园网执行 `check-stream` 成功：3 个非空内容块，共 5 字符。仅证明当前配置能返回可消费的内容流，不等同回答质量或语音闭环验收。
- 用户提供 `start` 日志：CampusLLM、nointent、nomem、SileroVAD 和 FunASR 初始化成功。
- 用户提供 HTTP GET 的 OTA 正常响应，返回 WebSocket 地址为 `ws://127.0.0.1:8000/xiaozhi/v1/`；无设备 ID 的 WebSocket 测试收到预期端口正常提示。
- 助手通过只读系统查询再次确认 TCP 8000/8003 都监听在 `127.0.0.1`。上游启动日志打印局域网地址不能代替真实监听检查。
- 当前没有更改圆屏服务器地址、没有修改防火墙、没有开放局域网或公网；Memory 仍为 nomem。
- 下一步依赖网络拓扑确认。上游 `allowed_devices` 是跳过令牌检查的名单，不是只允许这些设备的准入列表；OTA POST 还会为自报 device-id/client-id 生成令牌，因此单独启用 auth 不构成可信设备准入。共享校园网络部署需另做访问范围限制，不能直接当作安全公开服务。

## 局域网圆屏接入：执行准备

用户确认电脑使用学校有线网络、圆屏连接学校 Wi-Fi，并决定跳过独立手机连通性测试，直接使用圆屏验收。无线与有线互通仍是待实机验证的假设。

工具已支持 `--lan-ip`：保留原本机模式，局域网模式要求配置中的监听、WebSocket 和视觉地址与指定 RFC1918 IP 一致，并要求 `auth.enabled: true`、`allowed_devices: []`。`data/bin` 中存在 `.bin` 时拒绝本轮演示，不自动删除，避免切换服务器时意外下发固件。

2026-09-03 只读检查确认电脑以太网地址为 `192.168.124.45/21`，Windows 防火墙配置文件均启用。新增 [firewall.ps1](../../scripts/development/xiaozhi/firewall.ps1) 由用户在管理员 PowerShell 执行：

- `Allow` 只创建名为 `LongMemory-Xiaozhi-LAN-Demo` 的规则；指定监听地址、网卡、TCP 8000/8003、来源 CIDR，并从实际监听进程读取 Python 可执行路径。
- 初次建议来源 `192.168.120.0/21`，仅为电脑当前网段假设，不保证覆盖圆屏实际无线网段；若不通再取得实际地址调整，不改为 Any。
- `Revoke` 只删除本工具的规则，服务需另外 Ctrl+C 停止。已有同名规则时拒绝覆盖；不关闭防火墙、不改变校园网络的 Public/Private 分类。
- 规则是临时的手工生命周期，不自动到期；其他已有宽松规则可能扩大可访问范围，本工具不会偷偷删除它们。上游认证不是可信设备准入，故本阶段只使用合成对话，不存放个人记忆，不作为长期校园网络部署方案。
- 私有配置由用户编辑，不重新 init，不重填或复制密钥到项目模板。本机回退：停止服务、Revoke，将三个地址恢复为 127.0.0.1，再不带 `--lan-ip` 启动。
- 未实际执行防火墙修改或服务启动。Python 回归 117 项通过；防火墙脚本仅语法检查通过，真实 Windows 规则创建及圆屏连接待用户执行。

配置改动仅限 `server`：ip=`192.168.124.45`，websocket=`ws://192.168.124.45:8000/xiaozhi/v1/`，vision_explain=`http://192.168.124.45:8003/mcp/vision/explain`，auth.enabled=true，allowed_devices=[]。

```powershell
# 普通小智终端，先 Ctrl+C 停止旧服务；不必重复流式检查。
.\.venv\Scripts\python.exe $xiaozhiSetup check-config --lan-ip 192.168.124.45
.\.venv\Scripts\python.exe $xiaozhiSetup start --lan-ip 192.168.124.45 --allow-insecure-http
# 另开管理员 PowerShell，仅在需要放行本次演示时执行。
& "D:\02-项目\LongMemory-SmartRing\scripts\development\xiaozhi\firewall.ps1" -Action Allow -ListenAddress 192.168.124.45 -RemoteSubnet "192.168.120.0/21"
# 演示结束，撤销本工具的规则。
& "D:\02-项目\LongMemory-SmartRing\scripts\development\xiaozhi\firewall.ps1" -Action Revoke
```

圆屏应填写 OTA URL `http://192.168.124.45:8003/xiaozhi/ota/`，不是 WS URL，更不是学校模型地址。上游部署说明提供“配网页→高级选项→OTA 地址”流程，但 B V2 重新进入配网的具体按键/触屏入口尚未核实。旧版本源码中的“启动联网前短触屏/短按 BOOT”不能写成 B V2 已验证操作；不猜长按时长、不建议重刷固件。若用户找不到入口，需从厂家 B V2 板级源码或说明确认后再操作。
