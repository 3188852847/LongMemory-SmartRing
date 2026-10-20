# AE：原ASR预取与候选RPC实际适配

2026-10-21。独立树 `local/worktrees/ae-proposal-adapter-20261021`，分支 `codex/ae-proposal-adapter-20261021`，基线AI `ee03aec75c2d6788fb67fd52043385712ef5b18f`。本段与core release分开；仅AE提交本分支，未合入、未推送、未启用日用。前段模块/协议证据见[AE前段](AE-preemptive-20261021.md)。公共清单由AI维护，AE仅做内存补充清单后的本文窄范围检查。

## 授权范围与实现

主会话授权新增[适配器](../../../scripts/development/xiaozhi/voice_proposal_adapter.py)、[ASR预取](../../../scripts/development/xiaozhi/voice_asr_prefetch.py)的最小只读通知及专属测试。不编辑AI的launch、HTTP、Runtime或冻结树；不操作个人配置/数据、学校服务、GPU、下载、设备或串口。默认关闭，有真实functions的日用路径在任何候选模型请求前跳过；纯文本v2不扩展工具协议。

prefetch新增不可变票据证明、ready/verified/invalidated/buffer_released通知。ready仅在当前有效票据真正完成后触发；verified复用原完整PCM前缀、generation、voice_stamp、language与长度检查，在清空票据前通知，不保留PCM。通知失败只撤销候选权限，不改变原ASR返回或正式fallback。

原上游 `receive_audio` 在 `startToChat` 调度chat线程后立即reset。适配器包装实际executor.submit，同时识别诊断ContextExecutor的Context.run提交；只有当前端点已完成PCM核验且实际提交同一chat时，才标记一次内部采音收尾。reset仍真正清空缓冲并推进原prefetch generation；本次buffer_released不撤销已交接逻辑话轮。标记受ContextVar作用域、证明对象身份和一次消费限制；显式listen reset、续说、新话轮、异常、abort与close仍同步提高取消epoch。提交失败立即撤权，不能用时间窗口猜测或全局忽略reset。

逐连接RLock保护逻辑代次与最终输出。原文本/音频队列put、store_tts_text和助手dialogue.put都在同一门内检查；abort清空原队列也在同一锁内。TTS后台线程无chat上下文时按实际sentence_id检查；新轮不能收到旧轮迟到音频。后来安装的完成回执捕获器在最终provider边界重新纳入外层门，不能先记录已撤权的助手文本。只接管tts.conn明确属于本连接且队列无界的实例；不能证明所有权时跳过候选，不修改共享提供器。门不替代设备已播放/在途音频验收。

适配器只通过既有五种RPC操作调用宿主，不调用正式prepare、工具、字幕或TTS。实际正式输入在私有provider代理看到，经完整有效输入/本线程formal metadata确认后，仍以原provider输出类型交回原chat链路。代理仅包装底层真正拥有的response/response_with_functions方法，其他方法/属性完整转发；未知生成参数、结构化消息、有工具、元数据或实际历史/system不符均走原正式回答。正式prepare仍由原chat一次执行。任务完成、固定回复或提前返回也清理未采用候选；关闭回执不明保留RPC占位并阻止新票据，不推断供应商计算停止或清除unknown。

## 精确接线契约

```python
adapter = install_voice_proposal_adapter(
    ConnectionHandler, fun_local, asr_base,
    enabled=False,
    preview_effective_input=preview,
    formal_metadata=voice_proposal_formal_metadata,
)
# AI在_ObservedLLM.__init__中，只替换连接私有_provider的赋值：
self._provider = adapter.bind_provider(connection, provider)
```

安装顺序：输入计时 → 原ASR预取 → SmartTurn → adapter；adapter不改变SmartTurn端点，也不使用shadow启动候选。disabled不改任何类/函数，bind_provider原样返回对象。enabled缺前提或重复安装直接报告，回退通过重启不安装完成。

`preview(connection, raw_asr) -> PreviewPlan | None` 只在ready调用一次。Plan.input是EffectiveVoiceInput，必须报告实际工具能力；Plan.with_memory(context)只在已隔离的副本中替换候选记忆，不重读运行中的历史/配置/集合、不取时钟。这样即使snapshot等待中原工作线程已追加user，也不会拼出重复当前消息。

