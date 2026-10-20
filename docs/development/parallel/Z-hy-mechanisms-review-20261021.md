# Z：Hy机制与全站引擎状态独立审查

2026-10-21，Asia/Shanghai。**当前阶段：AA/Y组合软件审查通过，已产出新Z构建，待主会话发布窗口；尚未上线本轮。** 本轮独立于上一轮语音修复，不更新其历史验收。主会话已确认main基点 `eaa65b5b2979add8fd513bba07e19e64d5afa36b`；Z核对自有树clean后建立 `codex/z-hy-mechanisms-review-20261021`，旧分支、SDK、工作树和全部证据保留。

## 范围与交接

Y独占前端，AA独占固定2.0.3机制清单及最小只读能力接口。Z当前只读本树基点源码及已装SDK静态文件，不访问或操作Y树，不接未提交实现。待根交精确SHA和串行前端移交后，Z再做独立审查、必要修复、组合回归及文档同步。接口/实现尚未验收，不把准备工作写成已上线。

不新增模型/联网获取/依赖安装，不操作生产、个人库/私有配置、Docker、串口或固件，不修改V树SDK，不merge main/push或向其他会话发消息。前端使用ui-ux-pro-max的React异步错误/状态指导，保留既有设计系统；文档按project-doc-maintenance窄范围维护。

## 已确认基点缺口

- [ConsoleNav](../../../web/react-chat/src/components/AppShell.tsx)只有调用者显式传入hy才显示Hy导航，默认走旧导航；聊天、设备、设置等调用未传入。局部记忆页适配不能证明首次直开其他页面正确。
- [总览](../../../web/react-chat/src/pages/OverviewApp.tsx)按聊天enabled请求旧 `/api/memories`，快捷说明和详情保留旧L0/L1；[状态栏与轮次摘要](../../../web/react-chat/src/features/chat/ChatObservability.tsx)也按旧L1/L2/L3解释。Hy模式不能读取旧库后把统计换名显示。
- [MemoryDomainRoute](../../../web/react-chat/src/features/memory/MemoryDomainRoute.tsx)只在旧域书签按memory-config的representation做局部分流；质量链接转activity，不等于新质量任务已有合理替代。loading/error路径已有局部保护，但没有全站共享引擎状态事实。
- [现有管理API](../../../web/react-chat/src/api/memoryEngine.ts)有条目、来源、画像、历史和平台操作记录，没有完整机制目录。history能力与operations分别声明；平台管理审计不能冒充SDK历史已启用。[服务端](../../../src/longmemory/entrypoints/api/routes/memory_engine.py)和[管理扩展](../../../src/longmemory/methods/hy_memory/administration.py)的实际契约必须与新前端类型一起核对。

## 固定SDK与装配边界

只读安装元数据为2.0.3，未构造client；本机文件摘要/八层AST核查存本树忽略目录 `data/test-tmp/z-hy-mechanisms-20261021/sdk-static-preparation.json`。官方固定来源提交由[既有接入记录](V-hy-memory-20261019.md)与sdk_bridge声明追溯至 `2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed`；本次没有联网重新获取源码，完整机制/固定来源同一性待AA清单交付后复核，不能只据README或版本号宣布验证完毕。

安装的models/memory.py有八个唯一值：`l0_basic_info`、`l1_raw`、`l2_fact`、`l3_summary`、`l4_identity`、`l5_knowledge`、`l6_schema`、`l7_intention`。类注释仍称“七层”，兼容别名又有旧编号，展示应以八个唯一值及当前写入/读取路径为准。L4在writer中保留历史读取、新提取不再产出；L5注明未实现，不显示为正在产生的新能力。平台原话与Hy L1 raw分别标注，平台旧L0/L1/L2/L3不套入Hy。

本树[worker装配](../../../src/longmemory/methods/hy_memory/worker.py)固定pro，关闭图、coding、System2队列、意图提取、SDK history及相关缓存/访问跟踪/检索子句；[桥接检索](../../../src/longmemory/methods/hy_memory/sdk_bridge.py)固定chat，schema_limit/intention_limit为0；[召回注入](../../../src/longmemory/methods/hy_memory/method.py)选择normal及按设置可选profile。三路search返回契约是normal/schema/proactive，不能把协议有该路等同当前召回或注入已启用。System1/System2、lite/pro/ultra、图/图式/意图、working/coding、版本/冲突与持久状态的完整机制仍逐项等AA证据，不从pro名称外推。

## 候选验收标准

