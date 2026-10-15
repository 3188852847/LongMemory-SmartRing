# 安全故障摘要契约

更新：2026-10-15。本契约含前轮 D 的 HTTP 安全摘要与本轮 Q 的语音关联／累计容量增量。Q 在独立工作树完成合成验证，待主会话整合；不代表日用服务已切换或完整语音追踪验收通过。决策见 [ADR-0180](../adr/0180-explicit-voice-diagnostics-and-retention.md)。

## 事实来源与日志归属

| 入口 | 写入所有者 | 内容与保留 | 切换边界 |
|---|---|---|---|
| `data/logs/launcher-events.jsonl` | 单实例 Python 启动器 | 固定控制操作、阶段、请求 ID、故障码、耗时；当前文件达到 1 MiB 时轮转，最多两个备份；内存保留最近 50 项 | 关闭旧启动器后由正式入口加载新代码；本轮没有操作日用进程 |
| `data/logs/xiaozhi-demo-v1.jsonl` | 记忆审计 logger 的已配置 writer | 保留既有白名单及 1 MiB／两个备份；在 API 请求上下文内自动附加服务端请求 ID | 保留已有调用方式与文件名称；不同时向同一路径配置多个跨进程 writer |
| `data/logs/diagnostics/api-<PID>-<运行随机标识>.jsonl` | 每个 API 进程独占 | HTTP 摘要及通过内部认证接收的白名单语音事件共享同一有界流；1 MiB／两个备份 | API 主入口开启；`create_app` 默认仅内存，测试可注入独立根目录 |
| 小智运行目录 `tmp/server.log` | 厂家配置与小智进程 | 厂家维护；本轮不读正文，不修改格式／轮转配置，不迁移正在写入的文件 | 未统一接管；需要后续核对厂家配置和停机边界 |
| 第三方 stdout/stderr | 受管子进程 | 原启动器继续 `DEVNULL`；不将供应商错误、识别正文或音频输出落盘 | 不改变此隐私边界 |

轮转仅由拥有该流的写入者执行，不在只读状态接口中操作文件。API 每次运行使用独立文件名，避免多个进程相互重命名正在写入的文件。单流上限不限制历次运行累计容量；Q 增加只读总量核对与保留计划，**没有自动执行累计上限或删除工具**。已有大文件在所属写入者下一次受控写入时才参与原有轮转，不在本轮读取或搬动。

诊断 writer 为私有 handler，不替换 root logger，不接管第三方日志。写入或轮转失败时保留内存摘要并标记 `persistence=unavailable`，不阻断服务操作。两个真实合成子进程写入不同文件的测试覆盖了文件所有权；不据此声明厂家 writer 多进程轮转安全。

## 只读接口

| 接口 | 认证与语义 |
|---|---|
| `GET /api/observability` | 原控制台 Cookie 会话、Host／Origin／跨站检查；无 CSRF 写操作；不支持 POST |
| `GET /api/launcher/observability` | 原启动器 Bearer、Host／Origin／跨站检查；只读取启动器内存事件 |

两者均不接受日志路径、不提供原始文件下载、不加载历史日志正文、不重试业务。摘要轮询和 API 主机的静态资源请求不会新增诊断事件，避免挤掉真正故障；接口响应仍带独立 `X-Request-Id`。普通业务 API 的状态轮询会计入最近 100 条，长时间后仍可能挤出旧故障，摘要不是永久故障账本。启动器原 `/status` 首次观察允许记录初始阶段，后续阶段由控制器实际转换记录，不再由轮询推断。

API 响应版本为 `schema_version=1`，主要字段如下。

