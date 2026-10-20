# X：Hy-Memory 圆屏适配、可信装配与条件日用切换

日期：2026-10-19，Asia/Shanghai。分支 `codex/x-hy-roundscreen-20261019`，唯一实现树 `local/worktrees/x-hy-roundscreen-20261019`，基线 `3126c651303fb3f72c5f49b749dd119e126d1712`。X 会话 `01a153df-8682-7e33-80b5-1102ee2b54c8`。**本阶段隔离实现/验收和切换准备完成，待主会话组合接力；未切换日用，整项任务尚未完成，不归档。**

## 新授权与本轮分工

用户明确授权：“独立会话做完真实模型验证和圆屏适配，验证通过后切换日用记忆层；记忆管理前端全部按Hy重新设计，需要配合告知”。真实模型整轮费用上限十元。新库从零积累，旧个人库保留，不迁移/清空/覆盖。此决定追加在旧 U/V/W“隔离接入、不含切换”的历史阶段之后，不改写其当时授权/验收事实。

| 会话 | 本轮所有权 | 会话 ID |
|---|---|---|
| 主会话 | 精确提交交接、组合审查/整合/推送，最终切换候选和验收交接 | `01a1534f-3c56-78c1-9e13-4777422a67bb` |
| V | 真实模型、本地BGE、整轮共享十元预算；worker/settings/process/sdk_bridge/evaluation/专属模型模板 | `01a15363-8120-7400-a9db-8f9142104b12` |
| X | Runtime/圆屏用例/事件、项目小智桥、bootstrap/server、可信后端装配/启动器窄改、必要中立协议和本报告/ADR/清单 | `01a153df-8682-7e33-80b5-1102ee2b54c8` |
| Y | Hy method/administration、method_management/routes/memory_engine、完整记忆管理UI | `01a153e0-5cf5-7763-b944-7031e8a1c548` |

Y 唯一使用既有 P 前端树的新 `codex/y-hy-memory-ui-20261019` 分支，原 S/W 分支和产物保留。X 不使用该树、不借其 node_modules、不修改 V/Y 所有文件、不向其他会话发送工具消息；由主会话接力提交。全部终端显式 X workdir，源码编辑用 X 绝对路径。无 merge/push。

完成标准分两阶段：本阶段圆屏真实缺口及可信装配完成、隔离验收、本地提交和切换清单；后阶段只能在主会话交已验收最终 SHA/构建/资源身份后，由 X 成为那次日用进程/配置唯一操作者再执行。[切换检查单](../../guides/Hy-Memory圆屏与日用装配-20261019.md)已落盘，不把准备称作切换。

## 实现与接口交接

中立接口首提交 `3d8259e8f5ce7a737e0b265d1269a29562a4ac37`；可信选择/身份及后续边界补强提交 `ada8642c401973bc5f1e1e2eb0cbc0430d0bc7df`；正式日用拒绝离线/模拟模型的初始化前守卫提交 `91e7df89c0fa01c08e15e46adcdda3148fd5b72a`。最后文档提交的完整SHA随交付回复，不为嵌入自身SHA循环提交。首提交包含平台轮次、Runtime/网页/圆屏来源、内部API、薄桥及定向测试，不涉及V/Y私有协议；组合应接入三批代码，不能只取首批后运行最终部署。

| 主要文件 | 实际作用 |
|---|---|
| `application/memory_runtime.py`、`application/round_screen_turns.py`、`adapters/storage/sqlite_platform_rounds.py`（均在`src/longmemory/`） | 持久轮次、凭据、完成/取消/反馈、用户/助手来源及完整流程调度 |
| `bootstrap.py`、`entrypoints/api/chat_backend.py`、`entrypoints/api/routes/chat.py`与`routes/memory_runtime.py` | 网页/圆屏共享Runtime、独立短期会话、原旁库基址、中立内部协议 |
| `methods/hy_memory/assembly.py`、`infrastructure/config/hy_deployment.py`、`entrypoints/api/server.py` | 可信文件/路径/模型身份、实际Python/SDK版本、正式选择 |
| `scripts/development/xiaozhi/longmemory_provider.py`、`launch_with_memory.py`、`setup.py` | 线程/异步轮次、真实助手捕获、抑制内部输入、已知提供器升级白名单 |
| `scripts/development/launcher/`相关窄改、`sync_memory_config.py`、`infrastructure/config/memory_backends.py`、`web/react-chat/src/features/launcher/LauncherApp.tsx` | Hy枚举/说明、正式启动路径和旧主动能力暂停 |
| `tests/unit/entrypoints/test_platform_roundscreen.py`、`tests/unit/infrastructure/test_hy_deployment.py`、`tests/integration/test_hy_roundscreen_sdk.py`及既有桥/启动器测试新增 | 合成状态、真实HTTP/SDK与实际3.10桥回归 |

源码中上述未展开的Python路径相对`src/longmemory/`；完整文件清单可由`git diff --name-only 3126c65 HEAD`核对。没有修改V的worker/settings/process/sdk_bridge/evaluation或Y的method/administration/管理路由/记忆UI。

- `SQLitePlatformRounds` 在新平台来源库保存轮次、来源/连接会话、准备/完成/取消请求号、召回凭据、超时/不确定状态及反馈；助手和完成关联同事务提交。新增中立 `memory_receipt`，不把 Hy 层号塞进通用方法契约。
- `MemoryRuntime.prepare_round_screen/complete_round_screen/cancel_round_screen/round_screen_status`；网页调用新增可选 `session_id`，仅新后端传递。后台保持完整 Hy pipeline（组合流程）串行，来源优先，不自动重试failed/uncertain。准备、取消、迟到及重启语义见[ADR-0183](../../adr/0183-platform-roundscreen-and-hy-deployment.md)。
- 内部 `/api/internal/memory/prepare` 可收客户端轮次/连接会话，Hy必须带元数据；新响应 `memory_protocol=2`、未知数量None。complete按原持久凭据比较，cancel固定原因枚举。认证仍是回环Host/Bearer，浏览器会话不能投递。
- 薄桥按调用上下文隔离待完成请求；助手正文由真实 `dialogue.put` 写入捕获，不再用共享尾部切片关联。重叠旧轮被superseded，不把新答案归到旧来源；内部静默提示仍结构化排除。实际厂家固定 `core/connection.py` 只读确认助手经 `dialogue.put` 写出，未编辑厂家源码。
- `load_hy_deployment/build_daily_hy_runtime` 只消费固定私有文件和显式模型设置身份；解释器/状态/来源路径校验。普通启动不建库。旧原数据库基址继续供网页会话/角色旁库使用，新源另设；小智Memory提供器名继续LongMemory，实际算法由共享Runtime决定。
- 正式日用在初始化前拒绝未授权外部模型及synthetic_transport模拟模式，避免把本轮SDK替身误当日用成功；该守卫不代替V真实模型/BGE/预算和主会话验收门槛。
- 启动器/偏好/后端枚举支持hy_memory；保留旧回退。Hy强制暂停旧定时联系、整理和影子，UI显示暂停且旧提取/召回控件不生效。旧主动API仍拒绝。未实施主动交流下一阶段。

部署旧提供器只读核对：主源码和实际消费副本 SHA-256 均为 `98998f2fcf28c754bc39336129b072c737dd2cc58ef9505137625661452ce018`，只把此精确已知版加入正常同步器升级白名单；未执行安装/同步/改配置。

### V/Y组合必须核对的接口

V 接线仍须其最终 `HySettings.from_wire` 能忠实表示真实模型/本地BGE/共享预算，并让 `identity()` 绑定精确模型、端点、维度及本地资源身份。X固定读取 `local/config/hy-memory/settings.json`，部署身份必须等于该设置身份；不会从HTTP收任意路径/端点。X装配使用 `sdk_call('diagnostics')` 的 `sdk_python/actual_sdk_version` 核对实际版本，请V保留这两个既有字段。基线仅disabled/synthetic_transport，不把它说成真实日用装配已通过。主会话给精确V提交后再做组合补验。

Y 可读取 Runtime 状态中的 `proactive.state=paused_backend_unsupported`，不要继续展示正常联系。中立来源状态/详情保持原接口；圆屏生命周期可通过 `round_screen_status(event_id)`获取，包含助手关联和请求号。平台反馈表只采集严格反馈、不训练/修改Hy；若管理UI需展示该新表，应由主会话串行交具体需求，不由X越界改管理路由。当前X不声称完整管理UI已验收。

Y若将`HyAdministration`移至新模块，应保留method.py原导出的兼容转发，或由主会话串行调整X的assembly.py导入；X未修改该类或其管理协议。

## 验证与限制

主解释器只读复用项目Python3.12.13，实际打印导入为X/src；测试源码/合成状态/随机端口均在X。专属Hy解释器只读复用V已安装`.venv`，小智真实Python3.10.20按显式测试路径借用；收尾三解释器实际分别报告3.12.13/3.10.20/3.12.13，SDK实际版本由worker核对2.0.3。未复制/重装环境、无依赖或锁升级。

| 检查 | 本轮实际结果 |
|---|---|
| 首批旧后端/聊天/接口/架构/小智setup | 101 passed；初次setup收集缺少脚本目录，补进程级PYTHONPATH后通过，未改产品或断言掩盖收集问题 |
| 平台轮次定向与既有桥 | 42 passed / 2 skipped；跳过是原测试默认仅在X查厂家源码/解释器，X无副本，随后显式跨版本用例另补 |
| 启动器/可信部署定向 | 86 passed；新增测试初次插入到旧测试中间导致断言归属错误，已恢复原测试完整断言并分开新用例 |
| 真实Hy SDK/Chroma + 禁网模型替身 | 首批2 passed，11.99秒；最终增加实际Python/SDK版本拒绝及两个资源拥有锁释放用例，共3项随最终组合通过。含Python3.10提供器→X真实HTTP/Python3.12→专属SDK进程，真实完成/来源/召回/重启，external_http_attempts=0 |
| W已知重复bind | 本轮取证确认同Tracker失败路径重复bind；仅保留首次绑定，Tracker被替换时仍重绑定；原期望未改，定向和启动器组合通过 |
| W已知诊断双进程 | 本轮精确用例1 passed，0.16秒；实现和测试对基线无差异，使用本轮显式PYTHONPATH。保留W当时失败，不推定唯一原因或报告已修复 |
| 较大受影响组合 | 首轮758 passed /4 skipped /1 failed：旧教学/观测入口没有完整Runtime接口，修实现并保留旧测试后，第二轮760 passed /4 skipped，94.95秒。之后状态身份/元数据/部署窄补验74 passed；再一次组合761 passed /4 skipped /1 failed，未改的`test_observation_redirect_is_not_followed_with_bearer`发生WinError10053连接中止，未定位唯一原因、未改诊断代码或测试；其后连同最终轮次/部署/SDK定向31 passed，15.34秒。**最后在ada8642代码上764 passed /4 skipped，93.36秒**；不是全仓/远程CI，不抹去中间失败 |
| React启动器窄改 | X无独立node_modules，未安装/借用Y；本树未跑TS/Vitest/生产构建/浏览器验收，交组合阶段补 |
| 最后正式日用守卫窄改 | 91e7df8上的可信部署/启动器/正式选择定向90 passed，4.07秒；离线/模拟模式在建状态前拒绝，无模型请求或数据副作用。764项组合对应其前一代码ada8642，不冒充已再次跑全组合 |
| 文档与差异 | 9份受影响Markdown正式strict通过，findings=[]；清单登记3份新文档和X主题。基线关联检查无未映射源码，仅`docs/README.md`导航和`launcher-contract.md`文档本身未映射，已按本轮增补人工核对；不为静默清零添加虚假源码关联。git diff检查通过，提交敏感模式0、无删除文件 |

