# AD：CosyVoice 连续播放、可取消缓冲与后端能力接口

日期：2026-10-21。来源 `a93258e903954525b88b7af79756aaffe2bd50d6`，
工作树 `local/worktrees/ad-cosy-continuity-20261021`，分支 `codex/ad-cosy-continuity-20261021`。
任务由主会话分配；本会话仅提交自己的分支，不合入 main、不推送、不向其他会话发消息。

## 第一里程碑：核查、归属与接口

启动已核对分支和干净状态，读取项目 AGENTS、机器通用/Python/Node/GPU 规则、
X 的流式记录和 ADR-0190。主 Python 为现装 3.12.13；测试进程显式从本树导入
`src/longmemory` 与项目适配模块。真实 Opus 仅借用现装小智 3.10 环境做 CPU 编解码，
不加载 torch/模型、不写其源码或环境。未打开端口 18770 或其他日用端口。

文件归属与接线：

| 文件 | AD 范围 |
|---|---|
| `scripts/development/xiaozhi/cosyvoice_streaming.py` | 自有读流线程、连续 PCM、Opus 串行交付、自适应缓冲、取消和供给时间线 |
| `scripts/development/xiaozhi/cosyvoice_segments.py` | 保留现行自然分段与立即排空策略；不以字数猜测模型流式安全 |
| `scripts/development/xiaozhi/voice_latency.py` | 独立脱敏连续性摘要，既有 v6 格式不变 |
| `scripts/development/cosyvoice/service.py` | 后端能力合同与当前实例状态，既有模型/清理/声线链路保持 |
| AD 专属测试、本记录和 ADR-0197 | CPU 隔离验证与交接 |

AG 仅新增引擎适配/基准，不编辑上述服务/播放文件。AI 拥有统一启动接线，
AD 不编辑 `launch_with_memory.py`。主会话已分配 ADR-0197，设计见
[缓冲候选 ADR](../../adr/0197-cosyvoice-adaptive-playback-buffer.md)。

后端接口（供主会话转交 AG）：

```json
{
  "contract_version": 2,
  "audio_stream": {
    "protocol": {
      "supported": true,
      "version": 2,
      "path": "/v1/audio/stream",
      "framing": "uint32be-length-wav-zero-eos",
      "mime_type": "application/vnd.longmemory.wav-chunks",
      "sample_rate_hz": 24000,
      "channels": 1,
      "sample_format": "pcm_s16le"
    },
    "instance_usable": true,
    "incremental_usable": true,
    "default_delivery_mode": "buffered",
    "request_delivery_modes": ["buffered", "incremental"],
    "force_buffered": false,
    "cancellation": "token-boundary-and-join",
    "profile_identity": {
      "state": "valid",
      "config_digest": "<config-sha256>",
      "context_digest": "<model-context-sha256>",
      "selected_voice_warm": true
    }
  }
}
```

上述为字段示例，不是当前日用状态回执。`incremental_usable` 仅当固定运行时适配
明确 applied=True、未 force-buffered、实例可复用、档案未失效时为真。无适配器的
取消语义为 `drain-before-reuse`。profile 摘要缺失为 unavailable，格式错误为 invalid。
`/v1/capabilities` 和 `/health.capabilities` 同源；查询不合成、不暖机。
另一引擎必须实际实现同样的 v2/PCM 合同才能复用客户端，不能只更改 provider 名称。

## 实现边界

显式 `_longmemory_cosy_delivery_mode="adaptive"` 启用候选；缺省仍 buffered。
初始目标 360 ms，欠载后以 180 ms 步长恢复、最高 900 ms；本地 PCM 与预测下游
分别限制为 3000 ms。后续自然段共享当前轮库存；不创建固定的段间等待。
正常短尾在 EOS 放行；出错前积压直接丢弃。旧轮和新轮串行使用编码器，旧清理完成
前新轮不进入编码。未改声线/参考音/语速、原等待缓存、推理/标记过滤或模型选择。

连续性摘要为 `VoiceLatencyTracker.continuity_snapshot()`：每轮最多 32 段、无正文或
音频。包括客户端首有效 Opus、预测可播放/结束时长、最大/累计欠载、缓冲目标/峰值、
重缓冲次数、本地丢弃量、reader join 和客户端接收 RTF。摘要不进入原 v6 严格格式。
同轮后续段的供给时间线是整轮累计，时间原点为首次adaptive合成；缓冲/接收数字
属于当前段。客户端接收 RTF 包含 HTTP/CPU 重采样/背压，不能用于宣称纯模型推理加速。

## 验证记录

首批原有定向回归 86 项通过（9.64 s）。新增 CPU/真实 HTTP/Opus 检查 23 项通过
（5.62 s）。其中四个随机端口真实 Opus 用例各一次，两种输出率×正常/第三帧取消：

| 用例 | 首有效 Opus ms | 原生接收音频 ms | 最终 Opus 帧 | 最大/累计估算欠载 ms | 客户端接收 RTF |
|---|---:|---:|---:|---:|---:|
| 16 kHz 正常 | 664.8 | 750.0 | 13 | 0/0 | 0.8851 |
| 24 kHz 正常 | 233.9 | 749.958 | 13 | 0/0 | 0.4538 |
| 16 kHz 取消后新轮 | 213.3 | 750.0 | 13 | 0/0 | 0.4300 |
| 24 kHz 取消后新轮 | 232.8 | 749.958 | 13 | 0/0 | 0.4554 |

