# V：Memory 低延迟候选与完整数值观测

2026-10-20。基于 `87a25e2fd2c9b4486267dd3469fca354c12925a1`，分支 `codex/v-memory-low-latency-20261020`；旧 `3ea9146` 计时切片保留并 cherry-pick 为 `d1ef3cc`。本轮补充的 [ADR-0191](../../adr/0191-hy-short-input-and-owned-provider-session.md)说明等价边界和回退。未合入、推送或部署日用；没有GPU、真实模型、TTS、串口或个人库操作。

## 实现及已知限制

1. 固定 SDK 短文本截断快路径：字节上界充分条件成立才跳过必然原样返回的 cl100k 编码；长输入等交回原函数，计数保留。固定2.0.3、完整源码摘要和来源校验，内存安装/退出恢复；没有变更依赖或磁盘SDK。既有 token_count 回退不覆盖这个独立截断点。
   启动时在固定源码验证后准备公开OpenAI类和中文分词；不构造模型客户端、不执行SDK业务调用，初始化后事件与模型请求均为0。代价记入initialize/reopen，不和首次问话混算；失败保留原首次调用路径。
2. 管理来源由逐可见版本开账本改为一次请求内同连接批读，350个ID一批，保留来源顺序和 running/uncertain 排除；无跨轮结果缓存，同方法锁防止管理写与召回交错。
3. 自有网关实际校园上游普通请求/SSE（服务器发送事件）改为按身份持久HTTP会话，首次实际请求才创建事件循环和线程；120秒连接池，取消丢弃未读响应，关闭有界回收。不ping、不重试、不缓存答案；预算门和unknown结算、usage/DONE检查保持。原 SDK 已有连接池，新增的是网关上游复用；没有把仅官方地址命中的 voice_http_transport 称为校园HTTP/2优化。
4. 提供器 → 原API线程池 → Runtime外层锁 → 原JSONL → SDK既有loop → 返回头 → 提供器日志已接线。开关是内部请求头，字段白名单且数值有界，body/v6不变，不增加业务调用。API排队、Runtime外锁、SDK往返/执行、add/search/profile、分词、截断、向量请求/VDB和来源补足均可区分。画像关闭时不虚报画像阶段；归档单独由隔离基准测量，圆屏prepare_observe仍包括原归档/延后登记路径。

补正 [旧观测阶段记录](V-voice-observation-20261020.md)的待测范围：固定 SDK 构造已经初始化reader，且已有向量LRU/客户端复用；不是本轮新增。旧阶段未接收Runtime INFO和未接SDK scope的限制，现由内部 callback/header 和原RPC内scope接通；旧实测与归属仍保留。仍不能解释旧9.89秒的精确内部组成。

主会话转交的正确OTA现场记录为 Memory1948ms、模型首输出2425ms、首真Opus7081ms/发送7085ms，TTS首包等待4575ms；这属于原代码现场，不是本轮对照。X负责TTS，V不触碰其配置/运行资源。当前不承诺用户说完到有效首答≤2秒，更不把等待提示当首答。

## 合成测量方法

`tests/fixtures/hy_short_input_benchmark.py`用主3.12解释器和已有专属SDK3.12.13，只读环境、不安装。worker禁网、MockTransport替代模型、真实2.0.3和Chroma、全新显式合成目录；最终基线与优化只切换截断快路径和纯本地初始化，交替先后顺序，源码前后摘要必须相同。初始化、首次空召回、原话归档、observe、重复回执、热态重复/不同查询、关闭/重开和重启召回分列；持久化与检索分别检查，模型质量/最终自然语言答案不在该速度基准内。另以同一合成管理账本，原逐ID SQL对照批读，七次交替测量。

本地检查不代表远程CI，未运行远程CI。

原始产物保存在本工作树 `data/test-tmp/` 下的唯一目录，不提交Git；公开记录只保留无正文汇总与摘要。少量样本报告P50和最大值，不把最大值称P95。早先运行中有并行源码修改的探索样本不作前后提速证据。