| 领域 | 必须证明 | 不能以此代替 |
|---|---|---|
| 全站引擎状态 | 总览/聊天/设置/设备/预览/实验及记忆旧书签首次直开一致；loading、unknown、error、后台刷新失败、状态切换有明确信息，迟到响应不覆盖新引擎 | 默认旧导航、暂显旧计数、缓存旧引擎冒充当前事实 |
| 统计与兼容 | Hy不请求旧L1计数；条目总数/本页数/未知准确区分；旧引擎仍有原导航、统计与管理入口；旧质量任务有可解释新入口或明确不适用 | 将0当未知、仅改标签、无替代删除质量入口 |
| 机制真实度 | 八层均可见，L4/L5保留状态清楚；每机制带固定代码/来源、SDK支持、装配状态和证据/unknown；历史、图、System2等关闭可解释 | 静态README充当全部机制，支持即已启用，装配声明即本轮运行证据 |
| 可交互证据 | 数据流/层级可键盘点击进入已有条目、来源、历史、处理/检索/注入证据；缺失、未记录、不支持、未启用、无结果分别表述 | 假造链路ID、仅装饰动画、从空结果推断未发生、从SDK history关闭推断平台审计不存在 |
| 只读与性能 | 新GET零search/LLM/BGE，不写库、不全库扫描/新workerRPC；避免共享管理锁长等待、重复bootstrap/轮询；展示取样时点及持久/内存/未知边界 | GET方法名证明无副作用、能力目录触发SDK初始化或拖慢聊天语音、伪造性能数字 |
| 可信管理边界 | 对照[管理原语指纹](../../../src/longmemory/methods/hy_memory/assembly.py)七文件与原证明；新目录不绕过Runtime/拥有者/权限/隔离，敏感路径与凭据不出现在响应 | 为只读展示默默更改RPC/proof、重新填hash、扩大纠正删除范围 |
| 接口与界面 | 真实合成后端响应对接TypeScript类型；成功/空/unsupported/失败均验；桌面/窄屏/大字和键盘，焦点、返回/深链、屏幕阅读标签、截图实际核对 | 只有手写Fake组件测试、只构建通过、只截图无操作验证 |

共享引擎事实可由统一查询/上下文实现，具体方案由Y负责，Z审实际行为，不强制引入新框架。新只读能力目录可以独立静态投影，但运行状态来源要标成装配声明或实际观察，不能使用旧库补数。机制页面的首要任务是帮助用户理解和核对记忆，不把内部实现术语塞进日常操作。

## AA字段契约首轮预审

根交AA树中的 `docs/development/hy-mechanisms-contract.md` 草案后，Z仅只读契约，未接实现。拟定 `GET /api/memory-engine/hy/mechanisms` 区分标准装配/自定义unknown、装配声明/内存开关/worker_health未知；count为null，normal/schema/proactive与额外profile分开，并明确SDK history关闭和平台operations独立，方向符合上表。尚未证明字段实现、固定清单完整性或前后端组合。

本树 `MemoryRuntime.status()` 实际会调用圆屏store.expire并移除deferred事件，且wait_until_ready；因此新增纯只读目录不能借它取开关，也不能通过现有workspace间接触发。正式审查须验证：标准factory来源标记由受信装配建立，不以method名称/用户输入猜测；自定义factory关闭所有未证结论为unknown；锁内内存投影不进入SDK/数据库，锁竞争及反复刷新不拉起重初始化或无界任务；关闭、未装配、写/use暂停均按契约返回。SDK版本是适配器声明、observed_at是读取内存时点，不能显示成现场已探测版本/最后成功运行时间。

## 后续交接与完成条件

等根精确交AA/Y提交、接口样例/覆盖表及串行Y树移交，再核源码/固定来源、组合类型契约与必要隔离测试、实际宽窄截图和键盘。只用已有依赖，临时端口与合成库；缺依赖不安装、不联接共享可变node_modules。根负责发布/推送与最终验收；Z提供可追溯精确组合SHA、实际检查/限制及工作树状态。

本阶段仅源码/元数据静态准备及此记录/清单，未运行业务、SDK调用、模型、前端构建或浏览器；没有候选验收结论。Z会话 `01a15404-7df1-7f92-818f-e25093730b61`，主会话 `01a1534f-3c56-78c1-9e13-4777422a67bb`，AA会话 `01a15a18-68cc-77c0-a6d2-76ba574e74d5`；Y范围仍待根串行移交。


## AA精确后端接力审查

