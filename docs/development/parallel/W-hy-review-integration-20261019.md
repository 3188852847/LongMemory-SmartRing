# W：Hy-Memory 独立审查、整合候选与主动交流规划

日期：2026-10-19，Asia/Shanghai。工作树 `local/worktrees/w-hy-review-integration-20261019`，分支 `codex/w-hy-review-integration-20261019`，会话 ID `01a1539f-0689-7ed3-9ce0-c098a15a17e0`。共同基线 `147cbc117d4f88f5775dd02076ab9970871238a8`，起点为 V 最终 `8b28d0a9b2f989b630e13f707a146dfc555a6644`；初始干净，未创建新树。仅本地提交，不 merge main、不 push、不向其他会话发消息、不自行归档。

## 首轮审查结论与交付边界

以下至“第二阶段”前保留 `1dda701` 首轮交付状态。最新结论见文末第二阶段：前端缺口已补验，主会话接受两项既有失败另行跟踪，本次可选隔离接入可合 main；尚未由 W 合入/推送。

**后端作为可选隔离接入的代码审查通过，修复后组合回归通过；这不是无条件 main 验收或日用发布。** 主会话仍需处理前端动态验证缺口和两项再次复现的既有测试失败，决定整合范围。没有发现本批后端代码尚未修复的合入阻断缺陷；没有把旧失败改写为成功。

W 修复提交 `f251f98569a4fee6d1ccb3a5d563d556a940c60a`。本报告所在后续文档提交为最终本地候选，精确 SHA 随最终交付回复，Git 历史可查。新增 [主动交流阶段方案](../../requirements/主动交流阶段方案-20261019.md) 为 draft，实施与验收 pending，只建议先做有明确来源的一次性事项跟进，等待主会话定案。

未读个人库正文、共享私有配置或真实对话/音频，没有日用端口访问、服务启停、数据迁移/删除、配置切换、主动调度、串口/设备/烧录或外部模型调用。没有下载/安装/更新依赖、修改全局环境或根锁文件，没有共享可变 node_modules。

## 具体发现与最小修复

| 发现/等级 | 证据与影响 | W 处理及验证 |
|---|---|---|
| P2：畸形成功回包绕过传输故障清理 | V 的 `HyProcessClient._rpc` 只校验 ID 值，随后在 try 外读取 `response['result']`。`ok=true` 缺少 result 会抛 KeyError 并保留 worker；Python 的 `True == 1` / `2.0 == 2` 也会接受非整数 ID。调用方不能可靠终结协议失效的进程。 | 严格要求整数 ID、布尔 ok 和成功 result 字段；畸形包统一 `_stop` 并返回稳定 `state_unknown` 传输错误。新增 9 项真实子进程测试：缺字段、ID 类型/错配、ok 类型、初始化错误、退出/超时、错误正文脱敏和回收。 |
| P2：中立页面未说明列表截断 | U 的 MemoryApp 请求默认首批 25 条，只存 items 且不显示 total，超过首批时页面无法表明还有条目。 | 读取 API 的实际 total，显示已加载数/总数及首批提示。仍无完整分页/编辑表单；更新原中立组件用例。静态核对通过，TS/Vitest/构建未执行，见下。 |
| SDK 测试路径限制 | 原集成测试只在当前树查专属解释器，W 没有安装；直接运行会全部 skip，不能作为 SDK 通过证据。 | 测试独享 `LONGMEMORY_TEST_HY_PYTHON` 显式路径；设置错误报错、默认缺失才跳过。只读复用 V 已装解释器，项目代码/测试/所有合成状态仍在 W；补真实 SDK 越过末页的 total/空页断言。无生产配置回退。 |

前端窄修复使用 ui-ux-pro-max 技能作检查入口；两次本地检索未返回直接适用的分页结果，因此没有把检索结果当验证依据，改动依据是当前 API `total` 与页面请求事实，只用已有 Ant Design/普通文本，无设计系统或依赖变更。

## 独立审查覆盖与真实限制

