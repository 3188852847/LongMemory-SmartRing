# 安全故障摘要契约

更新：2026-10-14。本切片为 D 契约与可观测性的增量实现，不代表完整语音追踪或监控平台已完成。软件实现需由主会话整合，正式服务切换另行安排。

## 事实来源与日志归属

| 入口 | 写入所有者 | 内容与保留 | 切换边界 |
|---|---|---|---|
| `data/logs/launcher-events.jsonl` | 单实例 Python 启动器 | 固定控制操作、阶段、请求 ID、故障码、耗时；当前文件达到 1 MiB 时轮转，最多两个备份；内存保留最近 50 项 | 关闭旧启动器后由正式入口加载新代码；本轮没有操作日用进程 |
| `data/logs/xiaozhi-demo-v1.jsonl` | 记忆审计 logger 的已配置 writer | 保留既有白名单及 1 MiB／两个备份；在 API 请求上下文内自动附加服务端请求 ID | 保留已有调用方式与文件名称；不同时向同一路径配置多个跨进程 writer |
| `data/logs/diagnostics/api-<PID>-<运行随机标识>.jsonl` | 每个 API 进程独占 | 请求边界安全摘要及已观测记忆阶段；每个文件流 1 MiB／两个备份 | API 主入口开启；`create_app` 默认仅内存，测试可注入独立根目录 |
| 小智运行目录 `tmp/server.log` | 厂家配置与小智进程 | 厂家维护；本轮不读正文，不修改格式／轮转配置，不迁移正在写入的文件 | 未统一接管；需要后续核对厂家配置和停机边界 |
| 第三方 stdout/stderr | 受管子进程 | 原启动器继续 `DEVNULL`；不将供应商错误、识别正文或音频输出落盘 | 不改变此隐私边界 |

轮转仅由拥有该流的 writer 执行，不在只读状态接口中操作文件。API 每次运行使用独立文件名，避免多个进程相互重命名正在写入的文件。该规则限制**单次运行流**的容量，不限制历次运行累计容量；本轮不删除／搬迁旧证据。跨运行归档／总目录保留上限尚未实现，需在主会话安排维护窗口并确定精确目标后处理。已有大文件在下一次受控写入时才参与轮转，不在当前会话读取或搬动。

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

上下文变量是进程内关联，不会自动跨越任意线程池、独立进程或网络。以下尚未覆盖：真实小智客户端保存／继续传播新的 ID、ASR → 记忆 → 回答 → TTS → WebSocket 发送的完整会话、后台任务最终完成、硬件播放回执。圆屏已有延迟／首包时序仍由原设备接口单独提供，本轮不覆盖或改写那份事实。不能用时间相近、HTTP 200 或服务端首包发送补出未测阶段。

## 前端整合

新增 `web/react-chat/src/features/observability/DiagnosticsPanel.tsx` 为受控组件：主会话提供 `snapshot/loading/error/onRefresh`，`readDiagnostics(ChatApi)` 复用现有只读请求与认证。组件不启动服务、不自动轮询、不自动重试，展示最近 20 条、请求 ID、固定结果码、耗时及可展开阶段。

主会话可将其接入设备诊断区或系统总览，不需要本会话编辑 DeviceApp。若使用 query，设置读取重试为零或沿用已有受控读取策略；业务写请求保持不自动重发。已有 API 错误 UI 如需显示响应头 ID，由主会话统一审查共享客户端接口，本会话未修改它。

组件使用既有 antd，局部 CSS 只管理自身换行、间距与键盘焦点；无持续动画、固定栏或新视觉全局规则。前端依赖缺失，本会话未安装、未创建联接、未声称构建或浏览器验收通过。主会话整合后应在 1366×768、1440×900、窄窗口、放大字号与减少动画下检查展开、刷新、未知结果、加载和失败路径。
