# V：圆屏记忆外层计时与隔离 SDK 探针

2026-10-20。基于精确主线 `783f15e9b1b1b184f2ab43f41ec7d2e5fc97d965`，分支 `codex/v-voice-observation-20261020`；此前短句分支和提交保留。此候选仅补观测，不是延迟优化结果，不自行部署。

## 当前证据及归属

主会话转交的两轮隔离真实探针，从文本 chat 入口起算，问题、库状态不同且声音已预热：

| 区间 | 轮1 ms | 轮2 ms |
|---|---:|---:|
| 进入 chat → Memory 请求 | 4 | 2 |
| Memory 请求 → 返回 | 9900 | 847 |
| Runtime recall（上一区间内部） | 9885.548 | 17.335 |
| Runtime prepare total（上一区间内部） | 9889.768 | 21.438 |
| Memory 返回 → 首文本 | 621 | 71 |
| 首文本 → 完整短回答/TTS 开始 | 15 | 51 |
| TTS 开始 → 首真 Opus | 1428 | 1762 |
| 首真 Opus → WS 发送返回 | 16 | 26 |

Runtime 装配 5339ms、TTS 加载 8.908s 和基础预热 1.974s 另计。探针未走生产首段切句或等待提示，ASR/设备播放未知。以上不能作为等条件前后提速证据，也不能据“12秒/2.8秒”认定某个具体冷启动。

轮2外层 847ms 减 prepare total 21.438ms 为 825.562ms；不能全部称为 HTTP。既有 `prepare_round_screen` 在调用 `prepare_user` 前已取得同一个 Runtime 锁，因此原 prepare 的内部 lock_wait 不包含这段首次等待。提供器/路由线程池、提供器锁、轮次持久化、请求解析也处于外层区间内。

BGE 权重加载和一次文档向量检查、常驻 SDK worker 初始化均是既有装配机制；没有在本补丁中新增或调整。SDK reader 首次创建、jieba/tiktoken 首用和向量库首次查询仍是待测候选，没有证据把 9.89 秒归因于首次建索引。本轮不会暖身、改锁、缓存查询、延后更多操作或改变记忆一致性。

所有者先前主观快答/暂停反馈不能归属为本项目链路提速：主会话后来核实OTA缺少斜杠，改正确并重启后才真正进入目标链路，声音和延迟随之改变。V未读现场正文或操作服务；以下仅为主会话转交的脱敏证据。

改址后Cosy请求0→8、正式审计2→4且unknown0，当前v6记录为cosyvoice3/model，开始于2026-10-20T07:02:25.338560+00:00。Memory就绪1948ms、模型请求1949ms/首输出2425ms、TTS开始2506ms/首真Opus7081ms/发送返回7085ms；首段结束7136ms，89个60ms帧对应5.34秒编码音频。首段TTS开始至首Opus4575ms、至本段结束4630ms，成为当前首答优先排查段；不能把整段耗时全称为净推理。后续多段仍慢，不把此前两轮不同问题的隔离探针作为这个真实轮次的前后对照。

response_completed为3616ms，早于音频就绪，不能当作语音完成；输入VAD644ms/ASR423ms与主时钟缺少精确交接，不直接相加冒充完整E2E，发送不等于设备播放。本候选仍不访问生产；后续应先只读核对首段长度、当前声线的快路径及声线注册/首段模式，再按主会话另定范围。本轮不切段、不更改声线/模型/内部流式默认。

## 两个生产文件中的候选观测

### 提供器：仅调用局部记录

`scripts/development/xiaozhi/longmemory_provider.py` 仍通过同一次 `asyncio.to_thread` 调用同一个 `_request`，没有新线程池、任务或额外 prepare。记录放在该次调用的闭包及 ContextVar（上下文局部变量）中，线程结束即释放，没有共享“最后一轮”快照或无限增长映射。