内置 `preview_native_input(connection, raw_asr, *, tools_required, web_configured, style=None)` 提供固定上游纯预览：两项能力必须明确传入，绝不默认false或自行读私有搜索配置；有工具立即跳过，连角色/历史装配都不执行。无工具复制真实Dialogue消息、voiceprint描述与speaker集合判断，复用原get_llm_dialogue_with_memory、表达策略和网页说明函数；不调用副本上可能绑定回原对象的put，也不改introduced/system_introduced集合。speaker首次JSON/再次正文沿原上游行为，最终provider仍精确比对。预览生成当时的时间，正式链路独立生成其实际时间；改变即miss，不能把预览时间塞回正式输入。联网能力固定问答直接跳过候选。

`formal_metadata(connection)` 在实际聊天工作线程调用现有AI函数，返回精确formal_turn_id/client_round_id/session_id；缺回执、管理/固定回复或锁忙时不采用。RPC协程只在连接所属loop运行，工作线程等待有界；事件循环线程不进行阻塞result等待。正式回执不来自最近轮状态，也不重复query。

当前真实pipeline/realtime+configured搜索会提供functions，必须让preview报告tools_required=true，零候选请求；配置联网时的精确实时时间也不能假定前后一致。AI不能为安装而传固定false、关搜索或冻结旧时间。主机/语音两端发布先保持关闭；本文不是installed生产入口已完成。

## 第一阶段实际检查

[原方法加载夹具](../../../tests/fixtures/voice_proposal_adapter_native.py)只读本地Git对象 `eb4b28c59ed7ed885258498cf757ce14352d620e`，直接编译原ASR receive_audio/handle_voice_stop、startToChat、Connection reset/clear_queues方法；原chat另核对与既有公共快照AST完全相等。真实线程池与ContextExecutor、实际ASR-prefetch/PCM核验/正式chat调用边界运行，外围模型、Memory/RPC、队列为合成可控实例；没有导入或启动完整小智依赖/日用服务。

专属[适配测试](../../../tests/unit/development/test_voice_proposal_adapter.py)与原ASR测试 **48 passed in 2.59s**。屏障覆盖reset已执行但worker尚未运行、已获候选但原chat尚未入TTS队列时取消、新轮已出答案后旧轮继续、snapshot等待期间正式user已加入历史；还覆盖显式reset/abort/续说/close、元数据/date/role/history变化、完整PCM改变、真实speaker首次/再次预览、工具零RPC、保留provider能力和关闭ACK不明。

原ASR、输入/输出计时、SmartTurn、RPC/核心/连接桥/影子统计共十一文件回归 **282 passed in 15.79s，0 skipped**，其中原RPC使用显式Python3.10及AF固定 `06a332baae5416fcdbad2790dc71c162152e5da2` 的实际宿主测试。该组适配器新用例仍用合成RPC/Memory，不能冒充本段adapter→实际3.10 RPC→SDK/正式Runtime已组合通过；下一阶段单列真实组合证据。

```powershell
$env:LONGMEMORY_TEST_XIAOZHI_ROOT = 'D:/03-项目/01-正式项目/智慧圆屏/local/runtime/xiaozhi-esp32-server'
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -X utf8 -B -m pytest tests/unit/development/test_voice_proposal_adapter.py tests/unit/development/test_voice_asr_prefetch.py -q
```

缺显式原生仓库位置时原方法用例skip，不能按安装验收通过；不会下载补齐。尚待本段真实3.10 RPC/SDK/正式Runtime组合、AI最终两点融合与公开清单登记。日用真实模型、声音/打断、延迟和设备体验仍未验收。

核心提交 `576906ff5267c731bb95068f85d59597bf8648a7` 后，真实MemoryProvider装配初验定位预览遗漏：正常记忆返回不只是Runtime原context，还含“仅为记忆证据”说明、HTML转义与re.sub所需反斜杠保护。新增纯 `project_voice_memory_context` 复现固定正常非管理分支的投影，再交固定Dialogue；不调用query、不创建pending、不改MemoryProvider源码。实际provider输入仍精确比较，后续组合测试负责防止复制规则漂移。初验另修正夹具使用完整原生Message构造器和正式ChatBackend完成路由，未把简化对象异常归咎业务，也未修改生产依赖或真实模型。

