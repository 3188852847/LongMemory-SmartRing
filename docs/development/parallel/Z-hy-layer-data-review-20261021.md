# Z：Hy逐层实际内容与页内滚动独立审查

2026-10-21，Asia/Shanghai。**阶段：AA逐层契约与Y精确滚动小提交预审；数据实现及最终组合待交，未初始化SDK或执行库读取，尚无发布结论。** 用户本轮明确要看L0–L7实际保存内容，并反馈运行路径点选跳顶；46项机制目录不代替数据浏览。根已确认上一轮未满足这项内容展示意图，本轮单独验收，不改写旧报告的软件/发布证据或结论。

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


## AA完整契约预审

根交AA树 `docs/development/hy-layer-data-contract.md`：逐层GET及同层详情，层只接受八个原生值；列表limit 1–50、offset 0–10000、状态白名单，read_status/data_state/coverage/count_scope分列。L0采用实际SDK纯合并/head/渲染算法、可信stamp及租约、版本逐一范围验证，超过128版本或字段上限拒绝伪完整聚合；L1及其他VDB内容拟在唯一worker既有collection下推user/agent/source/layer/state，普通页limit+1，不调用public list/get的RAW屏蔽或图回退。图只查可信固定路径存在，不打开。方向符合本轮目标，仍须等冻结源码和真实离线证据。

特别核实现：非空末页才可由offset+本页数推断total，offset>0空页不能当空层或伪造总数；后验证发现坏行/范围不符时不能继续报精确总数。L0允许agent集合必须来自可信装配而非HTTP，逐字段来源不足不补造。图路径缺失/存在/无权限或非可信路径分别处理，不把无法检查当确定空。5秒应明确是RPC响应等待期限，现有worker终止/清理还可能占额外时间，不把它宣传为HTTP总耗时保证；超时关闭且不复用晚响应、不重试须有测试。本次指定AA的ADR-0194尚未读到实际文件，正式交付须核对其内容及链接，不将缺失ADR视为已经审完。

## Y早期滚动小提交独立预审

根交 `ced8ba53703294b567e41ddb260a632908acc280`（父34b2111），Z在保护准备提交82c65ef后接为 `a7c287d`，无冲突。仅Hy两处页内search更新加preventScrollReset；RouteWorkspace沿同一显式React Router sessionStorage key恢复坐标，保留全局ScrollRestoration。首次layout不以0覆盖已存位置，POP的ResizeObserver、用户wheel/pointer/keyboard取消及跨路径焦点逻辑保留；没有正文存储、任意JS执行或原型赋值。有限非负数过滤、最多200个Map坐标，损坏JSON/存储拒绝走空Map。

Z本树无node_modules，故未启动React/Playwright或借用Y依赖/进程。用现有Node对实际savedPositions纯函数去类型注解后独立验证7类输入通过：缺失、数组、坏JSON、存储异常、有限非负数、特殊键不污染原型、201项截至200；这不是React/真实滚动验收。只读核Y固定证据 `scroll-components-v1.json` 26项通过及 `scroll-fixed-browser-v2.log` 两屏真实浏览器2项通过，后者4.7秒，原文件摘要留本树ignored元数据。实际测试代码先scrollY>100再点选，以坐标差断言节点/目录/层/tab，返回/刷新和桌面跨页回顶/主焦点；移动原生select留浏览器原生滚动容差。作者结果与Z独立纯函数检查分别记录。

当前窄滚动补丁未发现阻断项，可以保留进入后续组合；数据内容UI接入后仍须在最终构建重核真实非零scrollY、分页/详情、懒加载和草稿，不将早期2项当最终两目标验收。Y仍独占其树，Z只读取作者忽略证据，没有checkout、执行或写入其目录；后续范围须剔除已pick的ced，避免重复接入。

## L0纯函数与X准备报告补核

独立静态读取固定SDK的basic_profile.py：`_node_timestamp`取gmt_created或valid_from，datetime转换失败/非datetime为0；`_assemble_full_kv_from_nodes`按此键稳定升序排序后遍历所有节点的basic_info_kv，后值覆盖前值，不按状态筛选。`_latest_l0_heads_from_nodes`另行筛ACTIVE、合法L0及is_latest，并优先user-level和较新时间。二者用途不同；field_sources应沿同一排序及覆盖规则确定，不能只沿gmt_created或自行过滤旧状态。这里只核源码，无SDK导入/初始化或库读取。

根交X仅报告提交 `8393eabf670a7c2922838524f9a6a4dc7458ef0c`，接为 `c0b0ea1`，无冲突。[X准备报告](X-hy-layer-data-release-20261021.md)没有新可执行部署工具，候选/proof/检查点绑定仍pending，未stop/apply；其正式环境快照属于作者现场证据，Z没有访问正式服务或个人库复验。新指纹必须绑定新增模块与其语义依赖，新离线套件不能被旧两文件回执替代；后续X还须交新冻结计划、proof精确替换门及独立生命周期批准。仅登记本轮Y/X与Z清单，不改旧报告结论。

本轮窄文档检查：登记Y/X后，`check_docs.py --only`选择Z/Y/X三份报告加`--strict`通过，无finding；`git diff --check`通过。此前Y尚未登记时的unlisted/unknown-selection已由清单补齐解决，没有改检查规则。检查仅覆盖链接/清单及差异，不代表分层功能或部署验收通过。

## 新指纹真实SDK验收与签发门槛

X准备核查确认，现行四字段proof不含测试清单，`tests/fixtures/hy_management_receipt.py` 固定TESTS只有旧管理RPC与release_management两文件；仅新原语hash配原5项通过不足以放行新增RAW/逐层读取。Z已只读核该工具，不执行旧命令冒充新验收。

最终必须在精确干净候选上同时验证AA新增真实SDK逐层集成集、原管理集成与后台语义写关闭：多user/agent/source、全部原生层/状态、L0合并与上限、RAW真实内容、跨层/ID拒绝、空offset/末页计数、图不初始化、无search/LLM/BGE和前后状态不变等关键反例；真实SDK解释器/版本/固定来源、导入源码路径与原语包括新模块都须绑定。新测试具体文件与case集合等AA精确交付后冻结，不由调用者任意删减。

验收签发工具需把上述固定套件作为门，而非只收一份未审任意JUnit；零failure/error/skipped且预期case均存在。伴随匿名回执记录精确HEAD/源码摘要、测试文件路径与摘要、case/JUnit摘要、SDK身份及背景写审核事实，并绑定其实际产出的四字段proof摘要；四字段生产schema本身不随意扩展。任一新测试缺失、被skip、源码变更或未知背景写均不得产出可用证明。原证明不改写，新证据独占目录、失败原样保留；生产proof配置和部署仍由根/X审后执行，Z不改私有来源。当前只设计此门槛，未运行SDK、签发或模型调用。
