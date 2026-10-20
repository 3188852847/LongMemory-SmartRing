// 合成标准装配；AA 固定目录，无用户数据。来源 SHA-256: a6838309604fe0a703e8e6eac0461b1a287fd3a9e5b7c245266568a479ada5ea
export const mechanismFixture = {
  "schema_version": 1,
  "sdk": {
    "version": "2.0.3",
    "source_commit": "2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed"
  },
  "observed_at": "2026-10-21T02:30:00+00:00",
  "scope": "adapter_declaration_and_runtime_gates",
  "assembly": "standard_worker",
  "mode": "pro",
  "scene": "chat",
  "runtime": {
    "engine_initialized": false,
    "worker_health": "unknown",
    "write_enabled": true,
    "use_enabled": true
  },
  "modes": [
    {
      "id": "lite",
      "title": "lite",
      "description": "仅原始记录与向量写入／检索，不调用提取模型。",
      "selected": false
    },
    {
      "id": "pro",
      "title": "pro",
      "description": "向量与模型提取协调；图开关与 mode 独立。",
      "selected": true
    },
    {
      "id": "ultra",
      "title": "ultra",
      "description": "pro 加可显式触发的 System 2；不是自动开启全部功能。",
      "selected": false
    }
  ],
  "layers": [
    {
      "id": "l0_basic_info",
      "number": 0,
      "title": "基本信息",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "Hy 聚合基本信息；与平台原话来源账本分开。画像读取另受独占范围能力约束。",
      "evidence": [
        "hy_memory/models/memory.py",
        "hy_memory/pipelines/writer.py"
      ],
      "count": null
    },
    {
      "id": "l1_raw",
      "number": 1,
      "title": "原始对话",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "SDK 原始记录追加保存；平台仅投递用户消息，助手正文另行归档。",
      "evidence": [
        "hy_memory/pipelines/writer.py",
        "src/longmemory/methods/hy_memory/method.py"
      ],
      "count": null
    },
    {
      "id": "l2_fact",
      "number": 2,
      "title": "原子事实",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "提取与协调形成事实，支持版本关联；接入不保证每轮都会产出。",
      "evidence": [
        "hy_memory/pipelines/writer.py"
      ],
      "count": null
    },
    {
      "id": "l3_summary",
      "number": 3,
      "title": "会话摘要",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "固定版支持摘要类型；当前是否产出、可选摘要增强是否启用未观测。",
      "evidence": [
        "hy_memory/pipelines/writer.py",
        "hy_memory/pipelines/reader_base.py"
      ],
      "count": null
    },
    {
      "id": "l4_identity",
      "number": 4,
      "title": "身份画像（历史兼容）",
      "sdk_support": "reserved",
      "integration": "reserved",
      "description": "新提取不再写此层；旧类型可读，不能当作基本信息聚合。",
      "evidence": [
        "hy_memory/pipelines/writer.py"
      ],
      "count": null
    },
    {
      "id": "l5_knowledge",
      "number": 5,
      "title": "知识层（保留）",
      "sdk_support": "reserved",
      "integration": "reserved",
      "description": "固定版枚举保留，不能把实体标签或关系存储直接称为已实现 L5。",
      "evidence": [
        "hy_memory/models/memory.py"
      ],
      "count": null
    },
    {
      "id": "l6_schema",
      "number": 6,
      "title": "图式／心智模型",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "System 2 图式归纳有实现；标准装配 pro 且图与后台队列关闭。",
      "evidence": [
        "hy_memory/pipelines/system2_agent.py",
        "src/longmemory/methods/hy_memory/worker.py"
      ],
      "count": null
    },
    {
      "id": "l7_intention",
      "number": 7,
      "title": "前瞻意图",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "固定版支持意图；标准装配关闭提取、图与意图缓存，不接主动调度。",
      "evidence": [
        "hy_memory/models/memory.py",
        "src/longmemory/methods/hy_memory/worker.py"
      ],
      "count": null
    }
  ],
  "mechanisms": [
    {
      "id": "system1",
      "group": "processing",
      "title": "System 1：写入与召回",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "pro 路径接入模型提取与默认召回；运行开关和预算仍可阻止执行。",
      "evidence": [
        "hy_memory/client.py",
        "src/longmemory/methods/hy_memory/sdk_bridge.py"
      ],
      "endpoints": []
    },
    {
      "id": "system2",
      "group": "processing",
      "title": "System 2：认知加工",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "ultra 可显式 evolve/sweep；本平台不接入调用且标准装配关闭队列。",
      "evidence": [
        "hy_memory/client.py",
        "hy_memory/pipelines/system2_agent.py",
        "src/longmemory/methods/hy_memory/worker.py"
      ],
      "endpoints": []
    },
    {
      "id": "extraction",
      "group": "write",
      "title": "原文、提取与冲突协调",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "用户来源先归档再投递 Hy；组合流程可能部分提交，不提供逐项 ADD/UPDATE 决策轨迹。",
      "evidence": [
        "hy_memory/pipelines/writer.py",
        "src/longmemory/methods/hy_memory/method.py"
      ],
      "endpoints": [
        "/api/memory-engine/sources/{event_id}"
      ]
    },
    {
      "id": "version_chain",
      "group": "write",
      "title": "事实演化与可见版本",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "SDK 演化链与独立 history 不同；平台核对召回可见版本来源和不确定管理状态。",
      "evidence": [
        "src/longmemory/methods/hy_memory/sdk_bridge.py",
        "src/longmemory/methods/hy_memory/method.py"
      ],
      "endpoints": [
        "/api/memory-engine/items/{item_id}"
      ]
    },
    {
      "id": "sdk_history",
      "group": "write",
      "title": "SDK 历史记录",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "标准装配 history.enable=false；空历史不证明从未变化。",
      "evidence": [
        "src/longmemory/methods/hy_memory/worker.py",
        "src/longmemory/methods/hy_memory/administration.py"
      ],
      "endpoints": [
        "/api/memory-engine/hy/items/{item_id}/history"
      ]
    },
    {
      "id": "vector_store",
      "group": "storage",
      "title": "持久向量存储",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "标准 worker 使用本地 Chroma；此端点不探测文件、不读取条目数量。",
      "evidence": [
        "src/longmemory/methods/hy_memory/worker.py"
      ],
      "endpoints": [
        "/api/memory-engine/items"
      ]
    },
    {
      "id": "graph_store",
      "group": "storage",
      "title": "关系图存储",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "固定版有图存储；标准配置 enable_graph=false，图路径配置不代表已创建或启用。",
      "evidence": [
        "hy_memory/config.py",
        "src/longmemory/methods/hy_memory/worker.py"
      ],
      "endpoints": []
    },
    {
      "id": "normal_recall",
      "group": "recall",
      "title": "普通召回",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "固定 scene=chat、search_mode=default，按当前用户／助手／来源隔离。此处不会执行 search。",
      "evidence": [
        "src/longmemory/methods/hy_memory/sdk_bridge.py"
      ],
      "endpoints": []
    },
    {
      "id": "profile_recall",
      "group": "recall",
      "title": "基本画像补充",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "include_profile 决定是否另读基本画像；管理查看画像还须 workspace 的独占范围证明。",
      "evidence": [
        "src/longmemory/methods/hy_memory/method.py",
        "src/longmemory/methods/hy_memory/sdk_bridge.py",
        "src/longmemory/methods/hy_memory/administration.py"
      ],
      "endpoints": [
        "/api/memory-engine/hy/workspace",
        "/api/memory-engine/hy/profile"
      ]
    },
    {
      "id": "schema_recall",
      "group": "recall",
      "title": "schema 检索通道",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "SDK 原生返回通道之一；平台 schema_limit=0 且不将该通道注入答案。",
      "evidence": [
        "src/longmemory/methods/hy_memory/sdk_bridge.py",
        "src/longmemory/methods/hy_memory/method.py"
      ],
      "endpoints": []
    },
    {
      "id": "proactive_recall",
      "group": "recall",
      "title": "proactive 检索通道",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "SDK 原生通道之一；平台 intention_limit=0 且不注入该通道，不等于主动联系。",
      "evidence": [
        "src/longmemory/methods/hy_memory/sdk_bridge.py",
        "src/longmemory/methods/hy_memory/method.py"
      ],
      "endpoints": []
    },
    {
      "id": "answer_injection",
      "group": "recall",
      "title": "实际回答上下文构建",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "适配器只组合 normal 与可选画像；排除管理未确认条目及受影响可见版本链。未存逐答完整注入轨迹。",
      "evidence": [
        "src/longmemory/methods/hy_memory/method.py"
      ],
      "endpoints": []
    },
    {
      "id": "query_rewrite",
      "group": "recall",
      "title": "查询改写",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "标准装配显式关闭；未接 agentic search。",
      "evidence": [
        "src/longmemory/methods/hy_memory/worker.py",
        "src/longmemory/methods/hy_memory/sdk_bridge.py"
      ],
      "endpoints": []
    },
    {
      "id": "recall_strength",
      "group": "recall",
      "title": "强度重排与访问回写",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "标准装配 strength/access_tracking 显式关闭；其他环境可选召回增强未在此探测。",
      "evidence": [
        "src/longmemory/methods/hy_memory/worker.py"
      ],
      "endpoints": []
    },
    {
      "id": "optional_recall_enhancements",
      "group": "recall",
      "title": "可选情景／实体／层次增强",
      "sdk_support": "implemented",
      "integration": "unknown",
      "description": "下列 episode、entity、bundle、rerank 等为独立可选机制；没有 worker 有效配置快照，不能推定启用。",
      "evidence": [
        "hy_memory/config.py"
      ],
      "endpoints": []
    },
    {
      "id": "reader_dispatch",
      "group": "recall",
      "title": "legacy／hybrid 读取器",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "SDK 可选择向量候选或向量＋BM25 候选；标准子进程固定 HY_MEMORY_READER=legacy。写入协调候选融合是另一机制。",
      "evidence": [
        "hy_memory/pipelines/reader.py",
        "src/longmemory/methods/hy_memory/process_client.py"
      ],
      "endpoints": []
    },
    {
      "id": "reconcile_candidates",
      "group": "write",
      "title": "协调候选融合与去重",
      "sdk_support": "implemented",
      "integration": "unknown",
      "description": "固定版写入协调支持向量、BM25、标签／实体候选加成与协调决策；具体分支和命中未记录，不等同开启 hybrid reader。",
      "evidence": [
        "hy_memory/pipelines/_retrieval/reconcile_retrieval.py",
        "hy_memory/pipelines/writer.py"
      ],
      "endpoints": []
    },
    {
      "id": "episode_memory",
      "group": "recall",
      "title": "情景归组与摘要回忆",
      "sdk_support": "implemented",
      "integration": "unknown",
      "description": "包含跨批次 episode、显式 session finalize、动态／系列情景、摘要、胶囊和成员展开。平台没有 finalize 入口，不能从有 L3 类型推定这些增强启用。",
      "evidence": [
        "hy_memory/config.py",
        "hy_memory/pipelines/writer.py",
        "hy_memory/pipelines/_retrieval/session_episode.py"
      ],
      "endpoints": []
    },
    {
      "id": "entity_tag_recall",
      "group": "recall",
      "title": "实体／标签候选增强",
      "sdk_support": "implemented",
      "integration": "unknown",
      "description": "实体 collection、NER、标签索引及动态实体标签向量有独立配置；图关闭不等于所有标签机制关闭。未观测当前有效分支。",
      "evidence": [
        "hy_memory/config.py",
        "hy_memory/pipelines/_retrieval/entity_store.py",
        "hy_memory/pipelines/_retrieval/tag_index.py"
      ],
      "endpoints": []
    },
    {
      "id": "hierarchy_bundles",
      "group": "recall",
      "title": "层次与多种子回忆组合",
      "sdk_support": "implemented",
      "integration": "unknown",
      "description": "支持 hierarchy bundle、multi-seed bundle 和系列时间线等候选组合；未观测配置或真实组合结果。",
      "evidence": [
        "hy_memory/config.py",
        "hy_memory/pipelines/_retrieval/hierarchy_bundle.py",
        "hy_memory/pipelines/_retrieval/multi_seed_bundle.py"
      ],
      "endpoints": []
    },
    {
      "id": "local_rerank",
      "group": "recall",
      "title": "局部交叉编码重排",
      "sdk_support": "implemented",
      "integration": "unknown",
      "description": "SDK 可对共享候选池使用独立 cross-encoder；不等同本地 BGE 向量化，本平台未核有效开关或模型加载。",
      "evidence": [
        "hy_memory/pipelines/_retrieval/local_rerank.py",
        "hy_memory/config.py"
      ],
      "endpoints": []
    },
    {
      "id": "temporal_recall",
      "group": "recall",
      "title": "事件时间过滤与日期视图",
      "sdk_support": "implemented",
      "integration": "not_integrated",
      "description": "SDK created_after 优先事件 memory_at、未知回退落库时间；还支持日期视图。平台未传时间过滤参数，也未接 agentic 时间范围解析；不探测底层内部加权。",
      "evidence": [
        "hy_memory/pipelines/_retrieval/temporal.py",
        "hy_memory/pipelines/_retrieval/date_view.py",
        "src/longmemory/methods/hy_memory/sdk_bridge.py"
      ],
      "endpoints": []
    },
    {
      "id": "result_shaping",
      "group": "recall",
      "title": "融合、去重与配额格式化",
      "sdk_support": "implemented",
      "integration": "unknown",
      "description": "固定 reader 有 RRF／评分、去重、多样性、候选护栏及配额和版本链格式化。具体生效分支、分数与裁剪未被本接口观测。",
      "evidence": [
        "hy_memory/pipelines/reader_base.py",
        "hy_memory/pipelines/_retrieval/rrf.py",
        "hy_memory/pipelines/_retrieval/dedup.py"
      ],
      "endpoints": []
    },
    {
      "id": "retrieval_clauses",
      "group": "recall",
      "title": "检索子句",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "固定版支持为召回生成检索子句；标准装配显式关闭 retrieval_clauses。",
      "evidence": [
        "src/longmemory/methods/hy_memory/worker.py",
        "hy_memory/pipelines/_retrieval/retrieval_clauses.py"
      ],
      "endpoints": []
    },
    {
      "id": "supplemental_propositions",
      "group": "recall",
      "title": "补充命题增强",
      "sdk_support": "implemented",
      "integration": "unknown",
      "description": "固定版另有补充命题机制；有效配置未观测，不因检索子句关闭而推定此项状态。",
      "evidence": [
        "hy_memory/config.py",
        "hy_memory/pipelines/_retrieval/supplemental_propositions.py"
      ],
      "endpoints": []
    },
    {
      "id": "schema_evolution",
      "group": "evolution",
      "title": "图式归纳与演进",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "固定版存在 forming/stable/evolving 等图式状态；当前 pro／图关闭，不提供图浏览。",
      "evidence": [
        "hy_memory/models/memory.py",
        "hy_memory/pipelines/system2_agent.py"
      ],
      "endpoints": []
    },
    {
      "id": "intention_extraction",
      "group": "evolution",
      "title": "意图提取与触发",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "标准配置 enable_intention=false、意图缓存关闭；不创建提醒或后台任务。",
      "evidence": [
        "src/longmemory/methods/hy_memory/worker.py"
      ],
      "endpoints": []
    },
    {
      "id": "intention_lifecycle",
      "group": "evolution",
      "title": "意图过期转事实与复本处理",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "固定 reader 的意图通道可惰性把过期 L7 转 L2、去重并异步删除复本，检索可能写状态。本装配关闭意图且 limit=0，本页面绝不运行检索验证。",
      "evidence": [
        "hy_memory/pipelines/_retrieval/intention.py",
        "src/longmemory/methods/hy_memory/sdk_bridge.py"
      ],
      "endpoints": []
    },
    {
      "id": "cross_domain_sweep",
      "group": "evolution",
      "title": "跨域图式归纳",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "ultra evolve 末尾可将 basic 图式抽象、聚类并形成 core 图式；当前 pro 不接 evolve/sweep。",
      "evidence": [
        "hy_memory/pipelines/cross_domain_sweeper.py",
        "hy_memory/client.py"
      ],
      "endpoints": []
    },
    {
      "id": "ultra_persona_catalog",
      "group": "evolution",
      "title": "均衡画像目录与具体事实补充",
      "sdk_support": "implemented",
      "integration": "disabled",
      "description": "固定版 ultra 可从精确 L2 生成特殊 L6 目录与补充，保留证据并附入可见 L0 链；pro 不启用这条路径，不能称为当前画像。",
      "evidence": [
        "hy_memory/pipelines/balanced_catalog.py",
        "hy_memory/pipelines/specific_supplement.py"
      ],
      "endpoints": []
    },
    {
      "id": "memory_lifecycle",
      "group": "evolution",
      "title": "记忆生命周期与遗忘边界",
      "sdk_support": "implemented",
      "integration": "unknown",
      "description": "固定模型区分 active/superseded/negated/conflicted/shadow/archived；状态变化的当前数量未知。rolling-delete 仅查到配置声明，未证实执行入口，不承诺自动清理或隐私擦除。",
      "evidence": [
        "hy_memory/models/memory.py",
        "hy_memory/config.py"
      ],
      "endpoints": []
    },
    {
      "id": "working_route",
      "group": "routing",
      "title": "working 工作场景",
      "sdk_support": "implemented",
      "integration": "not_integrated",
      "description": "固定版支持工具 trace 产生会话事实与跨会话可复用经验，分别协调后互链；有独立存储与项目范围。平台只归档文本并固定 chat，未接工具 trace 或工作场景。",
      "evidence": [
        "hy_memory/client.py",
        "hy_memory/coding/writer.py",
        "hy_memory/coding/types.py",
        "src/longmemory/methods/hy_memory/sdk_bridge.py"
      ],
      "endpoints": []
    },
    {
      "id": "coding_route",
      "group": "routing",
      "title": "coding 代码场景",
      "sdk_support": "implemented",
      "integration": "not_integrated",
      "description": "固定版沿双层事实／经验路径，另有版本演化 diff 链，在代码事实后附原话与修改版本；支持 workspace／branch 范围。标准 coding.enable=false，不采集代码或调用工具。",
      "evidence": [
        "hy_memory/client.py",
        "hy_memory/coding/chain_store.py",
        "src/longmemory/methods/hy_memory/worker.py"
      ],
      "endpoints": []
    },
    {
      "id": "automatic_routing",
      "group": "routing",
      "title": "自动场景分类与 agentic 检索",
      "sdk_support": "implemented",
      "integration": "not_integrated",
      "description": "SDK 可按工具轨迹分 chat/working/coding；agentic 检索合并分类、改写和时间解析。平台显式 chat/default，不触发这些模型路由。",
      "evidence": [
        "hy_memory/client.py",
        "hy_memory/coding/judge.py",
        "src/longmemory/methods/hy_memory/sdk_bridge.py"
      ],
      "endpoints": []
    },
    {
      "id": "scope_isolation",
      "group": "management",
      "title": "用户／助手／会话／来源隔离",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "平台投递保留会话元数据，检索限定当前用户、助手和来源命名空间，跨会话共享长期空间。workspace/branch 仅 Working/Coding 支持，当前未接。",
      "evidence": [
        "src/longmemory/methods/hy_memory/sdk_bridge.py",
        "hy_memory/client.py"
      ],
      "endpoints": []
    },
    {
      "id": "administration",
      "group": "management",
      "title": "查看、纠正与单条删除",
      "sdk_support": "platform",
      "integration": "configured",
      "description": "真实可执行能力以 workspace 为准；受启动权限、运行写开关、独占证明与修订检查共同约束，非原生原子 CAS。",
      "evidence": [
        "src/longmemory/methods/hy_memory/administration.py"
      ],
      "endpoints": [
        "/api/memory-engine/hy/workspace",
        "/api/memory-engine/items"
      ]
    },
    {
      "id": "source_trace",
      "group": "management",
      "title": "来源与平台处理状态",
      "sdk_support": "platform",
      "integration": "configured",
      "description": "按条目可得来源 ID 回看平台原话和投递状态；无来源时保留未知，不从正文猜测。",
      "evidence": [
        "src/longmemory/methods/hy_memory/source_evidence.py",
        "src/longmemory/methods/hy_memory/administration.py"
      ],
      "endpoints": [
        "/api/memory-engine/sources/{event_id}"
      ]
    },
    {
      "id": "management_audit",
      "group": "management",
      "title": "管理审计与不确定隔离",
      "sdk_support": "platform",
      "integration": "configured",
      "description": "平台 running/completed/uncertain 审计独立于 SDK history；读回不确定不自动重试，无自动解锁入口。",
      "evidence": [
        "src/longmemory/methods/hy_memory/administration.py",
        "src/longmemory/methods/hy_memory/method.py"
      ],
      "endpoints": [
        "/api/memory-engine/hy/operations"
      ]
    },
    {
      "id": "persistence",
      "group": "runtime",
      "title": "持久化、重开与所有权",
      "sdk_support": "platform",
      "integration": "configured",
      "description": "引擎目录与平台来源分离，独占租约与身份校验由装配负责；本次只读取初始化标记，不验证磁盘或重启。",
      "evidence": [
        "src/longmemory/methods/hy_memory/assembly.py"
      ],
      "endpoints": []
    },
    {
      "id": "cache_and_tasks",
      "group": "runtime",
      "title": "缓存与后台任务队列",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "标准缓存后端为 SQLite，画像缓存／System2队列／意图缓存关闭；写记录等其他细节未观测。存在缓存文件不能证明有后台任务执行。",
      "evidence": [
        "hy_memory/config.py",
        "src/longmemory/methods/hy_memory/worker.py"
      ],
      "endpoints": []
    },
    {
      "id": "observability",
      "group": "runtime",
      "title": "SDK 与平台可观测性",
      "sdk_support": "platform",
      "integration": "configured",
      "description": "标准 worker 关闭 SDK metrics/debug/流水线 trace；平台有安全分段计时和管理审计，但没有完整可回放的逐写决策或逐答注入证据接口。",
      "evidence": [
        "src/longmemory/methods/hy_memory/worker.py",
        "src/longmemory/methods/hy_memory/process_client.py",
        "src/longmemory/methods/hy_memory/observation.py"
      ],
      "endpoints": [
        "/api/memory-engine/hy/operations"
      ]
    },
    {
      "id": "shared_runtime",
      "group": "runtime",
      "title": "SDK 多客户端共享运行时",
      "sdk_support": "implemented",
      "integration": "not_integrated",
      "description": "固定版有跨 client 共享事件循环／缓存／指标基础设施；当前适配器拥有独立 SDK 子进程，不暴露多客户端共享入口。",
      "evidence": [
        "hy_memory/runtime.py",
        "src/longmemory/methods/hy_memory/process_client.py"
      ],
      "endpoints": []
    },
    {
      "id": "provider_endpoints",
      "group": "runtime",
      "title": "模型与向量服务边界",
      "sdk_support": "implemented",
      "integration": "configured",
      "description": "标准装配显式注入 OpenAI 兼容模型／向量端点与预算网关，离线模式拒绝外网；本接口不返回模型名、地址、凭据或预算账本。",
      "evidence": [
        "src/longmemory/methods/hy_memory/worker.py",
        "src/longmemory/methods/hy_memory/settings.py",
        "src/longmemory/methods/hy_memory/model_gateway.py"
      ],
      "endpoints": []
    },
    {
      "id": "embedding_override",
      "group": "runtime",
      "title": "逐调用向量端点覆盖",
      "sdk_support": "implemented",
      "integration": "not_integrated",
      "description": "固定 SDK 支持逐调用 embed_override；平台固定可信装配，不接受页面指定向量端点或密钥。",
      "evidence": [
        "hy_memory/client.py",
        "src/longmemory/methods/hy_memory/sdk_bridge.py"
      ],
      "endpoints": []
    },
    {
      "id": "storage_backends",
      "group": "storage",
      "title": "可替换持久存储后端",
      "sdk_support": "implemented",
      "integration": "not_integrated",
      "description": "SDK 有其他向量／图／缓存后端选择；本平台固定 Chroma＋SQLite、图关闭，不加载或部署其他后端。",
      "evidence": [
        "hy_memory/config.py",
        "src/longmemory/methods/hy_memory/worker.py"
      ],
      "endpoints": []
    },
    {
      "id": "platform_proactive",
      "group": "runtime",
      "title": "平台主动联系",
      "sdk_support": "platform",
      "integration": "not_integrated",
      "description": "Hy 新后端暂停旧主动交流，不把 SDK proactive 通道当作设备调度器。",
      "evidence": [
        "src/longmemory/application/memory_runtime.py"
      ],
      "endpoints": []
    }
  ],
  "evidence_gaps": [
    "各层数量未知；此端点不扫描或全库计数。",
    "未探测 worker 健康、有效环境配置或最近成功调用时间。",
    "缺少逐项写入／冲突决策记录；SDK history 当前关闭。",
    "缺少已持久保存的逐次召回与最终回答注入证据接口；不现场 search 制造轨迹。",
    "列表仅提供当前活动条目，不支持服务端正文搜索或按层过滤；图浏览未接入。"
  ]
};
