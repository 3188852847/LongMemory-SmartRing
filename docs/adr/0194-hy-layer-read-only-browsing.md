# ADR-0194：Hy逐层真实内容的有界只读边界

日期：2026-10-21。状态：本轮实现候选，待独立组合审查；未部署。用户明确要求查看L0–L7里面实际保存的信息，46项机制说明不代替内容浏览。契约见 [逐层内容接口](../development/hy-layer-data-contract.md)，软件证据见 [AA记录](../development/parallel/AA-hy-layer-data-20261021.md)。

## 问题

固定2.0.3公开list只返回ACTIVE，没有source过滤；Chroma list_by_user默认排除RAW，即使只指定RAW仍可被排除。公开list先取最多10000条再内存排序分页，图层又可能走临时打开图库回退。直接复用会漏历史、混来源、误报全层计数、使L1看似为空或在只读浏览时初始化图。L0为user-level多版本diff，链头并非完整基本信息；普通get可能落入其它存储，不能直接用于聚合ID。

## 决定

追加Hy专属layer_page/layer_detail，经已有Runtime/方法/唯一owner worker，固定2.0.3已有Chroma store/collection、SDK loop和VDB线程池原生metadata读取；不创建第二client、不打开库文件、不用search/LLM/embedding。普通查询下推user+agent+source+layer+可选状态，默认all，取limit+1和offset，不扫全层、不查全库count；能由末页证明才给准确范围总数，否则null。

L0必须已有可信空库来源范围stamp与现有owner租约；最多读129条判定128上限，逐版本检查允许agent、namespace和结构，复用SDK纯合并/排序/head/渲染函数重建完整字段。固定SDK合并读取所有版本按时间覆盖，并不只取active/latest；返回内容和字段来源沿同一算法，null/空值仍保留在basic_info，渲染按SDK省略。不能证明合并或来源则unavailable/unknown，不从别的agent/source补字段。聚合使用专属profile ID；原生版本另用本层ID只读详情，不获得写权限。

L4历史兼容、L5保留都可检查已存同类型VDB内容，generation与实际数据分开。L6/L7可显示VDB已有记录；图关闭时只核标准Kuzu固定路径存在性，不初始化遗留图。发现未打开图资源为partial/unknown，total=null，不能把“当前禁用”解释为没有数据。现阶段不承诺旧图库内容可浏览。

Runtime、方法与RPC锁非阻塞；取不到立即busy。成功请求在短的有界存储读取期间串行，RPC响应等待5秒，超时关闭worker、不重试；既有终止/强杀等待可能再用最多10秒。页面只在用户点层时请求，不成为聊天/总览后台轮询。

worker/process与新layer_data模块都纳入管理原语指纹。旧正式proof会失配，保持原拒绝守卫；新摘要需真实SDK合成内容读取及原管理回归证据，生产proof更新/部署由主会话统一安排。本轮不填新hash冒充旧证明，不改写开关/配置/数据库身份，不侵入MemoryCore。

## 替代和代价

只改前端层标签仍看不到真实内容。复用公开list不能满足RAW/历史/范围/开销要求；全量导出或直接SQL读取个人库会破坏拥有者边界；自动开启图扩大运行和写入范围。采用固定SDK私有存储原语增加版本绑定，须保留源码依据、严格反向校验与升级拒绝，并纳入proof。图未打开和超限L0只能诚实报告不可观测；正文/版本关联有界截断，跨页不是冻结快照。这些限制在API和页面明确呈现。

本决定追加只读行为，不改变ADR-0181/0185的中立管理、来源归档、所有权、写权限或不确定状态语义；不能将读取到内容当作模型提取正确性或真实设备验收。