最终组合使用主项目解释器，显式X workdir和进程级`PYTHONPATH=X/src;X/scripts/development/xiaozhi`，`LONGMEMORY_TEST_HY_PYTHON`为V专属环境，`LONGMEMORY_TEST_XIAOZHI_PYTHON`为固定小智环境。实际命令主体：

```powershell
python.exe -X utf8 -B -m pytest tests/unit/methods tests/unit/entrypoints tests/unit/application tests/unit/architecture tests/unit/infrastructure/test_hy_deployment.py tests/unit/infrastructure/test_memory_backends.py tests/unit/development/test_launcher.py tests/unit/development/test_launcher_control.py tests/unit/development/test_launcher_preferences.py tests/unit/development/test_launcher_latency.py tests/unit/development/test_xiaozhi_setup.py tests/unit/development/test_voice_diagnostics.py tests/integration/memory_pipeline/test_xiaozhi_bridge.py tests/integration/test_hy_roundscreen_sdk.py tests/integration/test_hy_memory_sdk_offline.py -q
```

四项跳过为Windows测试符号链接权限、未显式绑定Otto固定素材，以及原桥测试只在X查找厂商源码/小智环境的两项。真实Hy与新增显式3.10桥均未跳过；不因X没有复制厂商环境而把原跳过写成实机通过。

真实模型效果、真实BGE、十元预算执行、V/Y组合、正式构建、个人新库、日用服务切换与所有者声音/连接/插话体验均未验。禁网替身不证明真实模型质量/速度；服务器完成/发送不代表设备播放，播放仍unconfirmed。

读取范围仅必要公开规则/代码/文档及固定厂家源码/提供器摘要；未遍历密钥、个人库/真实对话/音频，未把真实内容变测试样本。无日用8767/8000/8003访问或启停、私有配置写入、厂家消费副本更新、个人数据迁移、外部模型调用/费用、安装/下载、全局环境变更、串口/烧录。

文档使用project-doc-maintenance；启动器窄改使用ui-ux-pro-max，首个精确检索无匹配，重试只命中通用提交状态反馈，未把它当作专门暂停能力设计结论；本轮沿既有Select/Alert保持明示状态。未修改根README/CHANGELOG/ROADMAP/AGENTS或U/V/W/T历史原文。V/Y最终文档登记待主会话交具体提交后串行整合，不猜路径/验收状态。

## 追溯与下一步

X任务 → 中立接口`3d8259e`→可信装配`ada8642`→正式日用守卫`91e7df8`→本轮隔离验收（见上）→本报告所在文档提交→合入/推送待主会话→X会话`01a153df-8682-7e33-80b5-1102ee2b54c8`。后续日用切换许可已存在但门槛未满足，X没有抢占日用服务所有权。所有工作树、旧库、SDK环境和原产物保留。

下一步由主会话汇合V真实效果/预算、Y管理重设计及X适配，安排独立组合审查/必要构建，交最终候选后X继续切换阶段；本报告在交接前不填合入SHA、部署身份、真实费用或体验通过。

## 第二阶段：V/Y精确接力与共用原池接线

主会话在核对第一阶段`018dd7a`干净后交付V/Y各五个精确提交，X顺序cherry-pick，均无冲突。主会话另回传用户新的日用费用决定：“先共用本轮10元总上限”，包含V既有约0.491022元消费；不是重新开一个十元账本。随后明确授权X独占补`model_gateway.py`的受控真实流式通道，V只继续worker/process的管理RPC；“RealModelConfig”是交接泛称，实际没有该类，X复用现有接口，没有另造模型配置系统。

| 来源原提交 | X接入提交 |
|---|---|
| V `a53d225e8aaa1415e7900779d241305157fb7cd8` | `73512fc377924904d6b13d18692565aac3041b23` |
| V `fd7d8f4a79b1f3d9872335c277b27596508a0be9` | `89daf75673bc4735a78f5f888f7b52697417611f` |
| V `d4b177764b4bcf4d576fcedc8d9d36ac5758a667` | `34890b7f710c4c5d2147ab227442f22442567de0` |
| V `6896279bef422599eb8e3273c7d1dd52bac6020f` | `c5697bcd94def5fa062cdda7485377aab1e38a4c` |
| V `cd70670b7c48558807fca1a45ae82fc59da4f60c` | `59fba1b34921c42f9f95865f3b35e4d5cf3f94b9` |
| Y `dee2cf4c73e6479812acbaec08d06582453114e1` | `856cdc34142b69b44395dab7ef797bbc9d647c43` |
| Y `b1d9c784f6338bc58265d14b0bcc22df88e9960e` | `2dbc1b13289c4570168786c639402bc35f177e42` |
| Y `4709c0dcdbbf3228983e667225a1ee5d329c339d` | `160450f478567da21c3791b6602aa72228d8330e` |
| Y `505277d6f7ac98f901bf51b70ce26500867499b8` | `9c3306555534a3d7cce17dcdbf38fe14d8effd93` |
| Y `6067f9e31c9c8ca8e9abb266c39700737775017b` | `23ee8558f330ea6140295081992648801254fb41` |

### 实际接线

Runtime扩展白名单为workspace/profile/history/operations/correct/delete，核对open/assembly/namespace，在同一串行锁内执行；correct/delete先查写开关、真实user角色/请求ID/正文，重复ID复用首条来源的时间/会话，归档不observe。可信装配保持serialized_writes默认false；验收回执绑定实际worker/process源码与SDK2.0.3、后台语义写关闭、两份独占租约，并尊重RPC真实update/delete能力。V新RPC未交时不会假设能力已可用。主会话已提示SDKdelete可恢复旧版本，X未为页面解锁放宽单条语义。

新`bootstrap_hy_daily.py`复用V现有模型选择/网关/设置，固定BGE revision与实际512维CPU，稳定provider_identity沿V公式，与端口/口令无关。SDK/网页回答器/圆屏只领取本次本地口令；供应商Key留网关。Runtime接管资源关闭，初始化失败关闭自有SDK/网关/端口，重启复用库和原预算；没有复制SDK环境、安装依赖或换源。

新`hy_campaign.py`只重开原V池，沿用总额、请求/token界限与所有尝试/未知预留。官方核价/CNY回执绑定当前凭据摘要，只允许续原价格策略期限，最长两小时，追加摘要审计，不按日/月重置。X在本轮只读核对[官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)仍支持Flash输入2元/百万、输出8元/百万的保守上界及旧请求名计费，未改真实账本/未查询余额/未付费。真实回执和原池更新留待Z/唯一切换操作者按范围执行，不把测试合成池写成实际续期。

V非流式实验通道保留，X新增圆屏真实SSE：首片即转发，完整usage＋DONE送达才结算差额；断流/取消/缺usage保留unknown，max_retries=0，不伪分块。网页回答、圆屏流式和显式连接检查同池；Hy日用拒绝旁路付费实验入口。暂停时保留原话、固定本机回执、不收费/不提取，不自动退回无预算供应商。小智人工配置不改成随机端点，只生成受摘要保护的消费投影，未知消费副本仍拒绝覆盖。

### 第二阶段验证与已知交接项

| 检查 | 实际结果/限制 |
|---|---|
| 首批Runtime扩展/流式/预算/轮次/setup定向 | 69 passed；首次流式测试错误地对JSON转义串做汉字包含判断，改为解析SSE JSON，产品转发未改成伪分块 |
| 更大V/Y/X组合 | 789 passed /5 skipped，109.23秒；含methods/entrypoints/application/architecture、部署/原池、启动器/配置、SDK/轮次/生命周期；发生在后续凭据摘要和连接检查窄补强前，不假称最终候选全量 |
| 最后原池/真实SDK网关生命周期窄补验 | 15 passed，16.90秒；含当前凭据币种证明不匹配拒绝，原消费/失败预留保留、续期改策略拒绝、真HTTP首片先于usage和中断预留 |
| 真CPU BGE＋真实SDK常驻进程 | 1 passed，9.33秒；读取主项目固定快照，主CPU BGE实际512维，同一SDK进程两次暖召回5.16/6.19毫秒。远端模型为替身，查询为同一合成事实；这不是完整真实日用延迟、分布统计、V的复制冷启动均值或设备首声 |
| 厂家消费投影/固定预算回执 | 合成配置/轮次/预算/流式定向31 passed，1.90秒；源YAML字节保留，回环Key替换、重启更新和未知副本改动拒绝；无实际配置/服务操作 |
| 收尾正式选择 | 增加仅使用托管回答设置后曾把ModelSettings导入加在条件实验块，造成启动用例失败；已移至聊天装配块，原正式选择用例1 passed。未放宽测试期望或改回直连 |
| 最终候选完整受影响组合 | **814 passed /5 skipped，109.87秒**，代码提交`e4137816c08189c34f93082416bc53cf87ef5974`；包括上述全部实现、当前凭据摘要守卫和显式语音连接检查走自有预算网关。沿首阶段命令增加原池、voice_budget、日用生命周期测试；未开启真实BGE根目录变量，故其用例本轮跳过，独立真实CPU记录见上一行；不是全仓/远程CI/设备验收 |
| 文档与提交检查 | 14份相关Markdown strict通过，findings=[]；登记V/Y五份精确候选文档和ADR-0184、源码/测试主题关联。关联检查剩余未映射项仅四份阶段/契约文档自身，已人工核对，未给它们虚构源码归属。代码提交27文件，git diff检查通过，敏感模式扫描0，无删除文件；收尾未发现X测试Python进程 |