最终冻结运行：北京时间2026-10-20 20:59:18–21:00:02，根目录后缀 `hy-review-final-c032248845fb425dab9795cf2ad2c3ef`；源码规范化摘要 `97e1696e0b7d0b3e03635a02a7f3c958b0df65a805918afdeb6b2c9918942de5`，三组全部前后相同。汇总文件SHA-256为 `ac88edee0b1d381db889a463aeaff03bf1613a17944a8d7ab0ceb6431916fe8b`。

| 区间 | 基线P50 / 最大 ms | 优化P50 / 最大 ms |
|---|---:|---:|
| SDK初始化（含本地准备） | 1620.111 / 1730.185 | 2618.964 / 2622.882 |
| 启动后首次空库召回 | 1616.413 / 1719.409 | 479.477 / 493.237 |
| 同一行启动＋首次召回总计 | 3328.351 / 3341.352 | 3098.441 / 3111.249 |
| 单独原话归档 | 3.032 / 4.744 | 2.199 / 2.238 |
| observe，模型为合成替身 | 161.572 / 172.232 | 164.252 / 172.936 |
| 重复observe回执 | 1.014 / 1.484 | 1.050 / 1.197 |
| 热态相同查询 | 4.305 / 9.659 | 4.051 / 4.284 |
| 热态三种不同查询，合计9样本 | 5.666 / 12.754 | 4.129 / 5.185 |
| 重开SDK | 1588.594 / 1604.120 | 2608.820 / 2626.560 |
| 重启后的首次召回 | 1656.629 / 1664.435 | 487.435 / 506.900 |

首次问话减约1137ms，主要是初始化移到启动期；启动加首次只减约230ms，不能说总计算提速1秒。热态重复查询只有不足1ms差异，少量毫秒差异不能推广成稳定改善。实际查询嵌套阶段P50：分词468.738→0.044ms，embed_rpc1142.639→474.456ms，reader_get约0.006/0.006ms，VDB查询约3.112/3.144ms。embed_rpc包含客户端/请求准备与合成向量传输，不能把474ms称为实际BGE耗时。另一组冻结样本启动加首次3195→3111ms、热态相同查询3.239→4.470ms，保留于 `hy-delivery-frozen-87531e7af88d4b26a0881663aea92d15`，不与最终样本混合；这也说明小样本/主机调度噪声不能当稳定总提速结论。

同账本七次交替批读对照（逐ID连接 → 一次连接批读）：1个ID P50 0.295→0.290ms，16个4.759→0.370ms，128个36.584→0.888ms，703个196.068→3.147ms；703个最大值219.240→4.583ms。这是合成平面账本的局部耗时，真实库可见版本数和记录量未知，不能折算成整轮节省196ms。

六臂所有归档先于observe、原文/来源、空库无结果、重复回执、不同查询和重启检索检查通过。每臂7次合成模型请求，重开后各1次，外部供应商请求均0。未做真实模型质量/声音验收。单独只切换短输入的先前冻结样本（摘要 `c7972d1ff057418a29acbdee6b16325d5a3daa210f8520b6f91e242ab0cf7bea`）首次召回1737.590→1559.413ms；它与最终样本分开，不混合统计或将全部差值归因于截断函数。

连接复用验证使用本地合成HTTP/1.1：多次普通/流式请求复用同一接受连接，提前弃读后换新连接；首次/复用连接失败各只发一次POST、下一轮显式请求才恢复。没有人工注入TLS节省来包装收益，没有校园实测延迟数字。校园是否保留连接以及是否返回前缀缓存命中字段仍未知。

重现命令（工作目录必须为此工作树；OUTPUT需由调用者换成不存在的唯一目录）：

```powershell
& 'D:\03-项目\01-正式项目\智慧圆屏\.venv\Scripts\python.exe' -B -X utf8 tests/fixtures/hy_short_input_benchmark.py --sdk-python 'D:\03-项目\01-正式项目\智慧圆屏\local\worktrees\v-hy-memory-20261019\local\runtime\hy-memory\.venv\Scripts\python.exe' --output 'data/test-tmp/OUTPUT' --repetitions 3
```

## 验证与整合要求

