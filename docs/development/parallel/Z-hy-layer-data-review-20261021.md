# Z：Hy逐层实际内容与页内滚动独立审查

2026-10-21，Asia/Shanghai。**阶段：只读准备，未接AA/Y候选、未初始化SDK或执行库读取，尚无实现/测试/发布结论。** 用户本轮明确要看L0–L7实际保存内容，并反馈运行路径点选跳顶；46项机制目录不代替数据浏览。根已确认上一轮未满足这项内容展示意图，本轮单独验收，不改写旧报告的软件/发布证据或结论。

## 起点与分工

Z核对自有树clean且无未完成工具任务，从main `34b2111d646cb1672bdad62603174e0da7c57f6b` 建 `codex/z-hy-layer-data-review-20261021`。AA独占逐层真实SDK读取/分页/详情与隔离，Y独占原前端树，先交独立滚动修复再做内容展示。Z当前只读自有基点和已装固定SDK静态源码，不操作他人树或接未交代码；等根精确SHA/契约与最终串行前端移交后审查组合。

不改生产、个人库、配置、SDK、Docker、设备/固件，不下载/安装、不调用模型或SDK初始化。当前日用继续运行，不为准备而停服。本轮记录及必要manifest为Z独占；原分支、工作树、SDK和证据保留，根负责main合入/推送/发布，Z不merge/push或向其他会话发消息。

## 静态核查到的读取边界

固定SDK目标为2.0.3、源提交 `2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed`，依据既有接入记录及已安装源码静态核查，不新增联网获取。client/models/Chroma三个文件摘要存本树忽略目录 `data/test-tmp/z-hy-layer-data-20261021/static-sdk-review.json`，无库/SDK调用。

- L0的get_user_profile是实际聚合profile，SDK按user读取，组装最多1000个L0版本并可附ultra片段；不天然有agent/source过滤，也不是普通get可完整替代的单条记录。须继续核独占范围证明和可得来源，不把聚合ID当普通事实；不能保证超过读取上界时仍完整。
- public list_memories支持layers参数，但只列ACTIVE，默认排除RAW，不接受source参数。_list_vdb_bucket先取底层最多10000个候选，再排序、求len并切offset/limit；不能把请求页大小当存储层分页证明，也不能把截断候选len称精确全库总数。
- 普通async_get主动屏蔽L1_RAW。实际Chroma list_by_user默认allow_raw_layer=False，显式仅RAW会被移除并落入layer!=RAW条件；其“结果必为空”注释与条件不一致，静态条件可能返回非RAW。因此SDK公开方法注释不足以证明RAW可列可详；候选须核真实层类型及受控底层读取路径，不用平台原话充当RAW。
- Chroma底层支持user/agent/source过滤，但枚举接口本身无offset；任何新包装须说明排序、范围、边界与总数能力。普通get按ID读取后仍须独立核user/agent/source和目标层，不能靠前端已经选中某层来放行。
- graph bucket会调用_acquire_graph_store_for_purge，即便pro/关闭图，发现遗留数据也可能临时initialize GraphStore。不能仅凭enable_graph=False证明列举不会初始化或写；L6/L7缺graph返回不等于确定空库。须分别核向量/图存储及无法安全读的具体限制，不为看数据启用Graph/System2/意图或初始化新图。
- 现有[管理列表](../../../src/longmemory/methods/hy_memory/administration.py)是活动混合条目，逐项get和来源校验；不是本轮按层全库浏览。SDK history、演化链、平台来源与管理审计仍是不同证据，空history不证明无变化。

这些是固定源码分支核查，未运行真实SDK来证明具体返回；AA正式契约/实现与后续离线真实SDK验收必须分别记录。SDK与平台已有边界参见[管理契约](../hy-memory-management-contract.md)和[方法边界](../../architecture/method-boundary.md)。

## 滚动链路与现有证据缺口

[机制选择](../../../web/react-chat/src/features/memory/HyMechanismsWorkspace.tsx)、[管理视图/分页/详情](../../../web/react-chat/src/features/memory/HyMemoryWorkspace.tsx)及[旧数据工作区参数](../../../web/react-chat/src/features/data-workspace/DataWorkspace.tsx)更新search params时未传preventScrollReset；全局[RouteWorkspace](../../../web/react-chat/src/app/RouteWorkspace.tsx)仍挂ScrollRestoration。这是查询导航触发回顶的代码线索，尚未用本轮浏览器复现；根已有实际用户反馈，不能以旧组件截图覆盖。