V已有真实模型10/10＋7/7属于其精确候选小样本结果；X本轮不重跑保留集、不收费采样。Y已有26组件＋8浏览器是Y候选结果，不代替X启动器改动后的Z组合构建。X没有使用Y树/node_modules或改Y冻结实现。

**已发现需主会话安排的Y窄修复：** Runtime真实写暂停抛`ValueError('memory_write_paused')`，Y的`routes/memory_engine.py.invoke`目前统一映射ValueError为409，而契约要求403。写入被正确阻止；Y替身HTTP测试自己抛MemoryAccessError403所以未覆盖这个真实组合。建议在Y路由只对这个固定码映射403，保留其他ValueError409；X遵守冻结所有权未改该文件，不把此缺口说成已关闭。

当前管理RPC的新增精确提交仍待主会话交付，管理写门保持false；Z还须审查流式计费、实际候选/构建、真实组合probe（只由Z统筹原池）及回退费用边界。日用切换仍未交接/未执行，播放unconfirmed。新决定见[ADR-0184](../../adr/0184-shared-campaign-budget-and-owned-model-gateway.md)，最新配置与步骤见[日用装配指南](../../guides/Hy-Memory圆屏与日用装配-20261019.md)。

第二阶段追溯：主会话精确V/Y交接 → 上表10个本地接入提交 → X受控装配/流式代码`e4137816c08189c34f93082416bc53cf87ef5974` → 814/5skip及独立真实SDK/BGE验收 → 本报告文档提交 → Z组合/合入/推送/日用切换均待执行 → X会话`01a153df-8682-7e33-80b5-1102ee2b54c8`。本地分支未merge main、未推送，未向其他会话发送消息。

## 第三阶段：main交接后的正式服务切换

日期2026-10-19，北京时间20:53取得检查点，20:59技术验收通过。主会话明确交付唯一日用进程/私有配置操作所有权及已推送main `729590c10113f44321c31022e4b6377c19fc0e08`，候选为Z `9901b5372093e544a9077b1e9a91331d338ea149`。X保护原交付HEAD `e1f36c6`到本地`codex/x-hy-roundscreen-pre-cutover-20261019`，仅ff当前X分支到该main；实际核对main与Z完整tree相同，`git ls-remote --heads origin main`独立返回同一main SHA。没有在X合并main、推送或改源码。

### 身份与检查点

| 项目 | 本轮实际核对 |
|---|---|
| 已验前端包 | 主会话交接的P前端树`data/test-tmp/z-ui-20261019/build-v1`，44文件/1759035字节；X按sorted(relative_posix_path + NUL + sha256 + LF)独立重算整体`588fdcc014fe571de451b81de223bb61263952eb7732e410c0dabe2a0613e8a4`。部署后逐文件相同，没有重建 |
| Z源码/管理 | 公开源码摘要`f8562f4576ede1581a63b9b42abb1bfc894c895637117a90d14f819ff716172f`属于Z收据；X独立核对精确main/Z tree相同及管理函数重算`c0bf03ea3cb31e51528e503ee5cd5d251d672a847e49091c462bb71e8a802026` |
| 候选配置 | Z handoff的deployment/settings/management-verification三文件逐项摘要一致后复制；settings身份`5fea60cced324e29fb003de8629687f64864e203e9776288c8bd3664260c7449`，provider身份`7d1029727454df601253f0f92d46fafc886f07aa435137f47bf4138227ea49e2` |
| 新私有检查点 | `local/archive/hy-cutover/20261019-205331/`；`checkpoint.json` SHA-256 `3f912db20c4194441786d55b974c30095e17397ef9d07bcf18f8d76b921717c0`。含64份逐项核对文件、旧源码3126c651的Git归档、旧构建、必要人工配置/偏好/消费副本/提供器/所选声音档案与参考文件；3份SQLite一致性备份分别为旧主库、聊天旁库、原预算池，完整性与每表计数均相同。角色旁库原本不存在，按缺失记录保留 |
| 新资源 | `data/memory/hy-daily-20261019`及`data/databases/hy-daily-sources-20261019.sqlite3`原本均不存在，只显式create一次。首次持久scope证明SHA `bc1d292ebfa4c3b0a7a58028ecde1d64ff0ba6d83e63a0d39c7f1bfbf6b9f1f4`，重开和实际服务身份相同 |

旧磁盘main已由协调会话更新，因此检查点另用已知切换前源码提交3126c651作Git归档；不能据当前磁盘HEAD追认10月18日旧launcher的内存版本。旧launcher PID41900（父42932）通过其认证发现和正式shutdown退出。首次即时检查早于异步socket释放，随后等待确认18767/35486释放、两个进程退出，没有重复发送shutdown或强杀。无关Codex PID49284的回环8768保持原样；本次壁纸服务成功绑定原局域网IP的8768，与回环监听并存，没有改端口或操作其他会话。

部署先将已核对包复制到新staging，逐文件验证后将原dist保留为检查点`old-dist-live/`，再安装新dist。三份候选配置和新核价回执进入`local/config/hy-memory/`。首次初始化成功后，X自用检查脚本两次分别误用能力键`correct`（实际`correction`）和ManagedMemoryMethod包装层路径而失败；产品初始化/重开本身成功，证据保留，没有删除/重建/换新目录。核对实际代码后仅create=False重开，能力、两份owner和身份均通过。来源表`conversation_messages/source_dispatch/platform_rounds/platform_round_feedback`均0，身份元数据行1正常；没有把元数据行误认成用户事实。

### 原池、正式启动与保护核对

切换前新核对[官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)仍支持原请求名、输入2元/百万及输出8元/百万保守上界；使用既有官方档案做一次只读CNY/账户可用检查。仅保存CNY/可用标记及当前凭据摘要，未输出或记录余额/Key。核价有效至2026-10-19 22:53:33，最长两小时；正式装配只续原池expires_at_unix，所有其他policy字段和196条attempt记录与检查点逐项相同，price_renewals仅新增1行，没有重置或释放预留。

本轮新指针为hy_memory，人工launcher偏好仍为圆屏/CosyVoice3/official/原role。从唯一根`启动智慧圆屏.cmd`正式重开新launcher，再经其受限认证动作请求start一次，实际启动API、SDK、小智与声音服务。不是仅保存后端偏好。最终技术收据在同一检查点的`installed-candidate.json`、`initialization.json`、`live-api-verification.json`、`protection-and-voice-projection.json`、`budget-renewal-verification.json`及`final-health.json`；配置/令牌和初始化日志仅留私有位置，不提交。

| 实际检查 | 结果与边界 |
|---|---|
| 正式launcher/进程归属 | 新launcher PID16840；API/网关59052、专属SDK58676、语音51852、CosyVoice53768均属本次launcher后代。启动器报告ready，API、小智、CosyVoice3就绪；不会据此声称设备播放 |
| 网页与同Runtime | 实际GET chat-config和memory-engine均指向新来源文件、相同5fea身份及`hy_memory_pro_chat`/`sdk-2.0.3-adapter-1`。主会话另独立HTTP复核同一状态、预算与管理能力，未调模型/写个人来源 |
| 语音接线 | 厂家消费副本只替换选中CampusLLM为自有127.0.0.1网关`/voice/v1`；和网页`/answer/v1`端口相同。供应商Key没有作为该选中消费Key；将消费LLM还原为人工来源后其余YAML结构完全相同。Memory薄桥消费源码与main逐字节一致，摘要`2c8036183634adc99d6e807ad28098e494d7a55181f569aa48de5f6aa5b9c2cd`。设备尚无真实会话，不把配置接线冒充圆屏已经调用Hy |
| 能力与调度 | 实际Hy workspace的profile/history/correction/deletion true，native_atomic_revision false；通用原子纠正/删除仍false。两份owner在可信装配中核对，首次scope可重开，旧主动交流`paused_backend_unsupported`，未开整理/影子/主动联系 |
| 预算/来源 | 仍196请求、496332微元＝0.496332元保守上界，unknown0，external_models available；X未发付费模型探针或连接检查。真实用户来源/轮次0，未向个人新库注入合成对话 |
| 保留项 | 原env、人工YAML、launcher/model/tts偏好、声音/参考音频、皮肤配置逐项SHA不变；原主库与聊天旁库每表计数不变，角色旁库继续不存在。未触及壁纸库或设备配置/固件/串口，不以电脑检查声称设备NVS已读回验证 |
| 日志与健康 | CosyVoice `/health` ready；只聚合当前时间窗15条厂家日志元数据，ERROR/CRITICAL计数0，不输出正文。这不是未来无故障保证或声音验收 |

技术就绪（technical-ready）成立；21:01:55和21:07:04只读复查设备控制面仍connection_count=0、ready=false、reason=device_offline，8000未见已建立连接。所有者向主会话报告通电联网、尚未唤醒，这与0会话并不矛盾：X只读核对保留固件`application.cc`的HandleStartListeningEvent/HandleWakeWordDetectedEvent→ContinueOpenAudioChannel/ContinueWakeWordInvoke，以及WebsocketProtocol::OpenAudioChannel→Connect，idle在开始聆听/唤醒时才打开WebSocket；CloseAudioChannel会释放连接。厂家WebSocketServer只在真实连接后处理ConnectionHandler，控制面只统计当前connections集合。因此device_offline不等于物理/Wi-Fi联网故障，不能单凭0连接要求修网络；此为保留源码行为，不是串口读取设备状态。由所有者按平常方式唤醒后分别验连接和体验，如有屏幕错误再据实际文字定位。没有为取样唤醒、播放、发送聊天、远程重启或刷写设备。主会话继续安排所有者先验证声音/字幕与真实偏好隔轮长期召回/管理来源，插话最后；中断若产生unknown须原样保留，不能重置费用。

### 追溯与会话状态

