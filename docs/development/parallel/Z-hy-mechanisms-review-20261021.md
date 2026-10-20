# Z：Hy机制与全站引擎状态独立审查

2026-10-21，Asia/Shanghai。**阶段：只读准备，尚无候选交付、整合、业务测试或发布结论。** 本轮独立于上一轮语音修复，不更新其历史验收。主会话已确认main基点 `eaa65b5b2979add8fd513bba07e19e64d5afa36b`；Z核对自有树clean后建立 `codex/z-hy-mechanisms-review-20261021`，旧分支、SDK、工作树和全部证据保留。

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