固定日志 `memory_request_timing` 包含 version=1、round_id、stage、status、timings_ms。round_id 是既有 begin_turn 产生的32位匿名 client_round_id，与 Runtime 同字段配对；不是设备ID、会话ID或24位 voice diagnostics round_id。缺少合法轮次时为 null，不导出原输入。固定时长：

| 字段 | 边界 |
|---|---|
| thread_handoff_ms | 进入 query_memory → 原线程函数开始，含提交/调度等待 |
| request_total_ms | 原线程函数开始 → `_request` 实际返回/抛出，含请求、校验和上下文构建 |
| handoff_total_ms | 进入 query_memory → 本条事件时刻，包含交接等待 |
| runtime_request_ms | 原 Runtime HTTP 调用的锁取得前 → 读取/解析返回或异常，含提供器锁和 HTTP；非纯网络时长；兼容 subprocess/跳过路径为 null |

`worker_returned` 的 completed/failed 仅表示物理调用返回状态。消费者取消另发 `consumer_cancelled/cancelled`；不把它解释为底层线程已停止，也不改变原线程写入或取消行为。迟到线程事件仍带原匿名轮次，不能归到下一轮。消费者取消时尚无的时长为 null，不能拿这条记录代替后续物理完成时长。

### Runtime：外层时钟独立于 prepare

`src/longmemory/application/memory_runtime.py` 的 `prepare_round_screen` 新增固定日志 `round_screen_entry_timing`：version=1、round_id、status 和 timings_ms 两键 `outer_lock_wait_ms/total_ms`。前者从函数入口至外层锁取得，后者至该函数返回/异常前、锁释放后，包含过期轮清理、reserve、原 prepare、prepared/failed 与 feedback。日志在释放原锁后输出。

原 prepare dataclass、计时起点、锁范围/存储调用顺序、返回二元组、异常、重试和递延语义保持。没有把新字段加入 HTTP 返回、Memory receipt 或严格 v6 设备协议。新日志不含问句、记忆、答案、供应商正文、路径或凭据；日志输出失败不改变业务结果。

日志 completed/failed 仅是本函数返回/异常边界，不是聊天、播放或跨存储事务的完成判定；failed 不证明未写入。业务原有取消、uncertain/unknown 和免费审计政策仍以原账本/接口为准，不被新日志替换。

Runtime 使用模块标准 logger `longmemory.application.memory_runtime`，不改 root logger 或审计 writer。现有 API 装配没有为它保证 INFO 级别接收器；X 的隔离 harness 须临时为这个准确 logger 挂接固定字段采集 handler，调用结束后恢复。提供器复用原小智 logger。当前仅新增观测点，尚不保证正式磁盘持久化或面板可见；若要统一接入有界诊断 writer，另由主会话分配路由/归属，不在本轮擅自改全局日志配置。

成功 Runtime 查询路径新增提供器5次、Runtime3次单调时钟读取，各一条固定大小日志；消费者取消另有一条事件。未引入等待、编码、网络调用、线程或后台任务。没有测生产磁盘日志/调度开销，不宣称真实额外耗时为零。

## SDK 专属隔离探针及尚缺接口

`tests/fixtures/hy_recall_stage_probe.py` 只供独立隔离 harness（实验夹具）显式使用，不被生产源码导入。它不导入/创建 SDK 客户端，不调用 search/prepare/模型或暖身。安装要求明确 isolated=True、实际 distribution 为 2.0.3、五个 SDK 源文件的固定 SHA-256、模块来源与同步/异步签名均匹配；全部核验后才在当前隔离进程包装内存引用，退出时恢复。已有包装或不匹配拒绝；发现并发替换停止 harness，不覆盖别人的引用。不改 site-packages 磁盘。

固定阶段为：

