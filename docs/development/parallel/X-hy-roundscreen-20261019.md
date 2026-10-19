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
