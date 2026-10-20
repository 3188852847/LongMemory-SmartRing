# ADR-0195：受控 Hy 语义派生与任务恢复

日期：2026-10-21。状态：AB 分支实现及隔离软件验证；待主会话组合审查，未部署日用。承接 [ADR-0181](0181-neutral-memory-backend-and-platform-sources.md)、[ADR-0185](0185-verified-hy-management-and-visible-history.md) 与 [ADR-0194](0194-hy-layer-read-only-browsing.md)。接口与证据见 [AB 记录](../development/parallel/AB-hy-l6-l7-20261021.md)。

## 原生语义与问题

固定 `hy-memory==2.0.3`，源提交 `2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed`。安装包 `client.py:evolve/async_evolve` 和 `pipelines/system2_writer.py:evolve` 明确：L6 需 ultra 显式归纳；输入为当前 user/agent 的 VDB 全扫描，操作非幂等，不消费原生后台队列。L7 由 `pipelines/writer.py:_store_intentions` 在 System1 写入 VDB，不依赖 System2。

`pipelines/_retrieval/intention.py:recall_intentions` 会把到期 L7 改为 L2，并 fire-and-forget 删除复本。到期不能证明计划已完成；这些写副作用也不能绕过管理串行证明。原管理证明要求图关闭与后台语义写关闭，不能用于新能力。

## 决定

新增显式 `semantic_layers_enabled` 进程能力，默认 false。开启时必须匹配管理证明协议 2 的精确源指纹、真实 SDK RPC、受控后台写、派生失效及只读意图验收字段。旧证明即使摘要更新也不能开启新能力；不重签已有日用 proof。开关不改变模型/向量/来源持久身份，但重开仍须既有可信空库来源 stamp、引擎和平台来源 owner 租约，以及实际可用的唯一 Kuzu 实例。没有旧 stamp 的已有库不补发。

任务保存在引擎目录 `semantic.sqlite3`，只记录任务 ID、类型、选项、状态、时间、耗时和稳定原因码，不记录提示、模型输出或原话。由同一 owner 的后台线程执行原生 evolve；`max_batches` 限 1–4，默认 1。相同 ID/载荷只认领一次，异载荷拒绝。partial/uncertain 不自动重试；重启 running→uncertain、pending→cancelled，明确新任务才能继续。取消只阻止尚未认领的任务；运行任务不承诺取消、回滚或撤销已经落库的内容。关闭最多等待 2 秒后台线程，仍活动则父进程走既有有界终止，重开保留不确定结果。

普通召回不拿后台工作锁。L6 仅在完整且同一输入代次归纳后注入；任务运行、部分失败、未确认、新事实写入或管理操作均隔离 L6。图式必须重读同范围原生证据才有平台来源；来源不完整不注入。证据 ID 进入既有管理来源叠加与 uncertain 隔离，纠正来源不能丢失。模型归纳、未来意图和用户事实在注入正文中分别标记。

L7 召回复用原生 VDB 搜索、现存向量和纯函数复本分组，不调用原生 mutating intention reader；到期只过滤，复本只在本次结果去重。维护任务把到期项归档，保留 L7 类型，不转成“事情已发生”的事实，不删复本。成功用户 add 后排入确定性维护与归纳任务；取消或未成功投递不由本协调器制造新 add。任务不获得执行权限、设备调度器或主动联系权。

纠正/删除只在后台工作锁可立即取得时可用。写前隔离 L6 代次，范围预检上限 10000；归档同 user/agent/source 的全部 L6、同平台来源的 L7（来源不可证时保守归档），清除同范围 L2/L3 的 `s2_` 派生检查点，再执行既有原生单条管理和独立读回。它是保守派生失效，不是单条 VDB 无副作用声明；用户原话不被改写。SDK delete 仍可能清理目标事实的图引用。中途失败由原管理账本保留 uncertain，L6 不放行；无跨库原子性或自动回滚。只有独立读回及平台 completed 审计后才排入重新归纳；排队失败保留已确认管理与 L6 隔离，不伪称管理回滚。

原生 System2 的遗忘、canonical state、治疗、事实画像提升、特殊画像目录与补充投影显式关闭，避免把后台推断改成用户事实。只接入固定图式归纳及其原生跨域阶段，不以 ultra 模式声明全部实验功能已开启。

Runtime 的写开关需通过内部 `configure_background_writes(write_enabled=…)` 同步；暂停阻止新 add/新任务与未认领任务，已经认领任务不伪称回滚。使用开关仍由平台控制是否调用 recall。HTTP 新任务操作须主会话/AI 接入统一写门后开放，本分支未扩展公共路由白名单。

候选预测使用独立只读快照：调用方提供已有查询向量，只读原生 VDB/图库/画像，不调用 add、公开 search、模型、embedding 或正式 prepare。快照不展开历史版本，管理来源叠加和 uncertain 排除仍保留。返回 HMAC（带密钥的消息认证码）令牌绑定当前 owner、revision/epoch、原生记忆摘要与最多 30 秒有效期；意图到期可进一步缩短有效期。任何前台写尝试或后台任务开始/结束均使 revision 前进，后台写运行时不能取得候选快照，重启换密钥，旧令牌拒绝。校验只在调用时点成立，不创建跨 Runtime 事务或执行授权；AI/AE 在正式采用的同一临界区校验，并与正式话轮实际记忆内容/来源比较。历史或召回策略产生不同支持时丢弃候选，不以 revision 相同替代内容一致。

## 本机问题与代价

本机 Kuzu 0.11.3 不能通过原生窄字符 API 打开中文绝对路径，最小独立复现为 Error 3。同一 worker 工作目录下 ASCII 相对路径可持久重开。采用固定 `cwd=owned_workspace` 与 `sdk/graph`，启动再次核对 cwd，不建联接、不迁移数据、不修改 SDK。Kuzu 的唯一实例与线程池保持原生所有权。

真实隔离栈发现首次后台导入 SciPy BLAS 可停在原生模块加载；初始化主线程预加载已安装的 CPU 聚类依赖后该复现通过。没有安装或升级依赖，没有加载 GPU 模型。预加载成本属于 worker 启动，不声称后台完全无 CPU、存储或 GIL 竞争。

L6 分页只读已有图库，参数下推范围，稳定 ID 排序与 limit+1。若发现旧 VDB L6，明确部分覆盖，不能把图库总数称为全层总数。任意图缺失或来源不完整保留未知；不临时开第二个数据库客户端。基本画像仍沿现有范围证明读取。

查询向量、L7、来源追溯、画像和逐层浏览均使用 SDK 原生 search loop，避免辅助读取回跳正在做 System2 预处理的 write loop。Kuzu/Chroma 仍共用原生单实例和存储执行器，仍可能有短存储竞争。重开完整性清单不把会创建/消失的 Kuzu `.wal` 当作永久必需文件；备份仍须保留当时的整个引擎资源。

## 验证与限制

真实 SDK、Chroma、Kuzu 与新合成库验证了原生归纳、L7 System1 提取、来源、过期、任务重复/重开、后台召回并行和管理派生隔离。模型使用禁网替身；真实模型质量、真实学校调用、日用库向前启用、完整 HTTP/前端组合及圆屏声音/打断均没有由本分支验收。具体命令、数量和接力事项以 AB 记录为准。