| 范围 | 实际核对结论 |
|---|---|
| 中立性/默认链路 | `contracts.py`/`backend_contracts.py` 不依赖 Hy 或 AtomicMemory；新装配只由可信 Python 调用，默认 CLI/启动器仍为旧链路；旧 `build_legacy_runtime` 的类型守卫保留。新后端旧 L1/情景/画像/主动端点明确拒绝，server 不装主动循环；未通过 legacy 标志放行 Hy。 |
| 平台来源与身份 | `SQLiteSourceJournal` 先提交角色/时间/session/正文，身份绑定引擎名/版本/精确资源；来源文件和 Hy 目录各有 OS 生命周期锁；另一个来源库不能绕过活跃引擎锁。用户事件才投 Hy，助手仅归档；同 ID 异载荷拒绝，completed 持久回放。未宣称失败无写入。 |
| failed/uncertain | 引擎异常后 failed，提交后来源回执失败在重开接管时 uncertain；Hy 不声明持久幂等，因此 failed/uncertain 不可盲重试；pending 可显式恢复，归档/暂停不自动恢复。真实 SDK 部分提交窗口有测试，未保证跨存储事务或 exactly-once。 |
| 管理/权限 | Hy 列表带 user/agent 过滤，列表/详情再核对 owner，分页/来源/未知时间按 SDK 结构保留；非 active/query 不支持时拒绝。revision 仅只读摘要，无原子比较能力就拒绝纠正/删除。Runtime 拒绝助手纠正权威；HTTP 使用原会话/同源/CSRF 与启动权限。 |
| 进程/隐含配置 | 子进程 `-I -X utf8 -B`，源码路径取 W 的 process_client 父目录，不继承环境 Key、MEMORY 私有配置；home/temp/logs 写 W。stdout 协议与 SDK 输出隔离，错误仅稳定码/异常类型；超时/崩溃/畸形包回收已测，不证明任何原生库永不崩溃。 |
| 禁网/版本 | 所有者安装的 Hy 2.0.3 与实际主次 Python 3.12.13 已核对；默认 socket/SDK HTTP 拒绝，保留 Windows 标准库 socketpair 内部连接。关闭搜索去重、strength/access、搜索历史、graph/intention/coding；BPE 使用字符估算回退，不下载。真实 SDK 初始化/模拟写读与重开已执行，未测图功能、真实端点或第三方所有可选组合。 |
| 比较协议 | 构建只收事件白名单，题目/答案不进入写入；关闭并重开后封存，每题新引擎副本/空来源账本，原构建账本保留。封存源前后摘要不变，副本变化列 requires_store_level_review；search 会变 SQLite/日志，不能叫冻结或按文件名豁免语义。错误/不支持/构建失败保留题目分母；截断前来源覆盖不是注入后充分性。 |
| 预算/模型 | CLI 仅无密钥离线配置和 Fake 回答，环境不回退到真实模型。单 worker 请求数上限不是整轮共享预算；token/金额硬限制未实现，真实网络装配未验，不能宣称已限费或已完成质量实验。真实实验前需明确端点/维度/出口及可执行整轮预算；本轮不以 mock 评分报告效果。 |
| 旧失败归属 | 独立核对下述旧启动器/诊断实现和测试与 `147cbc1` 无差异，W 不扩大修改或改测试使绿。未重跑无关硬件/模型全量，远程 CI 未运行。 |

## 实际命令、数量与源码身份

所有终端操作显式 workdir=W。主 pytest 解释器为主项目 `.venv/Scripts/python.exe`，只读复用 3.12.13/pytest 9.1.1；`longmemory.bootstrap.__file__` 实际打印为 W/src，pytest 的 pythonpath/rootdir 为 W。Hy worker 脚本从同一 W 的 `process_client.py` 计算 `parents[3]` 插入 src；`-I` 排除外部 PYTHONPATH/用户 site，没有加载 V 的项目源码。

专属解释器为 `local/worktrees/v-hy-memory-20261019/local/runtime/hy-memory/.venv/Scripts/python.exe`。标准库 metadata/find_spec 只读核对：Hy 2.0.3、langdetect 1.0.9、jieba 0.42.1、Chroma 1.5.9、Kuzu 0.11.3，SDK 模块实际在该 V 环境 site-packages；锁 SHA-256 为 `706ce91ace29062d86a73db6a5845d9081e5e5b87660f52de8737d6c7f0345d7`，未改环境/锁。项目库、合成状态、独立临时端口和实验输出均由 W 测试创建；无主检出导入或个人库读写。

