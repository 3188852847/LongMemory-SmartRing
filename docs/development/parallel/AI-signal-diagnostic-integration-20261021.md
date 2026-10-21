# AI：输入数值诊断与首次检索观测组合

日期：2026-10-21。基于 AB 冻结候选 `ae06f4b1bcb8ca53d5ce508b600a3137533d0ca1`，保留其 [v2 审查与精确升级接力](AI-first-recall-observation-review-20261021.md)。本轮只准备下一次真实采样的部署候选，未修复或验收实机打断，未改变 AEC/VAD/ASR 阈值、记忆行为或声音模式。

## 精确交付与启动

- AD `fee5eece775a094d2adfc622fe85ca60a5464d0b` 接为 `f11f64af`：[固定 AEC 合成证据](AD-aec-playback-input-20261021.md)及两份测试文件，没有算法修复或第四套观察器。
- AC `7dfcfca214d758ee3589c042cdcb33b2615ffec3` 接为 `3bb303ef`：[数值摘要定义](AC-vad-signal-20261021.md)、正式 helper、固定 Silero 类夹具与测试。未将此前未提交草稿作为发布来源。
- AI 在 [启动器](../../../scripts/development/xiaozhi/launch_with_memory.py) 的既有固定快照核验及实际 ASR 类型选择内，先完成 input observation，再装 signal observation。外层 control、直连 v2 及其他既有包装已经完成；任一诊断安装失败仍调用原业务 start 一次，不重试业务。

AC 用原次解码、AEC、VAD、推理结果做有限摘要，没有新增推理、线程或定时采样。`decode_return` 可能已包含直连 v2 的 AEC，服务器 AEC 前后应看 `aec_input/aec_output`。声明 true 不能证明实际非零时间戳、有效参考匹配或声学效果；AD 合成近端衰减及旧参考结果不证明现场根因。

采样解释补充：`inference_return` 在原 run 返回且观测成功读到合法概率后才计数；原 run 已返回但 feed/结果解析失败时，会记 `inference_observation_error`，不能将前者直接当成原 run 成功总次数。`probability_invalid` 也不会进入该成功概率计数。未导出 `inference_begin`，不按不存在的字段推断调用次数。

## 独立端点与体积决定

所有者明确选择独立只读诊断端点，ROOT 同时确认路径 **GET `/api/voice-input-signal`**。它复用 [原 control_http](../../../scripts/development/xiaozhi/control_http.py) 的 8766 回环服务、Bearer、Host/Origin/Sec-Fetch 检查、异常处理及 no-store 响应。没有新端口、UI 或 8767 投影字段；原 `/api/device` 和网页客户端 16384 字节上限不变。

原因来自 [合法上界样本](../../../tests/fixtures/ai_signal_device_status_boundary.py)：原设备状态含 64 段 TTS 明细、输入/输出/协议饱和计数和其余合法诊断字段，默认 JSON 已 **15519 字节**，紧凑 JSON 也有 **14330 字节**。不能把新对象直接塞入状态响应，也不删除旧明细或增加旧客户端上限。

新端点只返回当前明确且 OPEN 的已附着连接；不等待 MCP 工具，不调用设备。无连接/已关闭连接为 `no_connection`，未装观测为 `not_observed`，多个连接或失效旁路为 `unavailable`；不缓存断线对象。它与 `/api/device` 是独立读取，不构成同一时刻的原子快照，采样方须按前后窗口解释。

[voice_signal_diagnostics.py](../../../scripts/development/xiaozhi/voice_signal_diagnostics.py) 严格验证 AC 固定十字段、三分组、21 个固定顺序计数、能量/概率/实际加载阈值/参考摘要及有限数值。坏键、字符串、NaN、布尔计数或未知版本仅降为有限 `unavailable`，不输出原始错误。输出独立上限 **6000 字节**，比原 16 KiB 消费上限更窄。全字段、三组累计与近期、饱和计数和极端合法数值样本实测 **5243 字节**；缺测仍是 null，原时间戳、设备身份、波形、文本及逐帧序列均不允许。

## AI 独立检查

当前工作树源码导入明确；只用合成对象、自有随机回环 HTTP、已有 CPU Opus 与隔离解释器，未连接日用 8766/8767。测试中的现有客户端请求被明确转向测试服务器，其原始分块读取和 16384 字节检查原样执行。