| 任务 | 提交/验收 → 本次main | 会话与收尾 |
|---|---|---|
| V真实模型及管理RPC | 原V/Y十提交映射见第二阶段；V新增RPC `8199703`、`0230500`、`481befd`经Z重验 → `729590c10113f44321c31022e4b6377c19fc0e08` | V `01a15363-8120-7400-a9db-8f9142104b12`；主会话回传已交付/验收/合入，无待工作并已归档 |
| Y管理重设计 | `dee2cf4`→`6067f9e`五提交经X接入、Z组合修复与构建 → 同一main | Y `01a153e0-5cf5-7763-b944-7031e8a1c548`；主会话回传同样已归档，原Y分支/证据保留 |
| Z最终组合 | `bf65ccf`、`69d3ab6`、`2f0212a`及最终报告候选`9901b5372093e544a9077b1e9a91331d338ea149`；876/4skip＋最后23项、TS/38组件/构建、8合成＋1真实HTTP浏览器、原池2次开发探针 → 同一main | Z `01a15404-7df1-7f92-818f-e25093730b61`；主会话回传同样已归档，源码树/构建/SDK环境保留 |
| X本次切换 | 保护`e1f36c6`后ff精确已推送main，完成本节实际操作和技术验收；本报告本地提交另交主会话接入，不提前填合入号 | X `01a153df-8682-7e33-80b5-1102ee2b54c8`继续保留待所有者体验反馈，不归档 |

X未用工具向其他会话发送消息，未merge main或push；主树只做获授权的私有部署/正式入口操作，源码及本次文档编辑仍在X隔离树。旧库、代码/构建检查点、新空间、全部工作树/分支/SDK/证据保留。后续回退须正式停机后保留完整新引擎/来源/审计/伴随文件及原池，不能恢复旧DB覆盖新对话或消费，也不能切回旧直连规避同一十元池。

21:08:10收尾只读汇总仍为196/496332/unknown0、设备0会话；私有`cutover-receipt.json` SHA-256为`0f4a2558c20f4d238c1ea098e1a849dc68e9add2dc5eda4f8ce7ece185f84b5a`，不含Key、令牌、余额或对话正文。两份本轮变更Markdown正式strict通过、findings=[]；清单仅更新X主题/两份文档的现行状态与证据归属。未改源码，沿Z软件验收加本节实际运行核验，不为文档收尾重复模型测试或收费采样。

## 第四阶段：真实unknown定位与校园免费前向候选

所有者自然唤醒后反馈有字幕和声音，但说共享额度暂停；字幕/声音仅按该反馈登记通过，正常模型问答/长期记忆/插话未通过。21:43只读HTTP和原池核对确定：external_models.reason=budget_global_limit_reached，原池197次，其中196次settled共496332微元；21:41:38新增answer `0c34217080074bc28db42725f7be7c82`为unknown，held8388608、token_bound2621440、prompt/completion均null。合计8884940微元是已结算上界＋未知最坏预留，不是确认消费8.884940元；核价至22:53:33，当时未过期。

本次真实中断根因未定位：旧实现没有持久HTTP状态、失败阶段、usage/DONE证据；厂家近期日志仅能看到后续429预算拒绝，没有该笔可追溯usage。读取仅聚合时间/level/固定错误码，不输出真实正文；没有读个人源内容、猜0费用或释放预留，没有再发官方付费probe。原197条attempt及policy与本轮取证快照逐项相同，attempt元数据整体SHA为`67a48dc8aeb9d8de1941e022e8fa28f45c16bc843645d02c9c618fa154231b99`。新增诊断不能倒填该笔旧证据。

### 费用新决定及空间批准

所有者明确学校免费提供、之前已配置，要求复用校园。主会话确认该事实足以支持个人费用0策略，不再索Key或学校价目/CNY余额证明，并批准必要最小校园合成验证。只读找到原campus档案：openai_compatible、HTTP、已有allow_http=true、请求模型`DeepSeek-V4-Flash`、512 token/30秒、Key存在，端点摘要`cb27d4c3c189cb641daf59963fb9c4f0efdbed1cd34691f686c26a889b79f703`；真实地址/Key不进报告，不推断内部权重。原官方模型小写白名单不能误拒学校大写名，也不能把学校Key发往官方余额API。

主会话/Z基于X元数据核对批准前向配对：原来源8条、archived6/pending2；5轮、completed3/cancelled2；SDK memory_operations/pipeline_logs、Chroma embeddings/embedding_metadata/queue均0，可见事实节点尚无。没有读content/prompt/response。新目标`data/memory/hy-campus-daily-20261019`、`data/databases/hy-campus-sources-20261019.sqlite3`，免费审计`data/databases/hy-campus-calls-20261019.sqlite3`。原官方引擎/8来源/轮次/197账本/unknown完整保留、不改旧identity、不自动重放/迁移，旧聊天/角色旁库原位，两段来源不自动互相解析链接；所有者已由主会话获知分段限制。

### 实现与明确限制

- 复用同一ModelGateway/Runtime/HySettings，以受控profile和provider-policy区分官方原池与校园免费调用审计；不是另开十元池。免费授权与官方CNY核验分开，account_currency_verified=false；缺usage/中断仍unknown、不把token补0，但已确认免费调用不会制造付费最坏预留而锁死后续免费请求。
- selected_model保留模型大小写/端口/路径和HTTP同意；普通请求按实际scheme选择HTTPConnection/HTTPSConnection。流式同源发送、禁重定向/重试，边收边转发。校园回答512 token/30秒，Hy提取保留原显式设置。voice_budget只消费认证回环配置，不硬编码官方模型别名；网关仍要求请求模型与可信选定模型逐字相同。
- SharedBudget和免费审计可记HTTP状态、受控失败码、DONE/转发/usage出现标记，不存消息、供应商响应或异常正文，不改变金融状态。真实原unknown保持原状。
- 新关闭用例实证同步HTTPResponse缓冲读锁阻塞：原实现、仅保存socket引用、覆盖will_close的尝试均未通过原2秒断言。线程栈显示读线程仍readline，关闭线程卡fp.close；未调宽阈值或削弱unknown。最终仅流式上游采用项目原固定aiohttp3.13.2可取消读取，线程/循环由自有上下文回收，无新依赖/锁升级。这是另一个离线可重复缺陷，不声称解释了原真实unknown。
- 两个正式引擎目录各有精确.gitignore规则；X与主树git ls-files核对无个人memory数据tracked。正式免费审计属于既有data/databases忽略范围，未删除/移动/提交个人库。

核心代码已冻结为`b1f22dc421b1b6d519db1df9060c49899c87ccde`。主会话随后发现共用选择器扩展后旧V real runner可能把campus settings交给硬编码官方的verify_cny_account；明确只授权X补这一处。窄修复`e146ce22caff9d9c909a4e44401f84797776ef0e`在任何HTTP连接前共用官方scheme/host/port/path/模型校验，拒绝校园和错端点，防止校园Key发送官方。没有扩大CLI重构或调用模型。其余实现保持冻结交Z。

Z随后在合成下游停读场景复现另一关闭阻塞，主会话串行明确归X仅补这一项。X将Z原脚本复制到自己的忽略目录，修改前同样超过原2秒、须主动关客户端才退出；没有改Z树。窄修复`aaf3afc87e43301e4be50da8f4d839c65ff99649`登记自有下游socket，close只在锁内标记/摘取，锁外取消上游并shutdown下游，再等非daemon处理线程；回环socket阻塞读写有界，不改变上游模型30秒。原复现修复后约0.75秒内完成。免费/付费两种慢读者均在客户端仍连接且不读时关闭，线程/登记集合收回，unknown及付费完整最坏预留保留；没有通过daemon或放宽断言掩盖残留。代码再次冻结，未顺便改其他实现。

### 本轮实际验证

| 检查 | 实际结果与边界 |
|---|---|
| 首轮免费/原池/流式/消费配置/真实厂家SDK定向 | 29 passed，4.86秒 |
| 实际SDK生命周期及预算组合（关闭窄修复前） | 43 passed /1 skipped，56.19秒；含校园合成提取→重启→召回、管理scope及官方unknown原样保留。skip为未显式绑定实际BGE根目录，随后真实校园探针实际使用主固定CPU BGE |
| 最后HTTP流式/关闭定向 | 18 passed，5.95秒；HTTP真实端口/API前缀/大小写、普通SSE、增量tool_calls、空choices usage、缺usage后继续免费调用、关闭中断/重开保留unknown；实际厂家提供器＋小智Python3.10 SDK在200及上游400均只请求一次、max_retries0 |
| 较大受影响组合 | 902 passed /5 skipped /1 failed，148.52秒。唯一失败为未改Tk测试test_boolean_option_uses_explicit_live_state_instead_of_checkbox_glyph初始化报TclError invalid command name tcl_findLibrary；该测试及launcher/app.py相对8298无差异，随后同一精确用例独立1 passed/0.17秒。保留组合失败，不因独立通过称全组合全绿，不改GUI或加skip |
| 跳过说明 | Windows测试符号链接权限、Otto未绑定素材、旧桥默认只在X查厂家源码/环境两项，以及未为pytest设实际BGE根目录。显式3.10 SDK/厂家测试已运行，真实探针已加载固定CPU BGE |
| 官方余额入口窄守卫 | e146ce2上25 passed/0.26秒；8种校园/错误端点或模型均在构造连接前拒绝、0网络/Key不外发；其余为原预算与免费策略定向。未重跑较大组合或收费模型 |
| 下游慢读关闭窄修复 | aaf3afc上20 passed/7.36秒，含真实HTTP/厂家SDK、上游取消、免费/付费慢读者、缺usage/unknown及CNY守卫。Z原脚本X复制版前失败/后0.75秒的收据均保留；未再跑大组合或校园/官方真实probe |
| 最小真实校园验证 | 首次仅合成短句协议探针200/真实SSE/usage/DONE；随后隔离实际SDK+固定512维CPU BGE完成1条新合成事实提取、重启召回，再经网页回答与圆屏SSE同校园网关完成，共3次审计调用，无unknown。合成问句取消保留、不为采样再提取；内容/实际token只留忽略目录，不进公开报告，不重跑V dev/holdout或宣称校园17题成绩 |

本轮准确私有收据根在X `data/test-tmp/x-campus-repair-20261019/`：`validation-summary.json`、`campus-probe-receipt.json`、`campus-runtime-live-receipt.json`与`handoff/receipt.json`。最小真实闭环归属b1f22dc；e146只加官方余额预检，不改校园传输/身份，不伪称再次联网测了校园。候选provider身份`92fdc37ee5f7f435d9e0f985508455c000fbcb433faf52fa1d051c14613ab683`，settings身份`78506bce149bb51ccedb4c8563a8d35597cd2d4c0c21972e98160c037090d04a`；管理RPC仍c0bf摘要。handoff含deployment/settings/provider-policy/management-verification四候选文件逐项摘要，未写入主配置。