最终复核376项通过（81.90秒），覆盖全部方法单测、圆屏轮次、提供器/观测、文档机制，以及真实SDK/HTTP/3.10提供器、管理RPC/纠正删除与重启。此前扩大回归391项通过、1项跳过（169.58秒）；跳过项要求显式真实CPU BGE根目录，本轮不加载真实模型。独立只读审查发现坏观测大整数可导致OverflowError，已先界限检查再isfinite；坏HTTP头与成功SDK结果附坏观测均保持原业务返回，专项64项通过。新增真实SDK→合成回答器测试单独检查检索上下文送入、最终回答及助手归档；不代表真实模型质量。所有测试仅合成输入、独立临时路径/端口，未访问日用8767/8000/8003等服务。真实SDK/HTTP/Python3.10提供器检查已证明同一匿名轮次可穿过线程池、worker和SDK loop，来源、回执、纠正/删除、重启及零供应商请求分别校验。

整合前必须注意：worker/process_client改动更新管理原语源码摘要。最终代码须重跑 `tests/integration/test_hy_memory_management_rpc.py`、`test_hy_release_management.py` 后重新签发与最终摘要匹配的管理证明；V没有重写私有验证文件。旧证明按原规则失配拒绝，不降低门槛。最终管理原语摘要为 `e358debcfa870e09c6072645758d70ac4fa6792bcfb1dd5d589f3c1490657e04`，整合后源码变化须重新计算；不能直接照抄本摘要到私有证明。

## 补充交付：受控校园探针与管理回执入口

业务候选冻结为 `d1ef3cc59d857e898f9c803e2afc80d05cac94ac`＋`ae53f729dc73b549316b18dc770b2a02e6c56925`；本补充只增测试工具、针对性测试和本记录，不改业务实现。新入口为 [校园探针](../../../tests/fixtures/hy_campus_latency_probe.py)、[共享调用门](../../../tests/fixtures/hy_campus_probe_support.py)和[离线管理回执](../../../tests/fixtures/hy_management_receipt.py)。V仅运行本机合成上游和模拟回执测试，真实校园请求为0。以下真实执行由Z审查、X持有受控窗口后实施；不等待或占用X的GPU/TTS窗口来开发工具。

旧X的 `probe_only.py`/`stage_ops.py` 固定旧源码身份、输出目录和TTS入口，不能原样用作本候选的对照。新工具显式接收两份源码根、各自管理证明及原所有者配置根；源码必须Git清洁，记录HEAD、tree及规范化Python摘要，并在运行前后复核。新工具不启动/停止正式服务，不修改私有配置，不打开个人库或原官方付费账本，不新建付费池。所选校园配置与2026-10-19所有者确认免费身份必须匹配，CPU BGE仅加载已有离线资源，不安装或下载。正式部署证明也不会被工具覆盖。

两臂各最多两轮，使用相同固定角色与两条合成问题、相同模型身份和参数，各自新建空库。第一轮“记住无糖乌龙茶”完成回答和延后提取；第二轮检查同一来源已召回，采样答案后明确取消，避免多做一次提取。因此比较的是两臂相同轮次条件，不能拿第一轮与第二轮相减声称优化。每条件每臂只有1个样本，不计算P95，不据此证明模型质量。

单次调用门由两臂共享一个新账本，所有SDK提取与最终回答的请求在上游POST前占位；已完成、失败/unknown（不确定）及reserved（进行中）均计入总上限，最多8次。没有重试；HTTP失败、缺usage、断流、超时、取消或未结算状态都会永久暂停本次探针，后臂不再执行。到上限可提前结束，不能承诺四轮一定完成。失败后保留部分回执与占位，不可换目录自动重跑来重置这次授权的额度；下一次执行由协调方重新安排。各子进程先等待stdin许可，加入自有Windows Job（进程组）后才启动SDK后代，退出必须回收。

### Z：对精确源码生成离线管理回执

