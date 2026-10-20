# X：固定语音消费者与答案边界离线联验

2026-10-20。X 从已发布 `765ef5a118f3c5e061bc20430b78a7db11141820` 建立 `codex/x-voice-reasoning-boundary-20261020`。所有者反馈推理内容同时出现在圆屏发声和字幕；现场原始返回格式尚未确定，本记录不宣布现场故障解决或实机验收通过。

## 文件与责任

- [固定方法快照](../../../tests/fixtures/xiaozhi_voice_snapshot_eb4b28c.py)保留外部 MIT 许可，包含实际 LLMProvider 的四个方法和 ConnectionHandler.chat。仅规范化 Python 语法排版，没有改写业务控制流。
- [消费驱动](../../../tests/fixtures/xiaozhi_voice_boundary_driver.py)只使用合成消息、队列和对话；捕获发声队列 TEXT、store_tts_text 句子缓存、assistant 归档的共同文本，不合成音频或执行工具。
- [原消费者契约](../../../tests/unit/development/test_xiaozhi_voice_answer_boundary.py)固定历史缺陷对照和正常文本/新轮隔离；其中“泄漏”断言是缺陷复现，不是修复后的期望。
- [网关联验工具](../../../tests/fixtures/xiaozhi_gateway_boundary_probe.py)指定干净源码根和精确 HEAD，使用真实已安装 Python 3.10 OpenAI SDK、回环 HTTP、合成上游 SSE（服务端事件）及全新合成预算账本。子进程禁止非回环 socket 连接；上游替身不调用校园模型。X 不增加第二个过滤器，不修改 V 的业务实现或外部小智源码。

实际小智源码提交为 `eb4b28c59ed7ed885258498cf757ce14352d620e`。两文件均相对该 HEAD 未改：`core/providers/llm/openai/openai.py` SHA-256 为 `5dfec38041d28436362b4a1b0f5946d1bdff7bb9afb3501c6417037a6bd3b006`，`core/connection.py` 为 `e065c994bf3f926b81c69da045e09fad8c46d6fd1fc3e3a6403295aeab64e0fa`；路径前缀均为 `main/xiaozhi-server/`。联验前后核对提交、文件摘要、未改状态及快照 AST（抽象语法树）等价。

## 实际验证

原消费者专项 8 项通过（0.06 秒）。普通和工具分支只读 delta.content，不会自行把 reasoning_content 映射成正文。普通分支按单个增量匹配完整 think 标签，跨增量标签可漏出；工具分支没有该过滤。共同文本可同时带入发声、句子缓存和 assistant 归档，符合“发声和字幕同现”的一种可复现路径，但不能据此认定现场根因。

初次端到端对照使用 X 的 `d5a00821609b3c1693e1d98484c3c9d8cbac93a7`，该提交仅新增测试，`src/`、`scripts/` 与发布版本无差异。10 个普通/工具分支组合复现完整/跨块标签路径差异。首次指向 Z 的尝试因其文档工作区不干净在 preflight 停止，未发起测试或外部请求；未清理 Z 改动。

最终候选是 V 的精确提交 `177950f3cd141b30ae84c88962568c64feafd9a3`，测试前后 V 均干净且 HEAD 相同。14 个组合均完成，三处共同文本始终相等，每次只有 1 次合成上游调用，预算无 unknown/inflight：

| 输入格式，每项均测普通和工具分支 | 候选结果 |
|---|---|
| 独立 reasoning_content ＋最终 content | 只保留最终回答 |
| 前导 think 块分成两个增量 | 只保留最终回答 |
| 同一增量含完整 think 块和最终回答 | 只保留最终回答 |
| think 起止标签跨增量拆开 | 只保留最终回答 |
| analysis、think 普通词 | 正常保留 |
| analysis 标签跨增量 | 仍透传；不属于约定解析语法 |
| 无标签普通 content 中的内部标记 | 仍透传；不能安全判别为推理 |

前五项共 10 个支持范围组合通过精确答案断言，后两项共 4 个限制对照通过“仍透传”断言。`all_clean_answers=false` 如实保留，`all_supported_answers_clean=true`；没有把限制对照计作已清理格式。

本地忽略证据根为 `data/test-tmp/`：初次对照 `xiaozhi-gateway-baseline-d5a0082-20261020/report.json`，最终候选 `xiaozhi-gateway-candidate-final-177950f-20261020/report.json`，后者 SHA-256 为 `8f4fda64dd0d46fe49abce64c2be9fda49d0c4504a51526cc04d0a0b55820f13`。无真实模型调用、个人配置/个人库、GPU 或 TTS；工具参数及取消语义由 V 的专项回归另验，本联验不执行工具、不宣称音频播放或打断验收。

复跑需指定 `--source-root`、`--expected-head`、`--native-root`、`--voice-python` 和新的 `--output`。候选使用 `--require-supported-answer` 验证上述有限范围；`--require-clean-answer` 更严格，会因两个限制格式仍透传而失败，不能据此扩大候选清理能力。

## 既有真实校园合成证据的只读核查