现有RouteWorkspace单测mock scrollTo只检查焦点；上一轮机制浏览器没有真实非零scrollY断言，不能证明页内滚动保持。Y精确小提交到后只审其范围，不全站移除ScrollRestoration或吞掉历史返回/跨页行为。真实浏览器应先建立足够长的可滚动页面，确保控制点可见且scrollY>0，再测点击后的实际坐标；区分导航强制回顶和新内容过短导致的浏览器自然夹取，必要时按max scroll上界解释，不以不可滚动页面的0→0充数。

## 候选验收标准

| 范围 | 必验收的事实 |
|---|---|
| 实际层内容 | L0真实聚合；L1真正SDK RAW；L2/3与其他层分别显示其实际可读内容。机制说明仍可辅助，但不能代替数据。保留/关闭是配置维度，与已有内容、实际空、读不支持或unknown分开。 |
| 分页与总数 | 层/user/agent/source过滤在有界查询范围内正确，顺序稳定，翻页无跨层/跨来源；说明ACTIVE或历史口径及截断。精确总数仅在范围/完整性可证时返回，否则null或明确不可得，不能用混合页本地filter冒充按层全库。 |
| 详情与来源 | ID及层都校验，非法/跨user/agent/source/层拒绝且不泄露正文；L0字段来源不足保留unknown。RAW不自动获得写/删除资格，不复制成平台原话伪造链路。 |
| 权限与只读 | 会话鉴权、查询/body白名单、稳定错误，关闭/繁忙/并发读取有界。唯一拥有者内读，不search/LLM/BGE重生成，不开启写/图/队列，不初始化新状态；对合成状态做前后字节/记录核对。overview/chat不拉层数据。 |
| 原生与自定义 | 固定SDK/标准factory路径和自定义unknown明确；数据类型/存储读取依赖有必要ADR。图库不可读不当空，L4历史兼容/L5保留不隐藏已有合法内容。 |
| 指纹与证明 | worker/RPC等七文件变更即重算新原语；旧可信管理proof不能默默沿用、填新hash或降守卫。必须有真实SDK离线合成验证及精确新源码证明链，生产proof配置/恢复由根后续交X，不由Z改私有来源。 |
| UI/API组合 | 实际create_app响应与前端类型/空/未知/错误一致；图/RAW/来源能力不以单元替身宣称全部实现。所有L0–L7可选择和看到真实内容或准确缺口，分页/详情不假造数据；宽窄大字、键盘与截图均验。 |
| 滚动与导航 | 非零scrollY下点运行路径、目录、层、tab、页内分页/详情不强制回顶；URL选择/刷新、前后退位置、跨页回顶/主焦点与草稿护栏保留。需实际可滚动浏览器坐标证据，组件测试或截图不能替代。 |

根给AA契约/Y早期滚动SHA后可先做窄独立审查；最终两方精确交付及Y树串行交回后再组合、必要回归、构建和匿名收据。当前只写本记录/清单并做文档窄检查，没有候选验收、日用动作或提前发布结论。Z会话 `01a15404-7df1-7f92-818f-e25093730b61`。


## AA/Y准备接力补充

根已将RAW默认过滤、候选截断后分页和GraphStore临时初始化三点交AA核实。AA初步方案为逐层列表GET与该层条目详情GET，含limit/offset/state，read_status、data_state、coverage、total/count_scope分开，L0走aggregate_profile；尚未收到冻结完整契约，不将这些名字当作已实现协议。审查时重点核对：read不支持/失败不能变成空，覆盖不完整不能报全范围精确total，配置关闭不能掩盖已有可读数据；state语义、RAW/历史可见性及跨层详情都须有真实离线合成反例。任何新增worker/RPC白名单和底层存储读取均需必要ADR与新指纹验证链，原管理守卫不因读页面而降级。

Y在独占树做真实scrollY回归及懒加载刷新恢复，Z未进入其树。等根精确小提交后再核preventScrollReset与POP恢复的实际交互；不以这份准备文档提前宣布用户跳顶问题已修复。