| 字段 | 定义 |
|---|---|
| `scope` | `current_process`，仅当前 API 进程；启动器另为 `launcher_process` |
| `requests` | 最新在前，至多 100 条；重启为空，不视为“历史无故障” |
| `request_id` | 服务端生成 24 位十六进制标识；忽略客户端同名头，不改变聊天幂等请求 UUID |
| `operation` | 固定投影：`console/chat/device/memory/memory_runtime/diagnostics`；不记录原始 URL、查询串、动态路径 ID |
| `stage` | 最后观测到的 `request/storage/extraction/retrieval/context/model`；缺少阶段时不推断下游成功 |
| `stages` | 最多 16 个既有白名单审计事件及入口起算的 `at_ms`；不是每个阶段的独立耗时或全链路 span |
| `duration_ms` | 请求入口至生成响应／观察到取消的耗时；处理中为读取摘要时的已等待时间，不包含客户端收到响应或硬件播放时间 |
| `code` | 固定错误枚举；未知错误降为 `server_error/request_rejected`，不复制异常文本 |
| `persistence` | `enabled/disabled/unavailable`；`enabled` 不保证所有历史请求都在内存或文件中 |
| `logs` | 固定默认路径的 `stat` 清单，只有 ID、归属、保留策略、存在状态、字节数；不返回绝对路径，不打开正文，路径解析逃出项目根时标记 `outside_root` |
| `voice` | 可选增量；当前 API 收到的显式轮次事件，最多 100 轮、每轮 128 项；独立于 HTTP `requests`，不加载历史正文 |
| `requests[].voice_round_id` | 可选增量；仅通过内部认证的记忆 prepare／complete 路由接纳有效 24 位十六进制轮次头；不是 HTTP 请求 ID，也不是数据库 turn ID |
| `log_retention` | 可选增量；固定日志范围的元数据累计容量和只读计划，含预算、归属、保护原因、统计完整性；不触发清理 |
| `device_playback` | 固定为 `unconfirmed`，本接口没有硬件播放回执 |

`logs` 清单是默认约定路径的文件元数据，不证明相关进程正在运行，也不覆盖自定义 `--memory-audit-log` 的路径；归属名称描述设计约定，不能据此确定某个当前 PID 的实际所有权。

## 请求结果语义

| `outcome` | 含义与使用边界 |
|---|---|
| `processing` | 已进入 HTTP 边界，尚未生成最终响应 |
| `succeeded` | 只读请求生成成功响应；不证明设备健康或其他任务成功 |
| `accepted` | 写请求生成成功响应；实际业务完成、生效与设备执行继续读取各业务接口 |
| `failed` | 读取失败或 HTTP 拒绝；不据此声明数据库／设备绝无变更 |
| `unknown` | 写请求遇到 5xx／超时，或响应取消；可能已经产生副作用，须重新读取状态，不自动重发 |

取消时记录的 499 是诊断内部状态，不代表给客户端发送了该 HTTP 响应。读取超时为失败，写入超时为结果未知。聊天业务可能在 200 响应中携带失败或完成状态，仍以聊天业务结果为准，本摘要只说明请求边界。

启动器 `request_result` 的 200 仍可能只是排队接收。后续 `phase_changed` 使用触发操作 ID，并记录 `configuration_rejected/readiness_timeout/child_exited/operation_failed/health_check_failed/stop_unconfirmed` 等固定故障码；`duration_ms` 从该控制请求排队时起算。停止失败的进程残留继续沿用原 `can_start` 约束，不重复启动。

## 请求关联覆盖

当前已覆盖：独立 HTTP 调用进程读取服务端 `X-Request-Id` → API 边界摘要 → `asyncio.to_thread` 中的既有记忆审计事件，审计文件自动携带同一请求 ID。合成子进程 HTTP 测试验证内部 Bearer 请求的这条边界，并确认客户端伪造 ID 未进入摘要。启动器 HTTP 动作 → 工作队列 → 就绪／停止／超时阶段也使用同一 ID，不依赖浏览器持续打开。

Q 增加独立 `X-Voice-Round-Id`，由项目包装器随机生成；HTTP `X-Request-Id` 继续由各服务端生成并忽略客户端同名头，不改变业务幂等 ID。浏览器头不会被用于关联。只有已通过内部认证的记忆路由会把轮次加到请求摘要与既有记忆审计上下文。

新增 `POST /api/internal/memory/voice-events` 沿用现有内部 Memory 的回环、Host 和 Bearer 校验，浏览器 Cookie 不足以投递。它只接收固定字段：`round_id/event/sequence`，可选 `http_request_id`；CosyVoice 来源还须 `source=cosyvoice` 与其服务端 HTTP ID，事件也限 `tts_service_*`。不接收正文、异常、提示词、音频、地址或路径。事件投递请求本身不挤占 HTTP 最近请求列表，仍有自己的服务端响应 ID。