先完成最终整合审查及背景语义写关闭审查，再执行下列命令。`$BaselineRoot` 为清洁的 `87a25e2fd2c9b4486267dd3469fca354c12925a1` 检出；`$CandidateRoot` 为Z审查通过、包含V业务候选及所需X改动的最终清洁检出。两者均须现有隔离工作树，不能直接借用运行中的正式检出。`$CandidateHead` 填写Z已审查的完整40位提交号；该值故意不自动取当前HEAD，防止漂移后重新自证。工具根可用本V工作树，也可用已整合本工具的清洁工作树；输出只允许其忽略的 `data/test-tmp/` 下全新目录。

```powershell
$ToolRoot = 'D:\03-项目\01-正式项目\智慧圆屏\local\worktrees\v-hy-memory-20261019'
$OwnerRoot = 'D:\03-项目\01-正式项目\智慧圆屏'
$MainPython = Join-Path $OwnerRoot '.venv\Scripts\python.exe'
$SdkPython = Join-Path $ToolRoot 'local\runtime\hy-memory\.venv\Scripts\python.exe'
$BaselineRoot = '<Z提供的基线隔离工作树绝对路径>'
$CandidateRoot = '<Z提供的最终候选隔离工作树绝对路径>'
$BaselineHead = '87a25e2fd2c9b4486267dd3469fca354c12925a1'
$CandidateHead = '<Z已审查的完整40位提交号>'
if ($CandidateHead -notmatch '^[0-9a-f]{40}$') { throw '先填写Z已审查的提交号' }
$BaselineProofDir = Join-Path $ToolRoot ('data\test-tmp\hy-management-baseline-' + [guid]::NewGuid().ToString('N'))
$CandidateProofDir = Join-Path $ToolRoot ('data\test-tmp\hy-management-candidate-' + [guid]::NewGuid().ToString('N'))
Set-Location -LiteralPath $ToolRoot
& $MainPython -I -B -X utf8 tests/fixtures/hy_management_receipt.py --source-root $BaselineRoot --sdk-python $SdkPython --expected-head $BaselineHead --reviewed-semantic-background-writes-disabled --output $BaselineProofDir
if ($LASTEXITCODE -ne 0) { throw '基线管理验收失败，停止' }
& $MainPython -I -B -X utf8 tests/fixtures/hy_management_receipt.py --source-root $CandidateRoot --sdk-python $SdkPython --expected-head $CandidateHead --reviewed-semantic-background-writes-disabled --output $CandidateProofDir
if ($LASTEXITCODE -ne 0) { throw '候选管理验收失败，停止' }
$BaselineProof = Join-Path $BaselineProofDir 'management-verification.json'
$CandidateProof = Join-Path $CandidateProofDir 'management-verification.json'
```

审查标志是调用者已完成审查的声明，不能仅因命令需要而勾选。工具用已有主Python执行该源码下两份真实SDK集成测试：`test_hy_memory_management_rpc.py`、`test_hy_release_management.py`，SDK解释器必须Python3.12.13 / Hy2.0.3。显式源码cwd/PYTHONPATH、独立合成basetemp/JUnit、300秒超时；零失败、零错误、零跳过且有用例，源码/管理原语/SDK解释器摘要前后相同才生成四字段证明。元数据 `receipt.json`、JUnit及证明分别留存；失败不签发。该文件是可追溯验证回执，不是密码学签名；Z仍应核对对应回执、JUnit及审查提交，不能手填true或复制旧摘要。V没有替Z执行此最终验收。

### X：一次受控真实校园对照

沿用上面Z交付的变量及两个证明路径，核对 `$SdkPython` 与当前所有者deployment选择相同。X先确认独占本次CPU/服务测量窗口，避免同时测量或切换配置；工具不接管正式生命周期。只执行一次以下命令，不在失败后循环重试：

```powershell
$CampusOutput = Join-Path $ToolRoot ('data\test-tmp\v-campus-latency-' + [guid]::NewGuid().ToString('N'))
Set-Location -LiteralPath $ToolRoot
& $MainPython -I -B -X utf8 tests/fixtures/hy_campus_latency_probe.py --baseline-root $BaselineRoot --candidate-root $CandidateRoot --owner-root $OwnerRoot --sdk-python $SdkPython --baseline-proof $BaselineProof --candidate-proof $CandidateProof --output $CampusOutput --mode campus --execute-campus --request-limit 8 --rounds-per-arm 2 --arm-order baseline,candidate --timeout-seconds 180
if ($LASTEXITCODE -ne 0) { throw '探针已停止：保留原目录、检查回执，不重跑' }
```