仅打开 Z 原配对探针目录 `campus-paired-765ef5a-a0fd48309a` 的 baseline/candidate 两份 `data/databases/synthetic-source.sqlite3`，SQLite 使用 mode=ro，并核对读取前后字节摘要。每库只归档第一轮一个 assistant，均为 4 字，无 think/analysis 标签，未命中无标签分析开头规则；规则未命中不构成通用语义证明。第二轮收据均记 10 字，采样后取消，没有归档回答，不能补推全文格式。未复制回答正文。

原探针工具 SHA-256 与 plan 一致，为 `76f8bfea779b716f548d51ed3a4a51110d936c1cdfc33fe18363ed3fb13af75e`；合成 ROLE 与原计划哈希一致，为 `d48519a69756a75b908e9fdb0d764a7593cef1eb1b4880cb46d48ebd8eb1352b`。这是专门的隔离合成角色，未证明等同当前正式圆屏角色。既有证据不足以确定本次现场格式。

旧 AnswerSink 首文本计时取第一个非空字符串 delta.content，没有最终可播报答案判断。因此旧数据只表示上游 content 首段到达；若首段是推理，不能解释成最终答案首文本。保留旧数字与原收据，不改写历史测量。

额外只读原共享调用账本，实际仍为 completed=6、reserved=0、unknown=0，hard_limit=8、halted=0；字节 SHA-256 为 `670f2987b068c1f72545f146f954c355ef29b946cd1a7fbf2954d303f684e205`，读取前后不变。未实例化会 BEGIN IMMEDIATE 的 calls_snapshot/调用门。匿名核查收据 `data/test-tmp/x-existing-synthetic-format-20261020/metadata-receipt.json` SHA-256 为 `7d6c6f2baf1d98435314487f1f58fc5b2aa61e4f6697a76edb25a2387eb2def4`。

现有正式匿名审计代码仅保存状态、固定故障码、DONE/forwarded/usage_seen 和 token 计数；没有 reasoning 字段名、标签标志或 reasoning_tokens 的持久字段。本轮未为找格式打开正式个人库或真实响应正文，未加全文日志。

## 额外诊断取消

主会话明确取消额外一次请求的准备与执行。本轮没有新增校园请求，原账本保持 6 次；没有为构造正式角色请求读取个人角色旁库或真实对话。现有合成 ROLE 不等同正式角色，真实格式仍不可判定；由根安排最小候选恢复后的同设备重试，再按新反馈决定是否进一步取证。

X 交付仅测试和记录，不 merge/push，不重启生产、不改配置或安装守卫，不烧录。由主会话/Z 安排候选审查、整合及后续真实字幕、语音和打断验收；当前现场验收仍未通过。

## 第二次实机失败与独立 ASR 封装快路修复

`34f9022` 发布及当前等待音补齐后，所有者再次报告“你好”答成日期/检索说明并显示结束符。X 依本条新增授权只读锁定 23:28:42 唯一新测试轮：归档 ASR 为“你好。”，assistant 246 字，实际路径 model；同轮 2 次 answer 和 1 次 Hy 提取完成。末尾实际为 Unicode `<｜end▁of▁sentence｜>`，并非 ASCII 拼法，输出不含 think 块。原始 SSE 字段、工具调用和 wire 消息序列未持久化；web_response 两阶段及尾部 system 只能由代码和调用数推断，不能称为原始请求抓包。输出与公开联网指令最长连续匹配仅 11 字日期片段，未证明整段指令逐字回吐。脱敏证据位于主项目忽略目录 `local/archive/voice-incidents/20261020-232842-hello/anonymous-round-evidence.json`，SHA-256 为 `f1db570c8c8ad9302cee5c7b817b2ceb3803a756732909fb53711eb6abd62b3d`；没有另存完整输出、读其它历史、重启或新增调用。

根另授权窄查快路输入。固定小智 FunASR 返回 dict，ASR 基类把 content/language/emotion 及可选 speaker 编码为 JSON 交给 chat；首次说话人 JSON 仍可能由 startToChat 保留。项目归档路由先调用 extract_user_text 解包，故归档“你好。”不能证明外层 wrapper 收到了纯文本。原 fast_response_for 对整段 JSON 去标点后查封闭表，可确切复现“归档文本能命中、封装输入不能命中”的独立缺口；该轮原始 wrapper 入参形状未留存，不把这一缺口提前认定为本轮唯一根因。

X 从 `34f902291ad319382732b00f35667cd63639628f` 新建 `codex/x-fast-asr-envelope-20261020`，只改 [快路匹配](../../../scripts/development/xiaozhi/fast_voice_responses.py) 与 [专项测试](../../../tests/unit/development/test_fast_voice_responses.py)。JSON 分支沿归档入口契约取有界 content、只认 user 来源；speaker/emotion/language 不作意图。原封装继续传给 Memory 和 Dialogue，depth=0、默认声线及 CustomTTS/url 严格相等条件保留，非法或非封闭意图仍走原链路。未改 V 的联网指令文件、生产、配置或数据。

专项 19 项通过，覆盖纯文本/ASR 封装一致性、完整原 query 归档、无模型预置路径、角色/畸形/超长内容回退、递归 depth 和 URL 精确门；Python 3.10 解析通过。该修复仍待根/Z 审查合入，不替代 V 的通用回答修复或真实双臂/设备验收。