| 实际检查 | 结果 |
|---|---|
| 修复前受影响组合：methods、entrypoints、application、architecture，Hy preparation/runner 与 comparison | **546 passed / 2 skipped**，47.18 秒；未含真实 SDK。 |
| 协议修复初轮 | 6 passed / 1 failed；失败是测试替身返回错误后退出，finally 又期待正常 close；补齐替身 close 协议后继续，未修改生产关闭语义。 |
| 中间协议与真实 SDK 定向 | **12 passed**，25.80 秒；当时为 8 项协议与 4 项真实 SDK，之后新增启动畸形回包清理。 |
| 最终代码组合（下列命令） | **559 passed / 2 skipped**，71.78 秒；含最终 9 项协议和全部 4 项真实 SDK。跳过为 Windows 测试符号链接权限、未显式绑定 Otto 固定资源，Hy 无跳过。 |
| 旧失败复核第一批：重复 bind、两个 Tk 用例、voice observability API、voice diagnostics | **22 passed / 1 failed**，1.74 秒；失败仍为 `test_memory_observer_ends_speaking_and_records_sanitized_failure`：bind 实际两次、预期一次。两个 Tk 测试与本批诊断回归通过，不推定首次全量环境问题已解决。 |
| 旧诊断子进程精确用例 | **1 failed**，0.15 秒；`test_real_separate_processes_write_distinct_files` 实际 1 个文件、预期 2 个。W 再次复现，具体原因未定位；源码/测试与共同基线无差异，不能说已修复或只是环境原因。 |
| React | W `web/react-chat/node_modules` 不存在；未执行 TS/Vitest/构建/浏览器视觉验收，无安装/共享环境。源代码静态检查不替代动态验证。 |

最终组合命令（W 根目录的独立 PowerShell 进程）：

```powershell
$env:LONGMEMORY_TEST_HY_PYTHON='D:\03-项目\01-正式项目\智慧圆屏\local\worktrees\v-hy-memory-20261019\local\runtime\hy-memory\.venv\Scripts\python.exe'
& 'D:\03-项目\01-正式项目\智慧圆屏\.venv\Scripts\python.exe' -X utf8 -B -m pytest tests/unit/methods tests/unit/entrypoints tests/unit/application tests/unit/architecture tests/unit/evaluation/test_hy_memory_preparation.py tests/unit/evaluation/test_hy_memory_runner.py tests/unit/evaluation/test_comparison.py tests/integration/test_hy_memory_sdk_offline.py -q
```

主会话若要完成前端验收，先由所有者在 W 安装本树独立依赖，再运行；本轮未执行以下命令，不自动联网：

```powershell
Set-Location -LiteralPath 'D:\03-项目\01-正式项目\智慧圆屏\local\worktrees\w-hy-review-integration-20261019\web\react-chat'
node.exe --version
pnpm.cmd --version # 必须为项目固定11.19.0，沿既有Node环境，不自动切换/下载
pnpm.cmd install --frozen-lockfile
pnpm.cmd exec vitest run src/pages/MemoryApp.test.tsx
pnpm.cmd build # 包含tsc --noEmit与Vite构建
```

## 主会话整合、日用和下一阶段门槛

**main 合入验收未齐项：** 前端动态兼容/构建必须明确补测或由主会话接受为未验；两项既有测试失败必须保留并明确另项处置/修复归属，不把本组合通过写为全量绿。W 无未修复的本批后端缺陷，不主动改旧语音启动器或诊断实现，不自行把范围缩掉后宣布整个 main 验收完成。

**日用切换阻塞项：** 真实 LLM/Embedding/回答模型效果与费用控制、整轮共享硬预算、真实维度和资源身份、日用启动选择与受控配置、圆屏完成/反馈/来源轮次关联、新后端事项/许可/主动交流装配、真实声音/连接/打断/播放体验均未完成。本次通过不授权切换服务、读写个人库或开启调度，设备播放仍 unconfirmed。

主动交流草案基于实际旧策略/事项/账本/桥及 R 方案：Hy 提供证据，平台持有事项/许可/安排与结果，独立层决定是否/何时/说什么，设备执行，来源/轮次/取消/改时/回应/过期形成闭环。草案未接受为 ADR，未实现或迁移。先建议明确事项跟进，随后再讨论日常陪伴；记忆效果、调度正确和人的体验分别验收。

## 任务与提交追溯