根交AA `b016c2d828cfd67e03a26d8d72afe28d06a78445`（父main `eaa65b5`，作者树clean），Z在保护准备提交 `93b5162a05a9d9de544a2c5f3d6e32675f13df16` 后接为 `b97a2eb`，无冲突。新增中立identity与Hy机制目录，未接Y代码或操作其树。完整契约见[Hy机制契约](../hy-mechanisms-contract.md)，作者证据见[AA记录](AA-hy-mechanisms-20261021.md)。

独立源码审查确认：server通过existing_memory_runtime只窥已存Runtime引用，不调用memory_runtime懒创建方法。identity的available仅表示现有内存身份；旧库显式配置但未初始化时method为null，不打开旧库来补值；busy/closing/closed返回503，不伪装旧引擎。机制GET拒绝参数和body，沿既有会话权限；依次非阻塞取得Runtime/Hy锁，finally释放。它不走status、wait_until_ready、workspace、diagnostics或SDK RPC，只投影内存门/目录；Runtime和方法关闭路径均拒绝。标准来源标记只在client_factory为None的可信装配处建立，自定义factory保留unknown；engine_initialized不是健康，observed_at不是上次成功调用时间。

静态抽查固定SDK枚举/写入保留层、三通道及独立profile、pro/ultra路径，以及平台worker显式关闭项、process_client固定legacy reader和trace关闭环境。目录46个ID唯一，全部出现在契约覆盖矩阵；每条仓库/SDK相对源码引用文件存在，无绝对路径或越界引用。这里只证明该一级目录覆盖与已核边界，不声称每个环境变量/内部算法分支或真实运行均已验证；未知增强不执行模型补数。新目录没有条目数量/逐写决策/逐答完整注入轨迹，count=null及evidence_gaps分别呈现限制。

Z补充正式create_app的标准/自定义Hy目录成功路径两项检查，连接真实server路由和鉴权，使用合成Runtime且禁止SDK初始化/status/SQLite连接；验证identity与机制响应能组合，未创建PRIVATE测试库或启动SDK。与AA独立路由测试互补，不把替身client当成真实日用/SDK验收。定向7模块 **62 passed，1.06秒，0失败/0跳过**：identity、机制、Runtime扩展、管理HTTP/守卫、版本演化及来源叠加；全部随机非日用端口、独立合成目录，无模型/生产操作。日志临时根为 `data/test-tmp/z-hy-mechanisms-20261021/pytest-aa-review`。AA报告的191项是作者记录，不混写为Z独立执行。

worker/process_client/management_rpc/sdk_bridge/short_embedding_input/sdk_observation/observation七文件相对eaa65b5差异为空；实际原语函数重算仍为 `e358debcfa870e09c6072645758d70ac4fa6792bcfb1dd5d589f3c1490657e04`。没有改写或重签原证明、管理RPC或持久身份。新增中立identity不返回数据库/资源路径、用户/助手命名空间、模型或凭据；异常只返稳定代码。暂停写入/use不阻止只读机制展示。

**后端当前未发现阻断项；前端及完整组合仍待精确提交与串行交接，不能发布放行。** 后续特别核对Y对available/not_initialized/unconfigured、503与旧缓存的解释，不把known legacy未初始化等同装配健康；机制深链/质量替代入口、真实响应TypeScript契约、宽窄大字/键盘/截图仍待验。本段仅更新Z记录与统一清单，AA/Y原文件范围不越界，上一轮历史结论不变。


## Y串行移交与完整组合审查

根确认Y树clean且无本树任务后，正式串行交还前端树。Y范围为eaa65b5之后 `60b9d6df902020dfb9515191e2d23b282cd557ba` → `4b18f6afe77a684cbe20ea6d245001c94e3cee02` → `042a9f58d6ace4b1b77842188f6caf34ada5c392`；Z顺序接为 `e2d289f`、`d11345b`、`885c9bb`，无冲突。另在已移交前端树建立唯一 `codex/z-hy-mechanisms-ui-combined-20261021`，与主Z审查分支不同名；Y分支、实体依赖与ignored产物保留，未安装/下载/联接依赖。Y的[交付报告](Y-hy-mechanisms-ui-20261021.md)记295项前端与16项浏览器是作者结果，不混写为Z重跑。

独立审阅全局Provider、导航、总览、聊天证据、管理页和机制页：identity未知/加载/失败不落旧导航，503保留上次确认而不密集重试；Hy概览/聊天只读轻量身份，不为数量请求旧L1或SDK列表。管理配置与身份不符不挂旧页，SDK history先核声明、关闭/未知不请求历史。机制动态列出全部响应项，8层/3模式、未知计数、装配声明/健康/执行证据和缺口分开；URL选择/旧书签/草稿护栏和键盘均有验证。原质量聚合为旧后端契约，Hy保留机制证据与已有聊天轮次标记入口，不冒充已有Hy全量质量统计。