最后代码为aaf3afc（含b1/e146）；新增`downstream-close-receipt.json`记录原样复现前后的路径/结果和20项定向，validation-summary已追加两笔窄修复的精确归属。最小真实校园probe没有因窄修复重复调用。代码与文档提交分开，Z可按精确代码串行复核，不将文档等待当实现继续修改许可。

本节交付时生产仍为main729590c官方空间、模型暂停；没有提前部署候选、改profile指针、启停服务或碰原197笔费用。主会话已把b1/e146/aaf3交Z隔离终审；收尾文档另提交，待Z结论/已推送精确main交接后X才独占受控部署。届时先新一致性检查点、核对批准新目标不存在、切换同一免费网关、一次create、同Runtime/审计/保护核验；失败暂停候选并保留所有空间，不恢复官方直连。决策见[ADR-0186](../../adr/0186-owner-confirmed-free-campus-and-forward-state.md)。

本轮文档收尾：5份受影响Markdown正式strict通过，findings=[]；新增ADR-0186及校园主题，配置/排障/指南只同步当前边界。候选SDK解释器摘要仍560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e，requirements.lock仍706ce91ace29062d86a73db6a5845d9081e5e5b87660f52de8737d6c7f0345d7，管理c0bf摘要不变，已实际重算入handoff收据。文档本地提交与代码aaf3分开；未提前填校园main、部署/实机通过。

## 第五阶段：校园正式技术切换

2026-10-19 22:18接主会话正式交接，最终候选`cdf8ffa0f969f15b7a0437fbdb7f594d215a75e8`已由协调会话merge --no-ff为main **`6d12559bc3b883cce8d439fab022ddcf72aa588a`**并push。X独立核对ls-remote同SHA、main与cdf完整tree相同；保护X旧HEAD到`codex/x-campus-pre-cutover-20261019`后仅ff该main。源码保持冻结，没有再跑模型/旧大组合或改源实现。Z此前对aaf3原慢读脚本在客户端仍连接停读时0.765秒关闭，原2秒门槛及20项复核通过；CNY零网络拒绝、免费/付费unknown保留均核实，主会话明确放行。

### 新检查点与实际部署

新私有检查点`local/archive/hy-campus-cutover/20261019-221946/`，最终`checkpoint.json` SHA-256 **`7a3a5c83d7777d17a9c3840b1598ec70c7596824a4b4a3aa8c45828a742b119a`**。先核对自有launcher PID16840和精确后代、无用户活动会话，保存69份配置/偏好/声音与所选参考文件/消费副本/提供器/44份构建等文件及旧729590c源码归档。预停止比较第一次把动态launcher-status快照纳入稳定比较而中断，实际仅该正常刷新文件变化、没有发停机动作；核清人工配置稳定后正式shutdown一次，不重复启停或强杀。

确认旧launcher/自有API/SDK/语音/声音进程和端口释放后，才复制完整旧官方Hy目录10文件及伴随文件，逐文件SHA相同；其中2份SDK SQLite完整性检查通过。另用SQLite backup取得旧个人主库、聊天旁库、原官方来源库和原预算池4份一致性副本，完整性/每表计数匹配；原角色旁库仍不存在，按缺失记录保留。官方来源仍8条/5轮，原197次attempt和policy逐项等于第四阶段快照，含unknown及续价审计，不改旧identity或重放pending。无关回环8768 PID49284未动。

四份handoff文件逐项重算后同目录原子替换deployment/settings/management-verification并新增provider-policy，保留原人工env/Key和官方price-verification。web/voice指针同选campus，原HTTP同意已保存true，没有索Key、调用官方余额或续官方价格。批准的新引擎/来源/审计三个目标均原本不存在，显式create一次；画像scope、两个owner、管理能力和7850身份通过，免费审计0次，来源/轮次0。干净关闭后另留新空引擎全目录及来源/免费审计的初始一致性备份，再由正式入口重开已有空间，没有删库/随机换目录重试。

前端沿原已验包44文件/1759035字节/整体`588fdcc014fe571de451b81de223bb61263952eb7732e410c0dabe2a0613e8a4`，逐项核对不变，没有重建。唯一根`启动智慧圆屏.cmd`打开新launcher，认证受限动作start只请求一次；实际启动API+SDK+小智+CosyVoice3，22:25:28正式ready。

### 技术验收与保护

| 本轮实际检查 | 结果 |
|---|---|
| 正式服务归属 | launcher64040；API/网关60348、专属SDK22084、语音57832、CosyVoice24192均为本次launcher后代。API8767、语音8766/8000/8003、CosyVoice18770及本次局域网8768监听；原无关回环8768仍为49284 |
| 正式Hy身份 | 实际chat-config与memory-engine为hy_memory_pro_chat、sdk-2.0.3-adapter-1，settings身份78506bce149bb51ccedb4c8563a8d35597cd2d4c0c21972e98160c037090d04a，新source及新引擎路径均准确；provider身份92fdc37ee5f7f435d9e0f985508455c000fbcb433faf52fa1d051c14613ab683；首次scope摘要674a3e8597764c8893d2937a55b82201f48f4aa03611c208dd2fc226121626af |
| 调用政策与三链路接线 | available、owner_confirmed_free、personal_cost_micro_cny0、account_currency_verified=false、official_budget_reused_or_released=false。web/voice配置指针同campus，实际回答器/语音消费同回环网关38242的answer/voice路径；模型逐字为DeepSeek-V4-Flash，回答512 token/30秒。Hy worker仅领取同网关hy端点，SDK及管理实际版本由可信装配核对 |
| 管理/主动边界 | scope及两个owner在实际初始化核对，正式Hy workspace profile/history/correction/deletion true，native_atomic_revision false；通用原子写能力仍false。旧主动paused_backend_unsupported，整理/影子不启用 |
| 技术验收时计数 | 22:24—22:25免费审计attempt0/unknown0，新用户来源/投递/轮次/反馈均0，未向新个人库注合成、代发问答或播放；这不是要求后续所有者真实输入仍为0 |
| 保护 | 原两env、人工YAML、launcher/tts/backend偏好、声音/参考WAV及元数据、皮肤配置、官方核价文件SHA不变；仅模型指针和4份已授权Hy配置切换。消费YAML只替换选中LLM，将其还原后其余结构与人工来源相同。旧官方目录所有文件SHA不变，旧主库/旁库/官方来源/原预算每表计数不变，197条attempt与policy逐项不变；壁纸/绑定/设备固件/串口未操作 |
| Git保护 | 主树两正式Hy目录、原/新source和新免费审计三SQLite均命中精确/既有忽略；git ls-files在memory无记录、databases仅.gitkeep。原主树其他未跟踪用户材料保留，没有个人库tracked或提交 |

主会话随后独立只读复核正式8767的校园身份、web/voice=campus、available/0个人费用/未核账户币种/attempt0/unknown0/未复用官方池，未调模型或写个人来源；已交所有者自然唤醒验收。22:25设备控制面仍0会话，沿第四阶段源码核对不能据此判断Wi-Fi故障。原先所有者字幕/声音反馈属于官方阶段，不代替这次校园正常回答；正常回答、真实偏好跨轮召回/来源、纠正及插话仍由所有者随后验证，X不代测或读取正文。

本次实际私有收据：同检查点`installed-campus.json`、`campus-initialization.json`、`live-campus-verification.json`、`startup-latest.json`和`campus-cutover-receipt.json`；最后一份SHA-256为 **`306157140a3d615431366e15d3d984770b4e6a240396779f3cbbcf269eee2b7d`**。它记录技术验收时刻的0计数与保护关系，不随所有者后续活动重写成“合成污染”。本轮助手模型/余额请求0，不对官方核价续期，不改其unknown。

追溯：V/Y原软件提交→Z组合；X b1f22dc＋e146ce2＋aaf3afc→Z关闭/20项终审→文档cdf8ffa→主会话main6d12559并推送/独立ls-remote核对→X本节实际切换→本地部署记录提交交主会话整合。V会话01a15363-8120-7400-a9db-8f9142104b12、Y会话01a153e0-5cf5-7763-b944-7031e8a1c548保留原已归档软件记录；Z会话01a15404-7df1-7f92-818f-e25093730b61本次软件已验收/合入无待工作，主会话可归档，树/SDK/证据保留。X会话01a153df-8682-7e33-80b5-1102ee2b54c8保留待所有者真实反馈，不归档。X未merge/push，源实现冻结；若后续失败，正式停候选并保留所有新旧库/来源/审计/账本，不能清unknown、恢复旧DB覆盖新增内容或启用官方直连。

所有者实机反馈补记（2026-10-19，主会话转达）：校园切换后按平常方式自然唤醒说你好，明确反馈“能正常回答，字幕和声音正常”。仅按此范围登记正常校园模型回答、字幕和声音验收通过，原官方额度暂停对当前日用的阻塞已由校园切换解决；不据此认定原unknown根因已定位或费用已结算。长期记忆形成→跨新会话召回→来源核对、纠正及插话仍未验收，X保留待反馈、不归档。本次仅窄文档记录，没有访问服务、读取个人正文、模型调用、测试或启停。

## 第六阶段：换址与双设备端口冲突诊断

2026-10-20 主会话交接所有者截图：启动器“需要处理，受管服务配置检查未通过”，网页失败、声音/语音停止。X只读核对main/X均84048dc、X干净；13:25两笔configuration_rejected耗时282/93毫秒。偏好仍为192.168.120.106，本机以太网已为192.168.120.4，旧地址不存在。18767为正式launcher，8767无监听；8000/8003由Docker Desktop后端53048监听，其父链为Docker后台，非launcher后代。只读docker ps确认容器xiaozhi-local-xiaozhi-esp32-server-1映射0.0.0.0:8000及127.0.0.1:8003。所有者随后澄清该Docker小智连接另一设备，主会话明确保留运行。未停容器、改私有配置、启停服务、访问个人库、调模型或打开串口。

结论分层：旧LAN失效本身足以阻断圆屏启动，改IP后8000仍有独立冲突；这两项是现场事实。底层绑定预检原有原因文本被React控制器统一捕获ValueError覆盖，导致界面只有通用配置失败。旧事件未保留具体OS错误码，不能宣称逐笔还原了10049或10048；也没有模型/记忆/TTS故障证据。