后续复核补充后台TTS的狭窄边界：新发声已撤权、但原sentence_id尚未更换时，不能只比较字符串ID。增加单个当前输出句子/epoch绑定，并在队列put和get都校验；旧排队文本/音频在出队时丢弃，后台新生产的旧包在入队时拒绝。队列等待不持取消锁；abort原清队列在锁内执行。绑定只保留当前句子的标识和整数，不累积历史正文/票据。新增测试明确停在尚未提交新chat、sentence_id仍为旧值的空档，验证旧包不可出队、晚包不可重入；合法已归档历史保留。

该补强后的十一文件回归 **283 passed in 15.91s，0 skipped**。Memory投影补丁为 `f9f6d62c58e15c90f134bd2a676567c9645c3e56`。真实组合曾在该补丁后取得十场景68.27s全通过，新增出队门后的最终十一场景将另取得完整结果，不用前次十例替代。

## 第二阶段：真实3.10 RPC、SDK与正式Runtime组合

输出门补丁 `e6450b55ac4c38133eeb581c2d927f144311adac` 后，新增[真实语音客户端夹具](../../../tests/fixtures/voice_proposal_adapter_sdk_client.py)、[真实宿主夹具](../../../tests/fixtures/voice_proposal_adapter_sdk_host.py)及[组合测试](../../../tests/unit/development/test_voice_proposal_adapter_sdk.py)。宿主src/SDK公共合成夹具来自固定AI `ee03aec75c2d6788fb67fd52043385712ef5b18f` Git对象，语音脚本取本树HEAD并校验adapter/prefetch/RPC字节与工作树一致；没有导入AI editable安装或AI脏树。

实际链路为：原小智Python3.10.20解释器 → 固定上游原ASR receive/handle、startToChat、ContextExecutor、原chat/Message/Dialogue/LLM方法 → 实际prefetch与本段adapter → 实际3.10原生RPC → 独立3.12正式security/五种proposal路由 → 真正VoiceProposalHost/Gateway/SQLite计算账本/持久HTTP传输 → 随机回环合成SSE。记忆侧同时运行V既有解释器中的真实SDK2.0.3、Managed/MemoryRuntime与完整ChatBackend；普通prepare/complete/cancel均经正式路由。实际MemoryProvider、AI completion包装和formal_metadata在语音线程执行，不用固定ID或“最近一轮”替身；原Memory基类与日志是可控接口，未加载私有配置。

最终输入真实经过原Dialogue/Message方法、`prepare_voice_dialogue`、`_ObservedLLM`和`web_response`。只替换等待提示的外围计时对象，避免加载声音档案/提示音；未替换消息/工具装配函数。上游LLM实际方法仅用可控SDK stream记录fallback请求；候选供应商才走真实Gateway回环SSE，学校请求0。搜索配置为明确合成对象，任何真实工具执行都在夹具中拒绝；有工具场景保留实际 `[web_search]` 提供能力，仍正常执行原正式回答，不关闭搜索或删工具来命中。

逐场景分阶段检查：候选ready后正式prepare为0、sources.db字节不变、来源journal为空、SDK模拟模型计数不增、semantic后台任务为空、外部HTTP计数0。之后放行真实原端点，原缓冲reset确实执行；正式路由断言只收到提取后的 `检查资料` 正文，并按实际话轮计数恰好一次。供应商实际JSON最后user保留原ASR language/emotion封装，首system包含真实表达/联网说明以及画像1＋事实4＋意图1全部六项。未把标准消息手工传给confirm冒充真实接线。

