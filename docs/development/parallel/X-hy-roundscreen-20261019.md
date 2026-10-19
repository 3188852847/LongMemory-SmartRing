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
