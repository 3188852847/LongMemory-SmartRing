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