| 任务 | 原提交 | V 已接入提交 | W/验收/合入 |
|---|---|---|---|
| U 中立契约 | `83b5b6dcceca281acea718d0f4be75b3bfe302f0` | `5855e4e9f0c6ba07b7c60402ba6fcfc5345dc6db` | W组合覆盖；main待主会话 |
| U 装配/来源/运行时 | `b52e0e32d8f2c1c930698da3e1569c3dd5acd836` | `6fefb2662afd5b0c58a3f269b737c1d1a0f43acf` | 同上 |
| U 用户纠正权威 | `77c73421de2f55c891c3988bff5236e99e222b42` | `e12d336c49412981ed53e213a68cca4756b998e4` | 同上 |
| U 中立列表状态 | `4deee7ba9cf155ce23028ed9a739a5b97845e8f1` | `68a752dca0aa4bbe8fd7de63f5ccfd0825c0c4eb` | W补首批总数提示；前端动态未验 |
| U 文档/ADR | `e4087f7c9090298a9966f8ab539068f4cdebca23` | `972793a5ed23c9f15e5a72fc9dd83c07e04105af` | U/V报告历史保留 |
| V 首轮和最终接线 | `1e03d1df9e164966dc9c86207c1d8b7e363a30f4` → `8b28d0a9b2f989b630e13f707a146dfc555a6644` | W起点即最终V | 来源/SDK/比较见上；不重复合并U原分支 |
| W 协议/兼容修复 | `f251f98569a4fee6d1ccb3a5d563d556a940c60a` | 不适用 | 559/2skip；前端及旧失败限制见上 |
| W 文档与规划 | 本报告所在最终本地候选 | 不适用 | 正式清单/strict结果见下；main合入提交待主会话填写 |

U 会话 `01a15362-e6ae-72c2-bf03-bfb4f3844ba6`；V 会话 `01a15363-8120-7400-a9db-8f9142104b12`；W 会话 `01a1539f-0689-7ed3-9ce0-c098a15a17e0`。保留 [U 原报告](U-memory-boundary-20261019.md) 的首次 2132 passed/7 skipped/4 failed 和 React 未验，以及 [V 报告](V-hy-memory-20261019.md) 的分阶段数量；本轮结果不倒推旧全量成功。

文档只同步方法边界、Hy指南、W报告、主动交流草案与清单；未改 AGENTS/根 README/CHANGELOG/ROADMAP、U/V历史报告或已接受ADR。正式 `check_docs.py --only <上述四份Markdown> --strict --json` 返回0，正文检查4份，warning/error 0；仅Hy指南的实验计划链接为私有目录边界 note，未读取目标。`--base 8b28d0a` 的关联检查无 unmapped，候选文档逐项按范围判断，不改写历史记录。`git diff --check` 和提交范围/敏感内容检查通过；文档链接检查不证明全仓语义或未执行验收。

## 第二阶段：前端串行移交与合入前补验

所有者要求“没问题就合入推送，再把主动交流第一阶段的方案给我看看”。主会话据此安排 W 补完前端；两项既有失败明确接受为此次可选隔离接入的已知基线问题另行跟踪，不扩大本轮修改旧语音启动器/诊断。首轮失败数量、准确用例与源码未变事实保留在上文，不宣称全量绿。

**最终结论：可选隔离接入可合 main，无本轮剩余合入阻断；W 只交本地候选，main 合入/推送仍由主会话执行。** 前端补验无新缺陷，无需代码修复/cherry-pick；本阶段只改文档，未重复运行559项后端组合。前端组件测试、类型和构建通过不代表浏览器视觉、真实模型或设备体验已验收。

### 移交与旧产物保护

主会话明确串行移交已有隔离树 `local/worktrees/p-frontend-experience-20261015`，覆盖默认只使用 W 的工作树约束；该树原 P/S 工作已交付合入归档，无其他任务进程。W 重新核对：工作树干净，原分支 `codex/s-pq-integration-20261015`，完整 HEAD `36ebf3a0c6bc784c7b5697c4b026c6b5a2817f82`；除当前诊断 shell 无 node/pnpm/cmd/powershell 进程引用此树。`node_modules` 是本树实体目录，其 package 解析到本树 `.pnpm`，没有新增共享目录/联接，没有安装或下载。