错误展示窄修复代码提交 **`13c3c03`**：runtime新增只由规范IP/端口和固定原因组成的AddressBindingError，分类lan_address_unavailable/port_in_use/bind_denied/bind_failed；controller仅对此类型展示受控文案，其他异常继续通用脱敏；events白名单记录分类，不含IP。没有自动选网卡、迁移端口或停止外部服务。源码来自X，现有主venv只用于执行合成测试：tests/test_launcher_web.py＋test_launcher_events.py **31 passed/7.07秒**；test_launcher.py绑定/占用/自有进程回退定向 **10 passed、73 deselected/0.42秒**。11项新增覆盖固定原因、系统错误正文不泄露、事件无IP、失败后无受管服务；原通用ValueError敏感正文防泄露继续通过。没有重跑模型或旧大组合，不声称远程CI通过。

两设备共存方案交主会话决策/分工，**尚未实施或部署**：建议本项目WebSocket/OTA-HTTP采用18000/18003，原Docker的8000/8003完全保留；当次只读未见候选新端口监听，不等于可绑定、无系统保留或防火墙通过。上游websocket_server/http_server已有server.port/http_port支持；项目setup.validate_config则强制8000/8003，sync_network固定生成对应URL，故仅手改私有YAML会被启动拒绝。最小实施须贯通偏好→Options→controller→runtime预检/voice参数→voice.py/setup校验→受控网络同步五字段（ip/port/http_port/websocket/vision_explain）；沿用旧默认兼容，校验端口合法/互异/不撞当前内部端口，拒绝bool和未知字段，不改上游源码或依赖。React可在启动设置明确选择本项目端口，旧Tk读取相同选择或明确拒绝不支持，不能悄悄退回8000。view_model/防火墙诊断/旧恢复入口需反映实际选择，旧恢复工具若尚未支持新端口应拒绝操作，不扫描/停Docker。只扩这两个LAN端口；回环8766控制桥及实际ready/鉴权、8767网页、LAN8768壁纸与18770声音保持原约束。Doubao等未覆盖模式应保留默认或显式拒绝，不能假称此次已验证。

设备步骤依据本地固件：ota.cc读取wifi.ota_url，OTA响应写websocket配置，websocket_protocol.cc读取websocket.url；managed_components/78__esp-wifi-connect配网页已有Custom OTA URL及保存处理，板型现有EnterWifiConfigMode入口。没有读设备NVS、假设其当前值或把源码当当前在线证据。实施/技术验收后，所有者经圆屏既有配网页将自定义OTA设为`http://<当时核实的电脑LAN>:18003/xiaozhi/ota/`，按屏幕提示保存并重连；由OTA下发`ws://<同一LAN>:18000/xiaozhi/v1/`。当前.4只作当次候选，需确认圆屏同网可达，不能自动选多网卡。无需新固件/串口/NVS直写、修改另一设备或Docker；不要求清Wi-Fi/壁纸/绑定。若配网入口现场不可用或防火墙缺必要授权，报告具体阻塞，不扩大操作。

完成标准：合成验证默认兼容、新端口端到端传递、仅预期YAML字段更新/并发备份保护、端口冲突不动外部服务、控制鉴权与壁纸不变；主会话审查合入后，再独占交接配置备份/一次正式启动，核实LAN新端口归属与API/控制/声音身份、Docker原映射与另一设备服务仍保留。所有者最后自然唤醒确认字幕/声音/连接，记忆与纠正/打断沿原待验收清单继续，不提前登记通过。X本轮仅提交自己的分支，无merge或push，配置/服务动作继续暂停。

## 第七阶段：独立端口与自动 IP 候选实现

2026-10-20 所有者通过主会话明确授权：给本项目独立端口、检测电脑IP变化后自动更新，并希望两台设备共存；需要改圆屏地址时提供具体步骤。Docker小智连接另一台设备，整个本轮不停止/重启或修改其容器、映射、网络、配置与数据。主会话另派V隔离负责等待提示/首答时序；X不改voice_waiting/voice_latency、模型、声线或Hy质量策略，后续正式部署等精确整合SHA统一交接。

### 实现与边界

代码 **`04f92df140983ca6fd8ac552157be7812c1b1b9b`** 贯通语音WS/OTA-HTTP独立端口，部署目标18000/18003，保留旧默认8000/8003兼容。偏好版本7、Options、controller校验、命令/voice参数、网络同步、setup严格校验及实际消费链一致；拒绝bool/字符串端口、重复或内部冲突。8766桥、8767网页、8768壁纸、18770声音等保留。旧Tk读取新端口但自动网络模式要求React；旧恢复和防火墙工具遇新端口明确拒绝，不去8000找另一应用。新增LAN探测缓存5秒，没有每轮初始化或模型/网络探针。

network_watch用现有PowerShell只读枚举在线物理网卡首选RFC1918 IPv4，排除虚拟/回环/CGNAT/链路本地等。唯一明确候选可记录GUID身份；之后只跟踪同一网卡，不在断网时切到另一卡。无网/多候选/未知身份只提示，手动输入目标物理IP可重新选择。实际只读发现1个候选192.168.120.4；新端口当时无监听，netsh仅显示50000–50059的IPv4管理排除段，未覆盖18000/18003；这些不是正式可绑定或防火墙验收，部署前仍重验。

监控默认30秒，不随聊天轮次触发；跨10秒稳定窗口和额外10秒可见提示后才考虑运行中重开。新面板首次无归属时仅检测，首次显式开启由正常预检/同步建立归属；只有本面板成功停止过自己服务，才允许停止态后台同步。运行中的自动重开还须自有Job、当前实例令牌、设备连接/握手/控制操作全空、网页请求及聊天后台任务完成、Runtime递延任务和网关连接/流全空、旧主动/整理/实验关闭。双端60秒静默租约在同一循环检查后加闸，阻止新请求/连接；忙或未知不停止。网页断开仍跟踪真实处理任务；语音断开后等待上游被清空前的线程池/TTS线程句柄结束，未知形态保守拒绝。观察失败不干扰原close清理，完成句柄会旁路清除，不复制正文。没有修改SDK、网关或Memory Core实现，仅在新的网络维护切片读取可信已有状态；不能证明空闲则保留服务。

成功停止后重验候选，再更新配置并重开本面板服务；停止不确认不重复停/启，失败锁定自动重试。成功自动重开至少隔60秒、每小时最多2次；外部设置revision变更不自动带入重开。运行后的健康检查短暂失败显示待确认，不错误套用90秒首次启动超时取消聊天；真实子进程退出仍失败、不会自动复活。

冻结检查发现停止态的普通消费副本重生成可能覆盖已选Hy网关投影，追加窄修复 **`8b347be37409481d8639ce18b7c38b7ebb5166df`**。新增network_copy只投影消费副本网络五字段，先核副本/回执/原人工来源摘要，备份并读回校验，再更新源与消费副本；保留已有Hy模型、凭据、角色/声音等全部非网络字段，不生成普通直连回退。人工来源或副本被改动时在写源前拒绝；正式启动再领取当次新网关。该修复不读取费用账本、迁移来源或创建新空间。

### 实际验证

| 检查 | 本轮实际结果 |
|---|---|
| 最终代码组合 | 8b347be上13组pytest：**393 passed / 1 failed，23.77秒**。唯一失败为旧Tk用例test_secret_dialog_is_blank_and_saves_only_on_user_action在tk.Tk()初始化报找不到可用init.tcl，未进入对话框断言；该用例及密钥对话框实现未改，app.py本轮只改网络入口。没有删/跳过该测试、修改全局Tcl或把组合写成全绿 |
| 隔离复核 | 同一精确Tk用例＋网络/维护专项 **43 passed，0.57秒**；其中网络37项、维护5项。保留上行组合失败，不由隔离通过替代 |
| 网络覆盖 | 默认/独立端口、真实随机回环两套端口共存且外部监听不动、人工YAML/消费副本五字段与Hy投影保护、幂等/并发摘要、单/多/虚拟/无候选、物理身份、断网恢复、忙/未知不停止、去抖/冷却/失败不重试、ready短暂掉健康、检测不随tick/轮次重复、未知Job拒绝 |
| 维护HTTP/线程 | 真实随机回环HTTP校验令牌/实例/Origin、活动请求/后台/设备/握手/锁拒绝、加闸/释放/过期；客户端取消仍在执行、语音close清空executor但线程未结束时不认空闲；Runtime递延任务和网关连接/流忙则拒绝 |
| Python3.10 | 小智实际Python **3.10.20**只在合成受管目录执行网络源/消费投影，模型保持synthetic-campus且18000/18003正确，0模型请求；源导入来自X。另原transport_probe以固定上游MCP Future＋独立CLI/随机HTTP/模拟设备回执全通过，不是真机命令 |
| 前端 | 现有锁定依赖复制到X独立副本，632个联接全部重定位到X内部，`.bin`绝对引用也仅改副本；没有共享可变node_modules、安装或下载。Node **24.19.0**直接调用锁内工具，Vitest启动面板 **13 passed/37.98秒**；tsc --noEmit及Vite **8.2.2**构建通过（5.30秒，有既有大chunk警告）。全局pnpm入口只读为12.9.1，本轮未用它安装/构建、未修改锁或全局环境，不假称运行了pnpm11 |
| 浏览器 | 已安装Edge＋真实随机端口PreviewController、确定性替身 **5 passed/11.5秒**，含390窄屏独立端口/自动IP设置、保存不启停、键盘/减少动画、原启动停止闭环；已看截图，不是真实设备/语音验收。测试主机已退出，无本次X playwright_launcher残留 |
| 构建 | 44文件/1760568字节，按相对POSIX路径＋NUL＋文件SHA＋LF排序摘要 **5009aaac54c5d1f7f9740a6082d27727e200272b9a33c9a997bf0c3569cac01b**；产物在X web/react-chat/dist，未复制正式dist |

最初新网络测试曾把网络字符串规范加引号误要求为原字节完全相同，修正为网络语义等价并独立断言非网络字节保留；原启动器健康替身也补上本次选中LAN端口探测，禁止触碰日用端口。实现修复优先，未修改既有Tk测试掩盖其环境失败。先前284/130等组合属于中间阶段，最终交付以上表精确代码与结果为准；未跑真实模型、BGE/SDK个人空间或远程CI。