| 实际组合场景 | 结果 | 候选模型请求 | 正式prepare |
|---|---|---:|---:|
| worker屏障：内部reset完成后才运行chat | adopted | 1 | 1 |
| 最终emotion变化 | null miss，原正式回答 | 1 | 1 |
| 最终speaker变化 | null miss，原正式回答 | 1 | 1 |
| 最终日期说明变化 | null miss，原正式回答 | 1 | 1 |
| 最终角色说明变化 | null miss，原正式回答 | 1 | 1 |
| 最终历史变化 | null miss，原正式回答 | 1 | 1 |
| 正式完整PCM前缀变化 | null miss，完整ASR后原正式回答 | 1 | 1 |
| 实际配置/提供functions | 原正式回答，候选RPC为0 | 0 | 1 |
| 已获得候选、原chat尚未入TTS时取消 | 队列/存储/助手历史均无旧回答 | 1 | 1 |
| 旧worker暂停，新轮先完成，再释放旧worker | 仅新轮输出/助手历史 | 2 | 2 |
| 旧句子已排队，新发声但sentence_id未换 | 旧包不能出队、晚包不能重入，合法历史保留 | 1 | 1 |

最终 **11 passed in 76.80s，0 skipped**。每例都核对实际owned句柄退出、unknown为0、adapter/RPC关闭成功及子进程退出。候选供应商在进入后续屏障前已完整返回，故这里不是新的“上游流中取消”证据；该边界由前段真实宿主header/body取消用例另行覆盖。没有声称外部供应商计算停止。完成回执使用原“playback_acknowledgement=unavailable”语义，只归档本轮合成正式助手文本，不冒充设备播放。

```powershell
$env:LONGMEMORY_TEST_XIAOZHI_ROOT = 'D:/03-项目/01-正式项目/智慧圆屏/local/runtime/xiaozhi-esp32-server'
$env:LONGMEMORY_TEST_PY310 = 'D:/03-项目/01-正式项目/智慧圆屏/local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/.venv/Scripts/python.exe'
$env:LONGMEMORY_TEST_HY_PYTHON = 'D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/v-hy-memory-20261019/local/runtime/hy-memory/.venv/Scripts/python.exe'
$env:LONGMEMORY_TEST_ADAPTER_HOST_REF = 'ee03aec75c2d6788fb67fd52043385712ef5b18f'
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -X utf8 -B -m pytest tests/unit/development/test_voice_proposal_adapter_sdk.py -q
```

解释器只读复用，所有模型替身、SDK库、账本和临时端口均隔离；不安装、下载或复制环境。缺任一显式路径/固定引用时skip，不能当集成通过。stdout/stderr只含状态/计数/脱敏错误位置，无凭据或对话正文。最终字节未修改AI启动入口，仍待AI独立融合这两处接线与真实能力回调、登记公共清单并完成发布回归；本段不能与已冻结core release混同。日用双端仍关闭，真实录音识别质量、学校性能、TTS声音/打断和设备体验未验收。

## AI接入追加：公开启动与真实能力（2026-10-21）

上述“仍待AI融合”是AE当时交付边界。AI以公开启动新增默认关闭的语音开关、实际能力预览回调、`_ObservedLLM`连接私有绑定完成融合。回调不传固定false，不调用工具描述缓存，保留真实搜索/时间；完整公开入口检查与当前固定源码的SDK组合由[AI任务书](AI-hy-advanced-low-latency-20261021.md)单列，不覆盖本文件前段历史结果。

AI审查发现快捷寒暄会绕过原生chat/LLM，因此adapter生命周期现在安装于快捷回复/计时/完成捕获外层，仍在创建连接前；完成捕获后另重套助手历史撤权门，防止固定回复先被捕获再被内层拒绝。原生DTO、真实快捷回复及最终Cosy音频发送包装器使用合成CPU输出验收，无实际TTS/设备播放。确认预算保持0.3秒，并对有界回退增加不含正文的计数与显式阻塞测试。

主会话随后明确授权AI负责backend资源登记，现已按精确name/parameter/reason补入37项；对应[机器可读清单](../../../tests/fixtures/voice_proposal_resource_cases.json)，26个固定上游方法场景＋11个SDK/3.10场景；仅修改backend资源清单，未改workflow/Playwright/前端。该JSON不会参与pytest运行时跳过放行。实际缺资源报告16 passed/37 skipped通过护栏，缺普通依赖仍拒绝。远端新检查与生产开启仍由主会话安排。