切换前将原 `web/react-chat/dist` 与 `test-results` 共174个文件复制到 W 私有检查点 `local/archive/frontend/wfe-b78d32de`，清单记原分支、完整SHA、逐文件SHA-256，逐项比对副本相同。其余 ignored 证据/缓存保留原位，无 reset/clean/删除。新建原先不存在的分支 `codex/w-hy-frontend-validation-20261019`，使用 `git switch --no-overwrite-ignore -c ... 1dda701fc87df0d40be329bf5b67f724c876a577`，未同时 checkout W 分支，原 S 分支保留。

构建后再次校验174个原文件摘要全部不变、S分支仍指原SHA、验证树 tracked 内容与 `1dda701` 完全一致且干净。原 `data/test-tmp`/历史证据没有清理或作为新输出目录；新生产构建独占 W 的 `data/test-tmp/wfe-5f8a3137`，没有覆盖原dist或供任何生产服务消费。该验证分支/旧分支、检查点与构建输出均保留，不擅自清理。

### 工具、锁与实际检查

两树 `web/react-chat/package.json` SHA-256 都为 `3b935512fe8abb810de9e35805c708976843416da2ce1cefe67f3463ce081541`，`pnpm-lock.yaml` 都为 `c0e083751833a86c21a0f4cfa7cf66d8a8621d1459b91a66991dcfbe6ad6fdd9`，前后未变。Node 来自既有 fnm 会话 `node.exe`，版本 `v24.21.0`。稳定入口 `D:/01-开发环境/02-Node.js/bin/pnpm.cmd` 实际报告12.9.1，项目仍固定11.19.0；未在项目内调用包管理器以触发版本获取，也未变 packageManager/锁。直接用 Node 执行该验证树现有 TypeScript 7.0.2、Vitest 5.0.0、Vite 8.2.2 CLI，工具版本与项目声明一致。该检查证明已装依赖上的代码检查，不冒充 pnpm11.19.0 干净重装可复现验收。

所有下列命令的显式 workdir 均为移交树 `web/react-chat`；源码身份为 W `1dda701`，没有在主检出操作：

| 实际命令 | 实际结果 |
|---|---|
| `node.exe node_modules/vitest/vitest.mjs run src/pages/MemoryApp.test.tsx --maxWorkers=2 --fileParallelism=false` | **1 file / 11 tests passed**，54.50秒；覆盖新增中立引擎/首批总数与同页旧功能用例，无跳过。 |
| `node.exe node_modules/typescript/bin/tsc --noEmit` | 退出0，无类型错误，1.79秒。 |
| `node.exe node_modules/vite/bin/vite.js build --outDir <W新专属目录>` | 退出0，1614模块，Vite报告3.70秒；本次进程设置 `RAYON_NUM_THREADS=2`、`UV_THREADPOOL_SIZE=2`。 |

Vite保留两项非阻断提示：输出位于项目外所以不清空、共享chunk约689KB超过默认500KB提示；未为使输出安静更改阈值/配置，未触发下载。新构建43个文件的逐项摘要、工具/测试结果保存在同一私有检查点的 `w-validation.json`；`MemoryApp-C0-Mz2aE.js` 实际含首批提示，未提交原产物。构建后无该树 Vitest 任务残留进程；没有启动浏览器、生产服务、调度或设备连接。

### 最新追溯与待办

完整链路为 U原提交→V接入（上表）→W代码修复 `f251f98569a4fee6d1ccb3a5d563d556a940c60a`→首轮文档候选 `1dda701fc87df0d40be329bf5b67f724c876a577`→移交树同一tracked身份上前端11项/TS/构建通过→本报告第二阶段本地文档候选（完整SHA随最终回复）→main合入提交待主会话；W会话仍为 `01a1539f-0689-7ed3-9ce0-c098a15a17e0`。

main本批合入前的软件验证缺口已关闭；两项旧失败接受为已知基线问题，远程CI未执行。真实模型/整轮共享硬预算、日用选择/配置、设备完成与反馈关联、声音/打断/播放体验等日用阻塞项保持。主动交流方案仍draft，用户本次只要求查看，不实施、迁移或开启调度。第二阶段四份Markdown正式strict返回0、warning/error为0（仅原实验链接私有边界note），`git diff --check`通过；本轮不修改U/V历史报告、根入口或已接受ADR。
