# Hy 逐层真实内容只读契约

日期：2026-10-21。锁定 `hy-memory==2.0.3`、源提交 `2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed`。本轮解决每层实际内容浏览；不以机制说明或平台原话冒充 SDK 记录，不开启写入、图、System2或模型。

## 前端接口

按用户点层请求，不在总览/聊天后台预取全层。

| GET | 参数与结果 |
|---|---|
| `/api/memory-engine/hy/layers/{layer}` | `layer` 仅八个原生值：l0_basic_info/l1_raw/l2_fact/l3_summary/l4_identity/l5_knowledge/l6_schema/l7_intention。查询仅 `limit`（默认20，1–50）、`offset`（默认0，0–10000）、`state`（默认all；all/active/superseded/negated/conflicted/shadow/archived）。返回下述页面。 |
| `/api/memory-engine/hy/layers/{layer}/items/{item_id}` | 无查询/body。普通ID读取同层同范围真实记录；L0的固定 `profile` ID读取聚合，L0实际版本ID可读取对应原生记录。不得把聚合交给普通get/update。 |

页面字段：`schema_version:1`、`layer`、`sdk_support`（implemented/historical/reserved）、`generation_state`（configured/disabled/historical/reserved/unknown，仅装配声明）、`read_status`（readable/partial/unavailable）、`data_state`（present/empty/unknown）、`coverage`（vdb_complete/vdb_only_graph_unopened/unavailable）、`reason_code`（null或稳定原因）、`items`、`limit/offset/state`、`has_more`（布尔或null）、`total`（整数或null）、`count_scope`、`observed_at`。空页不一定是空层；未打开图、缺画像范围证明、超聚合上限均不是空数据。`observed_at` 是读取完成时刻，不是最后写入/健康时刻。

普通记录：`item_id/native_id`、`kind:"stored_record"`、`layer`、`content`、`content_chars`、`content_truncated`、`status`、`is_latest`、`recorded_at/memory_at/valid_from/valid_until`（ISO UTC或null）、`supersedes/superseded_by`（各最多16个ID）、`version_links_limited`、`source_event_ids`（最多16个可证明ID或null）、`source_raw_memory_id`。列表正文最多1024字符，详情32768字符，截断显式标注；L0详情的版本摘要为512字符、各4个演化关联、最多8个来源，超来源上限返回null，不冒充完整来源。不返回embedding、custom任意字段、用户/agent/session/来源内部标识、路径、私有提示或凭据。未知时间不补造。

L0聚合：`item_id:"profile"`、`kind:"aggregate_profile"`，`native_id`为实际链头，不表示可用普通管理操作；`basic_info`、`field_sources`（当前字段可得来源）、`stored_version_count`。详情 `{schema_version,layer,item,versions}`：L0聚合的versions为有界原生版本摘要；普通详情versions为null，不假造展开历史。L0不适用state筛选，只接受all；聚合显示SDK完整字段合并算法的结果，而非链头diff。固定SDK合并全部版本按时间覆盖，不只active/latest；字段来源使用同一排序及值核对，null/空字段在basic_info保留而SDK渲染省略。若历史超过128条或字段超过64个（键128字符、值2048字符）则unavailable，不输出伪完整聚合。

计数：普通页只取原生 `limit+1` 条，无全层计数。仅能从非空末页或首末同页证明准确总数时给整数，其他为null，`count_scope="owner_agent_source_layer_state_vdb"`；图库未打开时total始终null。L0 complete聚合total为0或1，`count_scope="aggregate_profile"`，并另给实际已完整读取的版本数；它不是L0存储行数。分页是当前拥有者原生存储顺序，不作全库时间排序，不保证跨请求冻结快照；刷新/写入可改变后续页。

## 各层实际读取支持

| 层 | 只读内容和范围 | 不可推定 |
|---|---|---|
| L0 | 固定版user-level基本信息；须已有可信空库范围stamp和拥有者租约。最多读取129条判定聚合上限，校验每版本user/允许agent及namespace meta，使用SDK的纯KV合并/head选择/渲染函数。不调用SDK profile的额外图查询/追溯扫描。 | 缺stamp或历史不完整不是空；不跨其他agent/source补字段 |
| L1 | 真正Chroma中l1_raw，精确user/agent/source/layer，包含原生状态；不是平台来源账本 | 平台归档成功不等于Hy已有RAW |
| L2/L3 | 同范围原子事实/摘要，默认所有原生状态，有界页及详情/版本关联/可得来源 | ACTIVE混合页不等于每层全部记录 |
| L4 | 可读同范围历史兼容记录，generation_state=historical；无记录时才显示可证空 | 新writer不再生成不等于没有历史 |
| L5 | 枚举保留未实现生成；仍可只读检查VDB是否存在已有同类型记录 | reserved不自动返回0 |
| L6/L7 | 先读精确范围VDB记录（L7实际可存在VDB）。标准装配图未打开时只核可信固定Kuzu路径是否存在；若存在则coverage部分、不可声称图中为空，不创建或初始化图库 | disabled不等于empty，不调用SDK会临时打开图的list/get回退 |

## 读边界、错误与兼容

固定SDK公开list只读ACTIVE、缺source参数、内存排序且可能临时开图，不适合本接口。新RPC仅在同一owner worker的SDK loop、现有Chroma store/collection和VDB执行池读取原生metadata，严禁第二client或直接打开另一连接。查询下推user+agent+source+layer+可选状态，详情同时加ID；回包再次校验，不用正文猜身份。L0的SDK user-level语义需独占范围证明例外，任何版本namespace异常拒绝聚合。

Runtime、Hy、RPC锁非阻塞，忙立即503；单次读取RPC响应等待5秒，超时沿现有关闭worker语义，终止/强杀等待可能再用最多10秒，不重试、不偷偷排队；不能把HTTP超时后后台继续读写当完成。成功请求期间仍持有Runtime/Hy拥有者串行锁，SQLite来源不读写，不调用search/LLM/BGE/状态回写。关闭/无Runtime为503，旧引擎501；参数错误400，普通详情不存在或越scope同为404；busy503 `hy_layer_data_busy`，SDK/闭合/协议失败503 `hy_layer_data_unavailable`。scope不足等预期可读性限制为200 unavailable页面，total/has_more为null，不泄露外部异常正文。write/use暂停仍可读。

这是追加Hy专属只读API，不改变旧items/profile/history/workspace或通用MemoryCore契约；返回内容不授权纠正/删除。worker/process和新模块进入管理原语指纹，旧正式proof将失配并按原守卫拒绝装配。新摘要和真实离线SDK验证证据交主会话审查，生产proof更新/部署另由主会话安排；本轮不改共享private、不重签旧证明。决定见 [ADR-0194](../adr/0194-hy-layer-read-only-browsing.md)。

本文件及 [AA记录](parallel/AA-hy-layer-data-20261021.md)的manifest登记由主会话/Z统一执行，本会话不改manifest。