### Z发现并修复的兼容回归

新MemoryApp只在identity.available后读管理配置，挡住“显式旧库＋无聊天Runtime”的既有独立管理模式。Z仅让显式进入管理页或旧书签时，依据已确认的configured、legacy_sqlite、atomic_fact声明浏览旧库；全局kind仍是uninitialized，method保持null，总览不补旧统计。该分支不读memory-mode，不懒建聊天Runtime；未知/Hy/冲突身份不获得此例外。另把无运行开关数据时误显示的“召回已关闭”改为聊天未初始化/状态未提供。

前端树提交 `1edb5e4`、`85f66d6`、`dedb064` 对应主Z树 `c52d728`、`54b7b5b`、`51ad5cd`。中间类型检查发现新增Testing Library角色断言的exact属性不受类型支持，已改完整名称正则；保留失败事实，无产品运行异常。相关MemoryApp/Provider/DataPages **38项通过**，最终状态文案新增断言对同一回归另跑1项通过，其余被选择过滤而非重复计算。修改构建输入后不再冒用Y产物通过记录，重新类型检查与独占构建。

### 实际API、浏览器与产物

初始先核Y前端tree `683825d1af44f8d51acb94d3faf9cdbcd4442f5e`、188份源码字节及45份build-v5/manifest，并独立核v4/v5逐文件一致。随后Z修改前端，最终以新产物替代，不向生产dist复制。最终前端tree为 **`5c26a1ca45d6d284743f0f19eb0379cb48b5e55d`**；构建在前端树 `data/test-tmp/z-mechanisms-build-20261021-v2/`，45文件，manifest摘要 **`d66cb33a09190bafc5458cdaae40d7304f8650bc49b0f8b648a71a5f2a1da59b`**，整树清单摘要 `e2cb41d3f8b34709d485f3b340bc1e24a0199a69b50e980582ffc7b92e2f471d`。依旧有原shared-visual大包提示，未为此扩大拆包/依赖变更。

最终新构建Edge合成API浏览器 **16/16通过，43.3秒**，覆盖全站冷开、未知/忙/未初始化/旧引擎、无旧统计/目录计数、全部机制/8层/URL刷新、来源、关闭history、宽窄大字/键盘/草稿和未知结果。另以真实create_app和同一新build驱动Edge，不替换API响应：标准Hy返回的46项/8层/3模式通过前端严格解析、目录选择与键盘；1920桌面、390大字号无水平溢出，已逐图查看。请求仅session/identity/mechanisms，禁止SQLite连接/status/SDK工厂仍通过，SDK未初始化，无模型调用。

独立旧库组合使用新合成SQLite及真实create_app(database=..., chat_backend=None)，浏览器能打开原话与事实，identity仍not_initialized/method=null，未请求memory-mode或Hy机制，数据库前后字节相同。合成库创建仅在测试准备阶段，不冒充GET完全未建测试文件；不是个人库迁移。最终实际组合证据在前端树 `data/test-tmp/z-mechanisms-combined-20261021-v4/`，浏览器全套日志为v3目录的browser-final.log及 `z-mechanisms-browser-20261021-v2/`。首轮辅助脚本在React提交前过早数按钮失败，改等待后通过，原日志和初始新构建/截图全部保留；未把辅助脚本时序错误写成产品故障。

原dist/test-results 174份摘要最终重算全同，package/lock未变；Node/Edge及服务helper均由各自finally清理，未触日用端口。完整组合新增风险以上述62项后端、38项针对组件、最终16项浏览器和实际API两路径核对，没有为文档收尾重复运行业务或真实SDK。测试替身不证明真实Hy数据/日用worker健康、模型效果或设备体验；没有新时延采样，更不宣布整链路2秒。

## 本轮交付状态

当前无未处理的组合阻断项，软件组合可交根安排发布评估。AA/Y契约、报告、新指南与本记录统一登记；管理七文件及指纹仍按上节不变，未重签证明。最终匿名review receipt在干净文档提交后绑定精确HEAD、前端tree/源码字节、构建manifest/逐文件清单、实际API和浏览器证据，供X部署核对；不含个人正文、凭据、生产路径原件或个人库。Z不merge main/push/操作生产，正式是否上线及用户体验由主会话/X后续记录，不能提前登记。