小智和 CosyVoice 使用同一 Python 3.10 标准库 helper。每进程观测队列最多 256 项，单次投递超时 0.5 秒，不重试、禁用代理与重定向；业务不等待 HTTP。队列满、API 离线、写日志失败和进程退出可能丢事件。每个源使用独立序号；按轮次／来源／合成 HTTP ID 去重和显示缺号，不把跨进程接收顺序解释为先后或耗时。缺号为空也不能排除末尾事件丢失。内存容量与轮转都可能淘汰证据。

| 实际插入点 | 记录的事实 | 不作的推断／未覆盖 |
|---|---|---|
| `voice_input_latency` 的 `handle_voice_stop`／`startToChat` | 识别包装器进入、结果向聊天交接、失败／取消／超时；不读取结果正文 | 不证明声学推理完整耗时、准确率或音频采集完成；预取可能已提前推理 |
| 识别交接的连接私有执行器代理 | 若上游通过 `connection.executor.submit(connection.chat, ...)` 提交，显式复制该次上下文，保留原线程池和 Future | 本树无厂家快照，真实该路径未复核；其他提交方式不猜关联，聊天另建轮次，缺失阶段仍可见 |
| `voice_latency.chat`、记忆包装器、`_ObservedLLM` | 顶层轮次，精确句子映射，记忆请求／HTTP 响应，模型请求／首个有效输出／迭代返回及错误 | 模型迭代返回不证明有可用回答；工具递归仍属同轮，不推断供应商内部 span（独立阶段区间） |
| `longmemory_provider` 的 Runtime prepare／complete | 显式传轮次头；消费 prepare 的服务端请求 ID；记忆审计携带同一轮次和请求 ID | 逐轮 subprocess 教学兼容入口未扩展跨进程协议；不修改原单次完成回执与记忆算法 |
| `cosyvoice_streaming` 与本机 CosyVoice HTTP 服务 | 消费端带轮次及 HMAC-SHA256（使用共享密钥的摘要校验）证明；服务生成独立 HTTP ID。校验有效才回传生成进入／方法返回／写出响应／失败／断开／忙碌事件 | 普通 24 位轮次头只记 `local_caller_claim`，不会回传可信事件；旧服务、凭据不同或未带证明的兼容完整 WAV 回退请求不补关联。HMAC 仅用于观测关联，不改变合成业务准入，也不对抗持有同一进程凭据的本机程序 |
| TTS 包装器与既有发送观察器 | 合成方法调用／返回、编码音频产生、首个发送观察边界返回；实时答案沿原最终 socket 包装器计时 | 空返回、首包、排入队列和套接字返回均不代表全部合成段／整个回答发送完成，更不代表设备播放 |

相同连接最多保留 32 个精确句子映射，不回退到“最近一轮”。模型迭代器捕获开始时的轮次；取消、换轮和迟到事件归原轮。摘要只给 `observing/cancelled/failure_observed`，没有“全链路成功”。固定超时事件也归失败观察；合成通道失败及兼容回退分别记录。某个合成 HTTP 方法返回只能说明该请求，不能代表其他片段已完成。

`voice.rounds[].missing` 列出尚未收到的关键包装器事件；预置回答、其他 TTS 或未接入阶段也会缺失，**缺失不等于业务失败**。原 `coverage/uncovered` 继续表达整个能力边界；`uncovered` 中 ASR/TTS 不是否认已收到的局部包装器事件。硬件播放、真实 ASR／模型／TTS 质量、所有音频段完成和后台任务最终完成仍未验收。圆屏原延迟接口不变，不用时间相近或 HTTP 200 补出成功。

## 累计预算与可执行维护方案

`log_retention` 默认预算 64 MiB，最短保留 7 天，是只读维护计划参数，不是已执行的硬上限。范围为 `data/logs/diagnostics/` 的直接条目、启动器／记忆固定流及 `.1/.2`，厂家 `tmp/server.log` 与这两个固定后缀另计容量。厂家其他命名的轮转、自定义审计路径、历史恢复包和其他目录不在统计范围；不把这个总量宣称为整个磁盘日志总量。诊断目录未知文件也计入项目预算，但匿名显示并保护。

