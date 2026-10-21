# ADR-0202：首次检索细分观测的显式协商

日期：2026-10-21。状态：**ROOT已批准独立v2方案与最小实现；隔离软件验证完成，待AI审查，未部署。** 基线 `c74b88834683080d4dc4ee4b770f48707ff5b349`。接续 [ADR-0201](0201-composed-runtime-write-gates-and-observation.md)；冻结历史见 [设计记录](../development/parallel/AB-first-recall-observation-design-20261021.md)，当前实现与限制见 [实施记录](../development/parallel/AB-first-recall-observation-implementation-20261021.md)。

## 问题与已有事实

当前 `memory_request_timing.observation` 是version=1、trace_id、stages三字段结构，阶段和值均严格白名单。服务端 `observation.valid_snapshot` 和小智 `longmemory_provider._observation_header` 遇未知stage都拒绝整个包。因此把新阶段直接塞进v1不是安全的兼容扩展，可能连原有基础计时一起丢失。只增加新请求头、仍返回扩大后的v1，也没有清楚区分语义版本。

本轮慢请求的总时长不能证明唯一冷启动原因。本决定只增加可审查的测量契约，不预热、搜索或读取个人记忆，不改变预算、提取、归档、完成、取消、L6/L7或声音链路。

## 决定：保留v1，另行请求独立v2详情

基础请求仍为 `X-Memory-Observe: 1`。响应的 `X-Memory-Observation` 永远保留基线v1阶段集合、原字段形状和数值语义；不混入任何新阶段，不扩必填字段，不变更业务响应JSON或状态码。

新版客户端只在原有合法观测条件已满足时，再发送可选 `X-Memory-Observe-Detail: 2`。新版服务端确认请求、匿名关联和内部能力后，可额外返回 `X-Memory-Observation-Detail`。这个独立包使用version=2、同一trace_id和新阶段stages字典；全部阶段都是可选测量项。它是**观测详情v2**，不改变现有memory_protocol=2或话轮业务版本。

旧版没有详情头，不能被解释成空详情成功或全部0。新版客户端保留原有v1基础记录不变，另输出固定的 `memory_request_detail` 旁路记录：version=2、round_id、state、observation。state仅为received、unavailable或invalid。received只说明独立v2包合法收到，不证明所有阶段都执行；缺阶段一律为未观测，不能填0或猜是缓存命中。基础记录不增加必填字段。

没有基础观测请求、没有合法关联、不支持的详情版本或内部能力不足，均不主动开启详情。详情解析失败只影响独立详情记录，不能吞掉合法基础包、改变答案或触发重试；不得回显坏header、异常正文或任意未知字段。

| 客户端 → 服务端 | 基础响应 | 详情响应/客户端结果 |
|---|---|---|
| 旧 → 旧 | 原v1 | 无详情，保持现状 |
| 旧 → 新 | 与旧服务相同的v1包 | 不发送v2，不默认开启新采集 |
| 新 → 旧 | 原v1，照常解析与保留 | 另记unavailable、observation=null，不影响基础包 |
| 新 → 新，明确请求2且支持 | 原v1 | 独立v2；另记received，缺阶段不填0 |
| 新 → 新，坏详情/异轮/未知阶段 | 合法v1仍保留 | 详情invalid、observation=null，不记录坏原文 |

固定合成头与客户端结果见 [三向回执](../development/parallel/AB-first-recall-observation-examples-20261021.json)。里面的数值是示例输入，不是性能实测，也不能用来解释真实5.4秒。

## 内部进程与网关边界

详情采集默认关闭，不能仅因存在普通Observation就开启。worker initialize结果增加可选 `observation_detail_versions: [2]` 能力声明，且仅在固定SDK观测钩子已应用时声明；旧结果缺省或未知版本视为不支持，新父进程不向未声明支持的worker开启详情。不可变c74父进程与新版worker、旧能力回执与新版父进程的混合版本测试已通过。

显式协商后，SDK RPC才能增加可选详情请求标记，并在原有v1 observation之外返回独立v2 observation_detail；API不能因自己认识版本2就凭空补出worker详情。未知SDK指纹/未应用观测钩子时保持基础行为，明确详情缺失，不签发成功采集声明。

embedding网关同理：只在既有可信回环、已认证请求且启用详情时传原有匿名关联和详情版本；旧网关忽略新增可选头、业务照常。新版网关返回独立v2详情头。无头或坏头不补零、不改变embedding结果或预算。此方案不建立新的控制接口，不接收任意URL，不向供应商转发观测头。

## 测量点

| v2固定阶段名 | 真实边界与限制 |
|---|---|
| embed_client_get_ms | 固定SDK的EmbedService._get_client整个调用，包含缓存查找及可能的客户端/transport构造；calls不是“新建客户端数量” |
| embed_http_headers_ms | SDK自有transport发送至收到响应头；不声称包含完整响应体解析 |
| embed_gateway_ms | 网关embed函数整体；不包含读取HTTP正文和写出响应 |
| embed_gateway_lock_wait_ms | 进入现有_embedding_lock的实际等待，不改变锁或优先级 |
| embed_bge_encode_ms | 原encode_query/encode_documents调用；不加载新模型，不记录输入或向量 |
| vdb_query_pool_wait_ms | 提交既有VDB执行器至实际查询callback进入；是队列/调度等待，不是Rust索引锁测量 |
| vdb_query_backend_ms | 原collection.query callback执行；包含后端内部等待/I/O，无法再声称拆出了Rust锁 |