参数 `--execute-campus` 是本次真实调用的显式开关。缺少证明、身份失配、dirty源码、复用输出目录或原模型/免费策略不匹配时，在请求前拒绝；未取得最终回执不算完成。受控窗口结束后X独立检查服务恢复，本工具不修改正式部署。

| 证据 | 可核对字段和含义 |
|---|---|
| `plan.json` | 两臂HEAD/tree/Python摘要、顺序、单次总上限、固定问题/角色摘要、工具/调用门/Job/SDK摘要、原配置摘要；不写密钥或对话正文 |
| `receipt.json` | completed/failed、固定错误码、已完成臂、结束时间；`calls` 含上限、暂停原因、按臂/状态次数及个人费用0。unknown/reserved不释放或伪称成功 |
| `baseline-receipt.json` / `candidate-receipt.json` | 各自初始化、SDK版本、来源及轮次；只在该臂完整结束后产生。失败臂可能仅有已写出的轮次文件 |
| `<arm>/round-1.json` / `round-2.json` | `prepare_http_ms`、原prepare阶段、存在时的SDK数值观测、`answer_first_text_ms`、`prepare_to_answer_first_text_ms`、`answer_total_ms`、完成/提取耗时、召回数量及来源布尔校验。第二轮明确 `cancelled_after_sampling` |
| `data/databases/probe-campus-calls.sqlite3` | 本次独立免费请求审计与按臂占位；`gateway_results` 是原网关诊断，成功回执要求逐请求诊断数量匹配。不是原付费或个人账本 |

时长覆盖CPU Memory内部认证HTTP至校园SSE首个非空文本；不含真实3.10提供器交接、ASR、TTS、设备播放。空delta、仅工具delta或等待提示均不计首文本。第一轮总耗时含完成/提取，答案总耗时单列并排除提取；SDK初始化前移不能折算为总链路节省1秒。各臂新目录保留合成库和来源以供核查，不提交原始产物。两个证明、三类回执与账本须一起交Z复核。

新增工具针对性验证：93项工具测试及14项文档机制测试合计107项通过（46.12秒），包括真实SDK接本地合成HTTP上游的双臂成功、500/缺usage/断流即停、上限1、证明不匹配零调用、来源漂移、取消/超时、SSE分包与仅工具delta、管理回执拒签条件；独立只读审查指出的Job关闭异常跳过后续回收已修，4项模拟测试覆盖继续kill/wait/关管道及拒签。文档严格检查通过。没有真实校园、GPU、TTS、个人库、正式服务或设备调用；管理回执自身的真实SDK整体验收留Z执行。

## 后续技术排序

下一阶段先评估语义 EOU（话轮结束判断）：[Smart Turn官方](https://github.com/pipecat-ai/smart-turn)支持中文、本地ONNX CPU，[官方量化单模型](https://huggingface.co/pipecat-ai/smart-turn-v3/tree/main)约8.68MB、BSD-2-Clause；环境占用另算。仓库README与示例版本存在v3.2/v3.1差异，实施前固定版本/摘要，由所有者下载。先授权合成中文影子回放：短问、犹豫、长停顿续说、否定纠正、数字枚举、背景人声、播放时插话。测误截率/结束拖延/CPU耗时，用户续说使旧判断失效；插话暂停不能等EOU。

[LiveKit预生成](https://docs.livekit.io/reference/agents/turn-handling-options/)可在最终确认前运行LLM，默认延后TTS；文本/上下文/工具修订须取消重算，已消耗token不能撤销。当前 `voice_asr_prefetch` 已重叠识别与静音，`voice_prediction`仅影子统计，不能重复宣称从零新增。先零外部调用模拟连接/话轮/修订/上下文版本绑定，后续真实实验每轮先限一次且计入原预算/unknown。Hy recall可能有缓存写，不直接提前运行；不提前归档、写Hy、执行工具或播放。本轮未下载模型、新增依赖或改变主架构。