固定目录不递归，不跟随 symlink（符号链接）或 Windows junction（目录联接），包括指向项目内的链接；最多枚举 4096 个直接条目。无法访问、重解析点、目录条目或扫描截断均标为不完整，停止生成候选。不打开正文或输出绝对路径。该工具没有执行阶段，不承诺对抗并发恶意替换目录；维护前仍应停止相关写入者并重新取元数据。

活动 API 流及其轮转文件受保护；其他进程、固定流和未知写入者默认保护。PID 不存在／可能复用都不足以自动认定已停止。只有维护者先独立核对归属、进程已停、证据用途，再以**准确流名**声明 inactive，且该流每个文件均超过 7 天，才按整个流从旧到新列候选。厂家日志永不进入候选；不修改其配置或接管 writer（写入者）。候选仍留在原处，GET 不接收 inactive 或预算参数。

在已整合的检出根目录执行（现有 Python 环境，模块根由源码确定，不支持任意扫描路径）：

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src') # 仅本次终端；退出后不保留
& .venv/Scripts/python.exe -m longmemory.infrastructure.logging.retention
# 已另行核对某准确流已停止后，可仅预演该流，示例名称不能代替现场核对：
& .venv/Scripts/python.exe -m longmemory.infrastructure.logging.retention --budget-mib 64 --min-age-days 7 --inactive-stream api-1234-0123456789abcdef.jsonl
```

工具无 `--apply`、删除或移动入口。`unresolved_bytes>0` 表示预算尚不能由已声明候选满足，不扩大扫描或擅自清理。实际删除私人日志需另列准确文件、大小、保留理由、当前元数据及独立授权；本轮未删除、搬迁或解析既有日志。恢复／回退以保留原文件和原配置为前提，无数据格式迁移。

## 最小应用步骤与切换

1. 主会话审查并整合 Q；保持依赖锁、共享客户端和服务工厂不变。API 路由通过既有 `register_observability` 注册，不需要新增 factory 参数。
2. 在维护窗口核对日用进程所有权，由所有者／主会话按既有停止流程停旧服务，再从正式启动器开新服务；本轮不执行。新 API、小智启动包装与 CosyVoice 必须来自同一整合版本，启动器沿原方式传递同一 Runtime 环境凭据。小智 provider 仍由原正式启动步骤同步，不能在运行时手工覆盖。
3. 从受控面板手动刷新，核对轮次、各服务 HTTP ID、缺失及来源；旧进程无新事件不能视为健康无故障。旧客户端缺增量字段时继续显示原 HTTP 摘要。
4. 所有者另验真实识别、声音、打断与设备；本树合成模型和离线发送替身不能替代实机验收。任何设备播放始终标 `unconfirmed`，除非将来另有明确协议与验收。

## 前端整合

`web/react-chat/src/features/observability/DiagnosticsPanel.tsx` 保持受控：主页面提供 `snapshot/loading/error/onRefresh`，`readDiagnostics(ChatApi)` 复用原只读请求与认证。组件不启动服务、不自动轮询或重试，显示最近 20 条 HTTP 摘要、至多 20 轮语音事件和累计保留元数据；语音／容量在原生可键盘展开区域内。新增字段均可选。

主会话可将其接入设备诊断区或系统总览，不需要本会话编辑 DeviceApp。若使用 query，设置读取重试为零或沿用已有受控读取策略；业务写请求保持不自动重发。已有 API 错误 UI 如需显示响应头 ID，由主会话统一审查共享客户端接口，本会话未修改它。

组件使用既有 antd，局部 CSS 只管理自身换行、间距与键盘焦点；无持续动画、固定栏或新视觉全局规则。前端依赖缺失，本会话未安装、未创建联接、未声称构建或浏览器验收通过。主会话整合后应在 1366×768、1440×900、窄窗口、放大字号与减少动画下检查展开、刷新、未知结果、加载和失败路径。