| 阶段 | 由谁包住原调用 | 包含内容 |
|---|---|---|
| sdk_roundtrip_ms | 父隔离 harness 的 scope | 现有一次 SDK RPC 往返，含传输/排队；不追加诊断 RPC |
| sdk_execute_ms | 子隔离 harness 的 scope | 同一次 SDK execute；不是父子绝对时钟相减 |
| reader_get_ms | ComponentFactory.get_reader | 缓存查找/首次创建，另计 reader_creations |
| tokenize_ms | reader_base 引用的 lemmatize_for_bm25 | 当前查询的分词/首用成本 |
| embed_rpc_ms | EmbedService.embed_with_meta | 包含截断检查、缓存及向量请求；不等同于纯 BGE 计算 |
| vdb_query_ms | ChromaVectorStore.search | SDK 向量库适配调用，含调度/过滤/回包处理，不冒称底层索引净耗时 |

记录只含匿名轮次、状态、reader 创建数和各阶段 calls/first_ms/total_ms/failed；没有参数、返回正文、异常正文、向量或URL。未执行阶段 calls=0、first_ms=null；total_ms=0是累计计数初值，不是测得零延迟。阶段可能嵌套，不能简单相加。scope 结束后清除关联，新轮独立；错误和取消仍透传原异常。

**未接入真实 RPC 采样。** 当前 worker 没有安装本探针，不能用当前夹具声称9.89秒已经拆解。后续若选用，需要主会话明确批准只在自有隔离子进程的 ProtocolService.execute 外包 scope，并由父 harness 关联原协议请求序号与匿名轮次；不添加生产 RPC 字段，不发第二次请求。若要修改生产 worker、core 或 API route 的线程池接线，须另定接口/文件归属，本轮不越界。路由自己的线程池排队仍未单独计时。

## 验证和交接

合成时钟测试覆盖提交等待/请求时长、单次 HTTP body及返回不变、原异常透传、日志失败、消费者取消后迟到线程、换轮隔离、外层锁等待、原存储调用顺序/prepare 时钟对象不变、非法轮次脱敏；SDK探针覆盖固定版本/源码拒绝、原调用仅一次、嵌套阶段、首次reader创建、异常/取消后恢复和新scope隔离。

SDK专属 Python 3.12.13 中只导入实际2.0.3模块，实际安装/恢复四处内存包装通过；网络被进程内拒绝，SDK实例0、请求0、安装期间新增线程0。五个磁盘源码指纹与方法 AST（抽象语法树）签名核对通过。没有创建向量库、运行推理、暖身或改变环境。

主 Python 定向回归首批137项、扩大后211项通过；之后补充并发引用变更拒绝用例，探针专项6项通过（与211项组合中5项重叠），共验证212个不同用例。实际小智 Python3.10.20 的提供器/探针语法与标准 `asyncio.to_thread` 单次原查询、匿名日志、ContextVar清理通过，网络请求0。`check_docs --changed` 仅作为候选导航，不据此批改历史文档；本轮实际 `--only` 新报告的 strict 返回1，仅有 unlisted-document/unknown-selection，因清单由X/Z维护而未登记，不能称正式strict通过。没有生产部署、真实SDK检索阶段样本、远程CI或端到端提速结果。V不维护X/Z归属的manifest。

交X的下一最小计划（待主会话审查/安排，本轮不执行）：

1. 先确认真实路由和代码归属。保持当前服务稳定，不能为这份候选擅自重启生产。
2. 在隔离合成库的同一快照、同输入、同设置中，给原已计划的调用增加上述scope，先收一组首次/重复调用；装配单列。每个测量包住原调用，不额外 search/prepare 来“取时长”，不改费用或unknown政策。不同库快照/声线/输入不能作前后对照。
3. 用同一匿名 client_round_id 对齐提供器与Runtime；用父/子harness关联SDK同一次RPC。首先解释外层差额，再解释recall内部。阶段未命中保留未知，验证ContextVar跨SDK现有loop的传播后才接受数据。
4. 同时核验计划调用数、LLM/embedding调用和写入审计，不为计数再请求一次模型。search可能写缓存/日志或其他状态，不能拿个人库做暖身。任何纯初始化暖身也要先证明不调用LLM、不写事实，再单独审查；本补丁没有启用暖身。