本次私有证据根为X `data/test-tmp/x-network-20261020/`，含python310-network-copy.json、Playwright报告和screenshots；前端构建/锁及最终源码摘要汇总由validation-summary.json记录，SHA-256为 **2a28bcd6362f7ce69556aedea1324801bd7c1fa19c05c71210b1c2317f3ba379**。合成n310目录只含伪造配置，不引用个人库。文档按project-doc-maintenance窄维护，新增[ADR-0187](../../adr/0187-roundscreen-network-coexistence-and-auto-lan.md)和[操作指南](../../guides/圆屏独立端口与IP自动跟踪-20261020.md)，6份Markdown正式strict通过、findings为空；37份本轮公开变更的密钥字面量定向扫描无匹配，不替代完整安全审计。没有改根README/ROADMAP/CHANGELOG。

### 设备限制、交接与未验收

只读本地源码/构建：ota.cc读取wifi.ota_url，websocket_protocol.cc读取websocket.url，OTA可下发新连接；配网页Advanced有Custom OTA URL并保存、但不自动重启。板型在启动未连Wi-Fi时轻触或短按BOOT可进入配网，已联网时普通点击仅聊天；不能假称任何状态均可点击配网。构建头文件启用MDNS_QUERIES仅为基础，主环境没有zeroconf/项目发布器，未验证Windows发布到ESP解析的完整稳定主机名链路，未安装、配置DHCP/DNS或写全局网络。电脑IP自动更新不等于设备旧数字OTA会改变，将来再变IP仍可能需要所有者改址。

具体所有者步骤已写入指南：正式服务新端口就绪→目标圆屏现有配网热点→高级选项填写部署时实际`http://<LAN>:18003/xiaozhi/ota/`→保存成功后正常重启原Wi-Fi→OTA下发`ws://<LAN>:18000/xiaozhi/v1/`→设备页和自然唤醒检查。当前.4只作当次候选，正式部署重新确认并交完整URL。入口若现场不可用则反馈实际屏幕，不恢复出厂/清SSID/壁纸、不刷固件、开串口或直接写NVS。

本轮未改正式私有配置/偏好/消费副本/构建，未启停正式服务、Docker或设备，未访问个人库或费用表；没有把“未操作”伪称重新逐字节验收。保留当前Hy校园与所有数据/来源/免费审计、官方197次及unknown、角色、声音和壁纸。主会话审查精确SHA并结合V语音候选后，再交X独占正式部署：核对所有权/活动与新端口→新检查点→只停自有服务→设置独立端口/自动模式并同步→复制已验构建→一次正式开启/技术核对→所有者设备改址及双设备/声音/字幕实机验收。这个部署已有授权，无需重复向所有者确认；当前仍等待主会话交接，X不merge/push或给其他会话发消息，不归档待办X。

## 第八阶段：独立端口、同声线缓存的正式部署

2026-10-20 主会话授权X唯一维护正式配置和服务。Z整合放行后，主会话合入并推送 **08836d404787469d76609a6be1e96452f991b5bd**；X只快进自己的工作树到该精确提交，核对源码和构建，取得新检查点后正常退出旧失败启动器。正式独立端口已改为18000/18003，开启自动IP跟踪，绑定当次唯一物理以太网192.168.120.4的规范GUID；受控同步只更新网络五字段，保留Hy消费投影。部署第七阶段已验44文件/1760568字节前端，摘要仍为 **5009aaac54c5d1f7f9740a6082d27727e200272b9a33c9a997bf0c3569cac01b**，旧dist完整保留，没有安装或更新依赖。

### 缓存失败与精确补丁交接

第一维护窗口仅TTS就绪且档案摘要匹配后，按批准命令准备原两句。服务日志分别记录1.68秒和3.4秒，后一条超过35个60ms帧上限，程序拒绝整套发布；没有部分缓存或默认声线回退。原合成WAV只在内存、未留存，不补报其精确样本数、帧数或静音跨度，也没有重合成旧句。主会话随后单独授权一次“稍等。”探针：完整24kHz/31680样本/1.32秒，16/24kHz均22帧；私有WAV仅供离线数值分析，没有手工发布为缓存。10ms RMS（均方根能量）阈值−60/−50/−40dBFS的首活动时间为0.09/0.13/0.56秒，末活动结束为1.21/1.19/1.18秒；这些不是词边界证据，没有裁静音、裁词或改速。

前两次真实链路探针在临时脚本的WebSocket参数、绑定端口与Host校验处失败。两个独立合成审计均为0次外部调用、来源消息/轮次/投递均0；保留失败收据，没有把它们计为模型或性能通过。修复仅在X忽略目录的测试脚本，没有放宽产品鉴权。X先恢复088正式实例，保留等待未ready结论，避免继续停机。正式校园审计仍为2次/unknown0，非本轮助手探针调用。

V实施中性短句与新配方身份、Z审查后，主会话明确交接已推送精确main **cb3c6d57bc0b7f4d7e5def88ea04016a1a5e41ba**。第二维护窗口先两次核对设备0连接、网页无processing、记忆无等待/运行队列、模型无unknown/inflight、TTS无请求，核对全部本项目监听是旧启动器后代。取得新的当前检查点，正常退出088整套，再只启动自有维护TTS。X没有合入main、推送或修改正式产品源码。

新配方 `opus60-neutral-wait-v2` 按正式脚本一次合成完整“稍等。”供model/web复用，返回 **ready/items4**。服务记录本次完整1.32秒；正式波形全长≤2.1秒与编码≤35帧双守卫通过，`cached_packets` 对新完整身份的model/web×16/24kHz四组全部非空、均22帧。未沿用旧recipe、旧探针WAV或公共默认素材。声线档案摘要从维护health到正式health均匹配；参考WAV、元数据和角色保留。

### 最小真实隔离探针及限制

第二窗口串行完成一次修正后的真实校园模型＋本地TTS探针：真实3.10 MemoryProvider经随机回环HTTP调用3.12 Runtime与真实Hy SDK，真实BGE/校园网关流式回答、当前声线cache=false合成、真实Opus编码并经随机回环WebSocket发送。使用X忽略目录下全新合成user/agent、state/source/policy/free ledger、诊断目录和端口；真实凭据只在父进程内存，子进程仅获得临时回环令牌。没有调用日用API聊天/个人来源或日用审计，没有访问官方余额、释放unknown或重放来源。

同一连接逐轮取当前token、`stage_snapshot()`、当前v6计时和`WaitingTurn.snapshot()`；同一次`_runtime_request`旁路取得记忆阶段，不多做prepare。答案在发送编码前标记为AnswerPacket，未把任意首个二进制包当答案。探针整段合成短回答，不执行生产首段切句或等待提示发送；真实探针cue帧数0、first_feedback为null，不能据此验收等待听感。

| 从文本chat入口起算，毫秒 | 合成偏好陈述，首次探针 | 同进程后续偏好提问 |
|---|---:|---:|
| Memory请求→返回 | 4→9904 | 2→849 |
| Runtime内部recall / total | 9885.548 / 9889.768 | 17.335 / 21.438 |
| 模型首个文本 | 10525 | 920 |
| 完整短回答可合成 / TTS开始 | 10540 | 971 |
| 首个真答案Opus就绪 | 11968 | 2733 |
| 真答案首包WebSocket发送返回 | 11984 | 2759 |
| 召回合成记忆 / 答案帧数 | 0 / 25 | 1 / 44 |

Runtime装配5339毫秒，维护TTS模型加载8.908秒、基础预热1.974秒，单独记录，不混入表内。缓存准备已预热当前声线，两个问题不同、库状态随合成轮次增长；没有完整模型冷启动样本，不能把第一列叫全链路冷启动，也不能由两列计算稳定提升、p95或等条件对照。ASR和扬声器播放均null，发送返回不等于真机听见。合成免费审计最终5次、unknown0，原正式免费审计仍2次/unknown0。

另用固定上游AudioRateController及当前实际等待发送适配器做零模型/TTS的受控时钟注入：22帧提示下答案在0/120/900毫秒就绪，真答案分别在0/120/900毫秒送出，提示已发送0/2/15帧，未发尾包不继续消耗时间槽。取消轮提示和答案、旧轮答案均丢弃，只送当前轮答案。这是队列和归属检查，不是真机播放/插话验收。

### 最终正式状态与保护

维护Runtime/网关及TTS自有Job均关闭并核对释放后，仅从根`启动智慧圆屏.cmd`开启cb3整套。最终launcher **48740** ready；API/壁纸 **44800**、语音 **53832**、CosyVoice **41764**均为本次启动器后代，监听回环8767/8766/18770、LAN8768/18000/18003。自动网络状态稳定于192.168.120.4；未实改IP、制造断网或验收真实换址重启。

实际API为`hy_memory_pro_chat / sdk-2.0.3-adapter-1`，state identity仍`78506bce149bb51ccedb4c8563a8d35597cd2d4c0c21972e98160c037090d04a`，web/voice仍campus，模型`DeepSeek-V4-Flash`，角色`elysia_v1`，TTS当前自定义CosyVoice3。启动会话`allow_memory_delete=true`已保留，Hy workspace的profile/history/correction/deletion为true；通用原子修订能力及通用allow_delete仍false，不能混为权限回退。旧主动交流/整理/影子不开启。正式TTS健康、档案摘要及四组22帧新缓存均重新核对通过。

两个已完成检查点分别为主项目`local/archive/vx-cutover/20261020-143111-8b313b/`与`20261020-144601-da4851/`，各20份私有配置、26份数据原文件、10份SQLite一致性备份均核验。保留旧dist和两精确源码档案；保护16份未授权改变的私有文件以及旧官方引擎文件、当前/旧来源、日用免费审计、主库/聊天旁库和原官方预算文件SHA，官方attempt197/unknown1/held8388608及policy摘要未变。当前Hy引擎启动元数据不要求原字节不变，未用备份覆盖或迁移任何个人库。Docker四容器完整ID、镜像ID、StartedAt、RestartCount和端口映射与首次基线一致；没有停止/重启容器、改网络/防火墙/DHCP、设备/串口/固件/NVS操作。

最终私有独立核验入口在第二检查点：`idle-and-ownership.json`、`data-backup.json`、`waiting-cache.json`、`cache-preparation-bounds.json`、`synthetic-probe-final.json`、`controlled-wait-cancel.json`、`probe-runtime-stopped.json`、`tts-maintenance-stopped.json`、`formal-restored.json`。早期失败和088恢复收据在第一检查点，保留，不改写为全通过。技术核验时设备连接0、所有者尚未改址；[网络指南](../../guides/圆屏独立端口与IP自动跟踪-20261020.md)交付 **`http://192.168.120.4:18003/xiaozhi/ota/`**，由设备取得`ws://192.168.120.4:18000/xiaozhi/v1/`。随后所有者实机反馈见下段，不回填当时收据。长程记忆/纠正的原实机待验项保留，不以合成召回替代。X只交自己的窄文档提交，由主会话独立复核和整合；本会话保留待验项，不归档、不merge main或push。