这些是固定正弦波+人工到达间隔的 CPU/HTTP 单次回放，包含 Python 首次导入成本，
不作统计分位、模型 RTF 或真实用户端到端结论。每次完整音频 13×60=780 ms，
仅正常尾部一次填充，原生样本不截尾。取消两例都只交付三帧旧音频、触发后新增旧帧
为零；随后 13 帧新轮完整交付。已交付给下游的 180 ms 不能视为设备立即静音。

背压测试发现旧的“ahead小于上限”判断可以多放一帧，已把下一帧计入准入条件。
随后扩大验证包含旧 finally/新轮并发、截断前 buffered 回退及下面的帧归属竞态。

最终定向组合 **202 项通过（28.98 s）**，包括上述新测试、既有服务/流式协议、
自然分段、真实 FIR/Opus、未适配模型清理与不可复用保护、固定控制流兼容、v6计时。
等待提示/答案交接、提示缓存与表达策略 **46 项通过（0.89 s）**。
最后补充 HTTP 阻塞读与初始 PCM 已缓冲时取消，两项均证实自有socket关闭、
读线程退出、服务生成器finally执行及 generation_gate 释放；该文件含原四个
真实Opus用例，共 **6 项通过（5.82 s）**。该阶段不同用例合计250项通过。

收尾审查发现帧在取消检查与回调之间可能切换全局句子编号。新增 `CosyVoicePacket`
捕获不可重新归属的轮次，计时回调不把旧帧标成新答案，队列入口逐项丢旧保新，
`install_audio_send_observer()` 同时包裹固定小智 `_do_send_audio`，在流控出队时
再检查，保留其他引擎和空 FIRST/LAST 控制消息。没有编辑第三方源码或等待缓存。
加入两项身份/混合批次检查后完整上述组合 **252 项通过（28.22 s）**；再加入
最终出队与重复安装两项检查，相关AD/计时/等待/表达回归 **84 项通过（0.99 s）**。
最后不同测试合计 **254 项通过**，并非252+84重复相加。此软件保护仍不能收回
设备已经接收并缓存的声音，真机残音必须另测。

主环境使用 `-B -X utf8 -m pytest`；全部在 AD 树执行，没有安装依赖。
202项命令的文件集合为：

```text
tests/unit/development/test_ad_cosy_continuity.py
tests/unit/development/test_ad_cosy_http_opus.py
tests/unit/development/test_cosyvoice_streaming.py
tests/unit/development/test_cosyvoice_service.py
tests/unit/development/test_cosyvoice_segments.py
tests/unit/development/test_cosyvoice_continuous_pcm.py
tests/unit/development/test_cosyvoice_unadapted_cleanup.py
tests/unit/development/test_cosyvoice_stream_runtime.py
tests/unit/development/test_cosyvoice_stream_benchmark.py
tests/unit/development/test_cosyvoice_stream_inventory.py
tests/unit/development/test_voice_latency.py
```

46项集合为 `test_voice_waiting_handoff.py`、`test_voice_waiting_cache.py` 和
`test_voice_response_policy.py`。最早一次命令误写不存在的 `test_voice_waiting.py`，
未执行测试；核对实际文件后运行上述46项，没有把不存在的文件视为通过。
`git diff --check` 通过。文档严格检查如实失败：两个新增文档未在公共
`docs/documentation-manifest.json` 登记，报 unlisted-document/unknown-selection；
未跨文件归属编辑清单，交 AI 整合时登记并再执行严格检查。

## 交付状态

代码与 CPU 验证已完成；分支提交由本会话收尾生成，提交号随最终交付给主会话。
没有 merge main、push、部署、下载、GPU加载、真实学校调用或个人库写入。
AG可按上述能力接口核对适配；AI需要按分配范围组合接线并更新公共清单。
GPU与实机矩阵仍为待验收，当前候选不能使日用默认自动变为adaptive。

## 待主会话调度的真实模型验收

目前没有 GPU 授权，未读取或修改共享声音配置，也未启动/停止日用服务。
无需下载新增资源；依赖沿用现装，缺资源时不自动安装。

最小窗口建议两类现行自然段（多句/长句）×buffered/adaptive×三轮，共12调用，
同一当前声线/参考音/语速/精度/种子序列，关闭精确回复缓存；另测初始读流、缓冲中、
已交付后三种取消，每次跟一轮正常回答。预计先申请8分钟硬限，实际时间由主会话
结合日用恢复预算决定；不与 AG 或日用抢 GPU，不由 AD 自行停服。

须记录说完→首个有效回答声音（等待提示不计）、TTS首 Opus、总音频/墙钟时长、模型
RTF、最大/累计欠载、误抢话/续说取消、打断后最后旧声及新轮首声。当前CPU结果
不能替代该矩阵或所有者设备体验，未通过仍 buffered。组合观测接线归 AI。

公共文档清单/主题索引归整合会话同步，AD 不越界编辑；历史 ADR-0190 与 X 结果保留。