原v1 embed_rpc_ms、vdb_query_ms和sdk_search_ms继续保留。这些是嵌套边界，不能直接相加当作总耗时。保留原执行器、调用次数和取消策略；取消时只记录已实际发生的边界，未完成的后端耗时缺省，不虚构0或迟到补写到另一轮。错误/取消传播和业务副作用须在实现后另验，合成契约模型不能代替真实链路证明。

测点位置以c74与所有者固定SDK 2.0.3为准：

| 位置 | 拟包装边界 |
|---|---|
| SDK `hy_memory/core/embed_service.py:EmbedService._get_client` | 在仓库sdk_observation.py内按固定源码指纹包装，不改已安装SDK |
| `src/longmemory/methods/hy_memory/worker.py:BoundedTransport.handle_async_request` | 仅既有受控embedding端点，底层transport调用返回响应头或抛异常时结束；不把请求失败写成成功拿到响应 |
| `src/longmemory/methods/hy_memory/model_gateway.py:ModelGateway.embed` | 现有_embedding_lock进入前后及encode_query/encode_documents原调用，保持锁和业务计数位置 |
| SDK `hy_memory/data/vector_store_chroma.py:ChromaVectorStore.search` / `_run_in_vdb_pool` | 仓库sdk_observation.py包装实际查询callback；沿用utils/async_executor.py原执行器/屏蔽取消行为，不替换调度器 |
| `src/longmemory/entrypoints/api/routes/memory_runtime.py:prepare` | 只协商并序列化独立header，不新增业务准备模式 |
| `scripts/development/xiaozhi/longmemory_provider.py:_runtime_request` / `_observation_header` | v1解析保持，新版另解析/记录v2；不修改共享消费副本 |

误差边界：毫秒沿用三位小数量化，0.001ms是输出粒度而不是准确度保证。pool等待含提交及Python包装开销，backend含原生内部等待/I/O；网关函数不含完整HTTP收发，HTTP头边界不含完整body解析。跨进程只比较各自elapsed，不相减绝对时钟。已补同规模轻量合成开/基础/详情对照，结果与范围见 [开销回执](../development/parallel/AB-first-recall-observation-overhead-20261021.json)：详情比基础的每次调用中位数多11.671微秒。该探针不含真实SDK/HTTP/IPC/BGE，不能作为生产开销保证，**数值误差上限仍未确定**。Rust内部锁等待仍不可分离。

## 隐私与部署守卫

只允许固定阶段名、calls与有限非负total_ms，沿用既有匿名轮次关联；不新增真实用户/设备/来源身份、问题、回答、记忆正文、令牌、私有路径或原始header。单包上限4096字符；v1与v2分别严格校验，两包header值合计也沿用4096预算，超额只舍弃详情、保留基础包。RPC沿用原MAX_LINE=2,000,000；可选详情标记或回包超额时先去掉详情，不扩大业务上限。未知、异轮、非有限值和额外字段均不透传。

小智消费的是安装后的provider副本，不是本仓库源码自动热更新。主会话已核验的当前自有副本SHA256为 `7241a12e6fe9d8c250245cf781167555c7df53375ef643bc02ebcaf1a18240e9`。本阶段不读取/修改该副本，也不改setup升级白名单。后续部署v2时，AI必须核对原字节、最终目标字节和回退件，再显式审计版本升级：已批准旧hash才可升级；目标已相同必须幂等不写；unknown必须拒绝，不能用路径或文件名推断所有权。不要重复此前版本接力时遗漏已批准来源的部署问题。

## preset建议独立保留

严格preset目前先决定答案、再等待memory.query_memory；检索正文不进入该固定答案，但查询还负责原话归档、预算暂停通知、turn_id/receipt及完成/取消关联。未来可单独设计语音适配层“准备轮次但不检索”能力，必须保留这些职责、写入开关和延后派生预算、声线/角色作用域及TTS撤权生命周期；不扩现有词表，不泛化跳过带问题/回忆的招呼，不在Memory Core加入终端判定，不提供任意skip_recall或新增prepare_only接口。本阶段不实现。

## 本轮验收范围

设计冻结提交 `3739d8857b35c3dc54b631e7a9d5e83f1c11a0dd` 只含参考fixture与合成契约；旧v1草稿备份保留。ROOT后续明确批准最小落地，现已实现独立v2并完成真实SDK＋本地替身网关首次召回、原SDK执行器正常/异常/排队及运行中取消、实际API路由、新旧协商和provider升级临时副本测试。软件证据不等于日用验收；本轮不合main、不推送、不部署、不重签日用proof，不修改共享配置、SDK或已安装provider。完整结果及未验收范围见实施记录。