本次汇总`completion-receipt.json`的SHA-256为 **204139bdfbea9131e55c2af96b05a5264c42b34b4da1214ff3d01f33b7f78e12**；正式恢复收据为 **e52bcb5e830836f28f0cf4a6dde804f049145e45ea3d297e8da77ae7b9c8eb21**，真实探针收据为 **d7e931a08d7a3b1667a03fb920bbd3876dae7a544be69303758e79096efb549a**。X记录和两份指南的窄范围strict文档检查3份通过、findings为空；四份公开变更的密钥字面量定向扫描0匹配、diff-check通过，不冒称远程CI或全量安全审计。主会话随后独立复核正式ready/校园身份/日用2次unknown0/四组22帧/Docker保持，并开始交所有者设备步骤；从该时起X只读和文档收尾，不再为测试停服务或准备缓存。上述设备0连接是本次技术核验时点，不要求所有者随后连接仍为0。

所有者本轮实机反馈（2026-10-20，主会话直接转达）：将目标圆屏OTA改为本次`.4:18003`、保存并正常重启、说你好后，明确回复“改址后正常回答，字幕和声音正常”。仅据此登记目标圆屏新端口连接、正常问答、字幕和声音验收通过。没有读取真实聊天正文、代发设备对话或再停启。等待提示实际听感、插话、跨新会话记忆形成/来源/纠正仍待验；Docker四容器及映射保持属于软件核验，另一台设备的实际体验未获所有者反馈，不能一并登记通过。

所有者随后实机反馈（同日，主会话直接转达）：本次指定知识问答“回答时间很快”“这次延迟变低很多”，插话“可以暂停”。据此补记该题回答主观明显更快、插话可暂停按所有者反馈范围通过；没有精确计时或等条件对照，不把主观感受换成秒数/百分比，也不归因某个改动。此前两轮隔离宏观数值及其限制保留，不用本次反馈替换首轮约12秒结果。快答中未明确听到“稍等。”，等待提示实际听感仍待较慢自然轮次，不判失败或通过。所有者另明确另一设备不在身边、其他人在用、“不用管”，取消额外实机验收要求；不再追问或操作该设备，保留Docker未改/映射核验事实，不将他人在用写为所有者完成体验验证。跨新会话长记忆、来源和纠正仍未实机验，X保留不归档。本次仅补文档；未读取用户对话正文、调用模型/TTS、准备缓存、启停服务或操作设备。

## 第九阶段：声音疑问与实际路由归属更正

2026-10-20 所有者质疑实际是否用了CosyVoice，并报告听到台湾腔。主会话要求X只读核对自有链路，随后统一安排所有者再说一次“你好”；X没有代发、重启、换声线或操作设备。14:58:28与受控问答后的14:59:03两次核查，正式启动器48740、语音53832、TTS41764、API44800均仍为本次原进程，创建时间分别14:47:37、14:47:59、14:47:42、14:47:42。TTS健康ready/provider=cosyvoice3、当前档案摘要匹配，只证明本机服务准备状态。

实际计数证据：两次TTS `speech_requests`均0，内部诊断累计llm_job/flow/hift各1且未变；API收到的语音轮次0，设备连接0、ready=false、保留的voice_latency与当前voice_feedback均null；正式校园审计仍2次/unknown0、token累计也未变。该语音进程使用的本项目server.log最后写入14:48:07，按14:47:59进程创建时间过滤仅15条启动期记录，没有匹配到设备连接头、OTA POST设备请求/下发配置或语音阶段事件。日志原始头、正文、MAC和凭据未输出/复制；OTA GET成功路径没有常规访问日志，因此不把日志缺失当作完整HTTP抓包证明。

这些证据说明受控这次回答没有经过当前本项目Cosy HTTP服务，现有资料不能确认设备连到了本项目18000/18003。**更正第八阶段及其后文档的验收归属：所有者确实听到正常回答、字幕/声音，主观觉得指定题更快且可暂停的反馈保留；此前将其直接归属为本项目新端口/Cosy链路已验收，证据不足，撤回该归属。** 不能凭口音猜实际是Edge或某个云端引擎；实际引擎/服务器尚未查明。本机部署ready、四组22帧缓存、独立合成探针和Docker保护核验仍是各自已验证的软件事实，不因本次路由未确认而改写历史或合并成设备体验通过。

只读核对本机固件源码：`ota.cc`先取`wifi.ota_url`，空值才用编译默认；配网页`/advanced/submit`只保存该OTA URL，不直接更新`websocket.url`。成功取得HTTP200并解析到websocket对象时才把响应字段写入websocket命名空间，缺该对象不清理旧值。`WebsocketProtocol::OpenAudioChannel()`读取已存`websocket.url`，不会自动把OTA URL当连接地址；Application选择OTA返回的MQTT优先、其次WebSocket、无协议配置则默认MQTT。因此保存OTA成功本身不足以证明实际已换服务器；也不能简单断言失败后一定沿用旧WebSocket。本次未读取设备NVS或抓包，上述仅解释代码可能路径。

最小证据收据在X忽略目录`data/test-tmp/x-routing-audit-20261020/snapshot-145828.json`和`after-owner-145903.json`，只含受控计数/时刻/事件分类。下一步由主会话统一安排所有者核对目标设备高级页实际保存URL、同网访问本项目OTA的可达性，并在必要的一次正常冷启动期间观察本项目OTA POST、匹配设备的WebSocket握手和随后TTS计数，先证明路由再判声线/问答/打断。X不再次自行要求重复说话、不改防火墙/配置或重启，不检查或操作另一Docker项目/设备；另一设备取消额外实机验收的决定继续有效。等待听感、长记忆/来源/纠正继续待验，本项目设备链路的声音和打断归属也须重新以实测路由确认。

主会话随后统一询问目标设备高级页读回值，所有者提供`http://192.168.120.4:18003xiaozhi/ota/`：端口18003后缺少`/`，与预期`http://192.168.120.4:18003/xiaozhi/ota/`不同。此为所有者读回/转述，保留人工转录误差可能，不写为助手读取设备NVS。该明确格式差异作为无自有请求的优先排查项；主会话已要求完整替换、保存并正常重启再说你好，实际接入仍以纠正后本项目OTA/WS/TTS/审计增长为准，尚未登记通过，不据此猜实际MQTT或TTS来源。既有配网页只读`GET /advanced/config`可返回`ota_url`，不提供已存`websocket.url`；本轮未扩为串口/NVS读取。

另按主会话要求只读核对当前活动防火墙：以太网及另一活动接口均Public；已有当前Python3.10.20程序的Public入站TCP规则，LocalPort/LocalIP/RemoteIP均Any，程序路径与语音PID匹配（Windows路径大小写不区分）。旧`Xiaozhi AI ESP32 LAN`规则只覆盖旧`.106`和8000/8002，不匹配新端口，但程序规则另行覆盖18000/18003，故不把“没单独加新端口规则”写成阻断原因。PowerShell端口过滤查询报拒绝访问后，使用普通权限只读netsh取得匹配规则字段；未提权/UAC、未改规则、未扫描网络或测试设备可达性。收据`firewall-active-readonly.json`保留查询限制与匹配字段，实际端到端可达性仍待本次URL纠正后证据。

### 地址纠正后首次实证接入

所有者按主会话给出的完整正确地址替换、保存并正常重启后，主会话转达新反馈“已改好并回答，声音与刚才不同，同时延迟比刚刚高很多”。15:03:06与15:03:39只读核对出现此前没有的实证：本项目15:02:21收到1次OTA POST并下发WebSocket配置，15:02:22收到1次WebSocket连接；OTA和连接头中的设备身份均与本项目允许的目标设备匹配，只输出匹配计数，不复制MAC/原始头。API语音轮次0→1，正式校园调用2→4、unknown0，Cosy HTTP请求0→8，8次均有authenticated_wrapper关联且request_received/synthesis_entered/synthesis_returned/response_written各8。当前连接回到0时仍保留该轮voice_latency，说明不能把本次idle断开与前次完全没有历史阶段混为一谈。当前档案摘要仍与部署时相同，所选参考标签爱莉希雅、style为空；服务代码每片段按捕获的档案装配声线，不凭台湾腔猜供应商。

这次已能确认目标设备进入本项目Hy校园＋本地CosyVoice3链路，结合所有者新反馈仅登记正确URL后的实际接入和回答/声音存在。先前错误URL时听到的快答、声音及可暂停仍属原未确认链路，实际旧引擎未知；不把之前的快答或插话体验移植为本次实现验收，也不假定此前一定用了MQTT或Docker。读回URL的格式差异与纠正后实际接入证据分开留存，不冒称直接读取NVS或完整根因抓包。没有修改服务、防火墙、配置、声音档案或设备。

该真实轮次`started_at=2026-10-20T07:02:25.338560+00:00`，v6后台为cosyvoice3、response_path=model。相对文本chat入口：Memory就绪1948ms、模型请求1949ms、模型首个输出2425ms、TTS开始2506ms、首个真答案Opus就绪7081ms、首包发送返回7085ms。模型首个输出不另冒称可朗读首字；response_completed=3616ms是上游chat生成返回，不是整段TTS或设备播放完成。Memory固定无正文日志的内部total1931.098ms，其中recall1927.172、observe3.510、command0.067、lock_wait0.001ms；主要Memory耗时在recall，不在锁等待。TTS开始到首个Opus为4575ms；首TTS段完整合成/编码完成耗4630ms、89个60ms包对应5340ms可播放音频。该轮主要首答等待位于TTS阶段，不能进一步把这4575ms全部归为某一模型子组件或参考注册开销。VAD判停644ms、ASR处理423ms分别保留，不能无条件相加成“用户说完到听见”的总时长；没有扬声器确认。

API另记录该轮cancelled事件，最后一段本机tracker未完成；不由单个事件认定所有者当前链路插话验收通过。断开后voice_feedback未保留，实际等待cue是否已发送/听见无证据，不把四组缓存存在填成已播放。实际元数据收据仍在上述X忽略目录：`followup-150306.json`、`confirmed-150339.json`、`memory-split-and-profile.json`，无真实问答正文。等待听感、当前链路插话、跨新会话长记忆/来源/纠正继续待所有者验证；另一设备不再额外实机验收的决定保持。X只读诊断及窄文档收尾，不以本次结果扩展优化或再次停机。