- 新端点、实际 AC 摘要、旧输入启动接线、原控制端和网页客户端联合 **209 passed，0 skipped，1.10 秒**，报告 `data/test-tmp/ai-ac-signal-integration-review-01.xml`。包括鉴权先拒绝且 getter 未调用、精确 GET 路由、原状态整包 15519 字节原样读取、新响应 5243 字节读取、缺连接、隔离快照、坏字段降级与启动失败继续原业务。
- AD 固定源方法/真实 CPU Opus 合成检查独立 **5 passed，0.29 秒**，报告 `ai-ad-aec-reference-review-01.xml`。未运行声学模型，未将 60 秒旧参考或近端被压低当作实机证据。
- AD 资源缺失模拟及端点/质量门 **20 passed，5 个精确 skipped，7 subtests passed，0.45 秒**；`audit_report` 为 (20, 5)，报告 `ai-signal-resource-review-02.xml`。仅登记五个固定 CPU numpy/Opus 验收，不放行模块/前缀。首轮模拟未修改到 pytest 实际收集模块、实际仍执行五项，保留 `-01.xml`；第二轮在收集后对真实模块模拟缺失，未改测试前提或生产文件。
- 已有小智 **Python 3.10.20** 实际导入启动器、control、AC helper 和数值投影，无 Torch，getter 返回 `no_connection`；报告 `ai-signal-python310-import-01.json`。源码另经 3.10 语法检查。

这些组有重叠，不相加成独立用例总数。AC 自身 39 项及 CPU 原模型 12 场景/626 包/1170 推理证据保留在其交付，AI 本轮未重跑原模型或把局部 P95 当端到端成本。AB 先前独立检查仍见其记录，不重复全部旧大组。

## 管理证明与部署门

AB 改变了受管记忆原语摘要，当前为 `fc9d53ea2b90be3d9a80846b21eec9b389f2dbe4393b51d8956f3013fcd103e8`。新 provider 原字节仍为 31326 字节、SHA256 `f425a3824f3771a16e7bd8df2b022376257c0d8f6673cd70c23d552a8943f717`；仅允许已批准 `7241…` 精确旧版的显式升级。

ROOT 已授权在本组合清洁源码冻结后，用 `tests/fixtures/hy_management_receipt.py --managed-semantic`、已有 V 树 SDK、既有小智 3.10、AB 已捕获合成输入，在本树全新 ignored 目录生成实际管理证明及外围回执。冻结提交时该项待执行，现已按下节完成，不手改旧 proof、不访问日用个人库或模型。工具要求真实固定 SDK 验证零跳过、源 HEAD/源码/解释器前后一致，并由 Windows Job 管理测试后代。

ROOT 负责最终停机与一致备份、合入、精确 provider 升级、复制匹配 proof 和正式启动；AI 不推送、不操作日用/私有配置/个人库/设备。保持 buffered 及既有关闭设置，不混入 AG GPU、AE 双模型或持久化草稿。上线后由 ROOT 受控读取两端点和 AB 同轮基础/详情，所有者尽量一次真实对话采样；仍需真实视觉、声音和打断反馈。

## 最终源码对应的实际管理证明

组合业务冻结提交 **`3299e358cda6e3db8fac8e7d743c163dc6b33dea`**，Git tree `3c3bc3514cb3e04a382cfaf5310cbcdd0da446a4`；本次工具执行前后要求源码清洁且身份不变。固定受管语义验证 **219 passed、0 skipped、0 failure/error，438.71 秒**，正常退出0。包括真实 SDK 管理/重启、来源派生失效、只读意图、后台准入与跨 Python/HTTP 路径；不是重新执行旧大回归来代替本次身份验证。

所有新证据在本 AI 树排他目录 **`data/test-tmp/ai-signal-managed-proof-20261021-01/`**，未写正式配置。ROOT 部署可用该目录的 `management-verification.json`，外围审计用 `receipt.json`，二者不可混淆。证明为工具根据真实检查结果新生成的七字段协议2候选，不是密码学签名，不修改或覆盖旧证明。

| 原字节证据 | SHA256 |
|---|---|
| `management-verification.json` | `d9787e30fdeb49fb6f2dc3d5c062b0d3a73e4223e1df66302cca1ffb3082ca4b` |
| `receipt.json` | `0ad22195ef47d6333e328409c580f8db5c655abb2a6cad7c69c0f25a0a9bb77c` |
| `junit.xml` | `bbbd840c85792f68212261e5100bf115dc59c8f7eb1be55857c1eec0166485c8` |
| `pytest.log` | `42dd92b64eab76b68bd8b5f636b960bf84281fe0cd9da6a21767a07a8c679cb0` |
| 全部 `src/longmemory` 与 `scripts/development/xiaozhi` Python 文件名＋规范化字节 | `d3908f19053e17e440107ce7127c6effe41e65c4bf785353c7b699d7af938e4b` |

AI 独立复核七字段 proof 的精确内容、219 个 JUnit case 零跳过/失败、日志摘要、两套解释器摘要、最终管理原语摘要和全源码摘要，均匹配；复核回执在同树 `data/test-tmp/ai-signal-managed-proof-independent-review.json`。SDK 解释器 SHA256 为 `560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e`，小智解释器为 `8ce49d96ecba2dfd13b3cc99b5d8a18f6c0ad82bacf0df2f5d17a3df6a9cd203`。

此后仅追加本文与清单，不改变 `src/scripts/tests/web`。ROOT 合入后仍须核对最终源码与上述身份，保留回执实测 source HEAD，不将文档收尾或主仓新提交号伪写进旧回执。当前没有部署、真实 BGE 首次分段、设备信号采样或打断成功证据，实机失败状态不因此改变。
