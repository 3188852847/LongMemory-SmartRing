# AA：Hy逐层真实内容浏览

日期：2026-10-21，Asia/Shanghai。起点 `34b2111d646cb1672bdad62603174e0da7c57f6b`，分支 `codex/aa-hy-layer-data-20261021`；复用本会话原干净树 `local/worktrees/aa-hy-mechanisms-20261021`，原分支与ignored证据保留。新需求为点L0–L7查看实际已存内容，不是重复机制目录。只改后端、对应测试及本轮窄文档；未改前端/manifest/根入口/他人报告，未读个人库/私有配置或操作正式服务/设备。

契约为 [hy-layer-data-contract](../hy-layer-data-contract.md)，决定为 [ADR-0194](../../adr/0194-hy-layer-read-only-browsing.md)。八层原生类型、所有状态、服务器有界分页/详情、可得来源和历史关联均经固定SDK owner接线；L0聚合与普通版本ID分开，L4历史/L5保留不冒充空层，L6/L7图未打开时明确部分/不可观测。普通总数只在有证据的末页给出，其他null；没有全库扫描/模型检索补数。

当前代码原语摘要：`674fd264bb84d3f6ed7c39e0764fdfdc1be44254cfddbcab0d9de123fa3c1433`。覆盖原七文件及新增 `layer_data.py`。旧正式摘要 `e358debcfa870e09c6072645758d70ac4fa6792bcfb1dd5d589f3c1490657e04` 失配，原守卫仍拒绝；没有更新/重签生产proof或改设置身份。旧签发工具仅两份旧管理测试不足以证明本轮读取，后续须由Z按精确候选重跑新入口和旧管理回归，再由主会话安排生产证明/部署。

已执行：最终真实SDK内容＋原管理组合 **32 passed，74.68秒，0 skipped**，JUnit `data/test-tmp/aa-layer-data-final-real.xml`。内容测试入口 `tests/integration/test_hy_layer_data_sdk.py` 共7项；人工SDK类型fixture与真实流水线＋模拟模型分不同合成空间。读取前后模型计数及所有可读合成库文件摘要不变，实际外部/本机模型网关请求为0；mock提取的合成模型调用只在播种阶段，读取增量0。原受控纠正/删除/history/RPC回归覆盖在同组内，不冒充读阶段有写。

较大15份单元组首次为255通过/1失败（11.61秒）：旧指纹测试合成目录漏建新覆盖文件，已扩展同一逐文件变异/换行归一化校验，专测 **6 passed，0.19秒**。这是测试前提更新，不降低生产指纹或跳过校验。最终同15份组合为 **256 passed，9.38秒，0 failed/0 errors/0 skipped**，收据 `data/test-tmp/aa-layer-data-final-unit-verified.xml`。

原失败保留：真实SDK首轮2通过/3失败，定位Chroma空字符串占位被误判链接，修正读取投影；第二轮4通过/1失败，mock协调修改人工状态fixture，隔离真实提取与人工类型场景；第三轮7通过。HTTP首组64通过/1失败为测试直接匹配JSON文本中的中文，改为解析JSON断言，随后65通过。没有改SDK安装源码、放宽隔离或访问日用数据解决失败。

核心实现/契约/ADR/测试提交 **`6d2df85249db5eaca3ecc3c12f9473ea7a9f528d`**，该精确代码先交Z审查；此后仅补本记录，原语摘要不变。没有merge main、push或归档会话。下面是最终交接范围，报告补充提交由主会话合并时追溯。

## 固定SDK依据与新增边界

只读重核本机公共规则、AGENTS、文档入口/manifest、架构/运行流程/方法与管理边界、Z前轮报告，复用project-doc-maintenance技能。V原树与SDK环境没有编辑/切分支/移动；SDK解释器仅用于子进程新合成空间与离线元信息读取。实际Python **3.12.13**、hy-memory **2.0.3**、Chroma **1.5.9**。官方目标提交由 [release-source](../../../config/examples/hy-memory/release-source.json) 追溯，未使用2.0.4主README，没有声明整个wheel与Git树逐字节等价。

本次只读核对安装源码摘要（SHA-256）如下，便于Z重核同一固定安装；未下载外部源码或改安装文件：

| SDK相对文件 | SHA-256 |
|---|---|
| `client.py` | `358145e038beace94c8307b8cc5516c305b96e78f845a782b173892d493e9084` |
| `data/vector_store_chroma.py` | `a3be99b273da02aa1ce860376886de76079e3c061400dc039c2408f69c4b1a33` |
| `data/vector_store_base.py` | `7aa2858afad2e7aef309b03ec450a490d3828a6862c33bec983c5190bdcf6411` |
| `agent/tools/basic_profile.py` | `575a421809084490e4f2b3e59cb2572c3c95f9dba535fee1caed3e9c20b16cbe` |
| `models/memory.py` | `e71eb6cfb4220a815defe2a6f46a7f1b3841b2f8062de440f806bb2cebbcebb2` |

`layer_data.py`在同一worker内使用已有SDK loop、Chroma collection及SDK VDB池；普通页精确下推user/agent/source/layer/state，原生limit+1/offset，二次复核身份与namespace，不读取embedding。原始L1没有经过list_by_user的RAW屏蔽。没有后台计数/全库搜索，页面/详情正文与演化关联/来源均有上限，截断或未知显式返回。逐层请求不新开或读写来源账本，平台归档不作Hy L1替代。

L0最多129条探测128版本上限，须已有范围stamp和owner租约，复用SDK纯函数同序合并，字段来源值不一致时降为unknown；全量来源超过投影预算也为null。生命周期不是另猜业务事实：固定合并函数确实按全部版本时间覆盖，negated/archived/分叉/null/空字段反例已测。L6/L7只确认VDB和标准本地Kuzu路径存在性；旧图资源存在时不打开，返回partial/unknown，不假称图里为空。测试中的旧图marker只是存在性安全反例，不冒充真实Kuzu内容验收。

## 最终软件证据与复跑入口

| 最终JUnit分组 | tests / failures / errors / skipped | 范围 |
|---|---|---|
| `tests.unit.methods.test_hy_layer_data` | 20 / 0 / 0 / 0 | HTTP鉴权/严格参数/body/旧引擎/闭合/暂停、未知/脱敏、零副作用、原生过滤/前瞻页/准确末页与未知总数、Runtime/方法/RPC非阻塞、5秒响应超时不重试、读操作拒绝模型、旧proof拒绝、无owner不读 |
| `tests.integration.test_hy_layer_data_sdk` | 7 / 0 / 0 / 0 | 真实Chroma八层/全部状态/来源过滤/分页详情/重启/字节不变，实际流水线＋模拟提取与手工类型分离，L0反例/范围/超限，旧图存在性不初始化 |
| `tests.integration.test_hy_release_management` | 2 / 0 / 0 / 0 | 真实HTTP/Runtime/SDK受控纠正、真实管理来源、重放、暂停及限定删除 |
| `tests.integration.test_hy_memory_management_rpc` | 3 / 0 / 0 / 0 | 原真实SDK管理RPC/独占范围/固定副作用回归 |

上述32项JUnit为 `data/test-tmp/aa-layer-data-final-real.xml`，XML记录tests=32、failures/errors/skipped=0，time=74.677秒；不是以环境缺失跳过。每个真实SDK测试的child仅打开本树合成空间，SDK生产解释器作为只读运行资源，固定socket拒绝外网，未连接日用端口。播种仅SDK类型fixture或MockTransport；没有真实LLM/BGE调用、个人对话或真实录音输入。读取阶段模拟请求数不增、实际外部/网关请求0、所有可读合成库文件摘要不变；owner锁字节被OS保护，不绕过读取。

最终15份单元组合JUnit `data/test-tmp/aa-layer-data-final-unit-verified.xml`：256/0/0/0，time=9.382秒。模块为new layer_data、hy_memory_process、hy_memory_administration、hy_mechanisms、hy_management_http、hy_runtime_extension、hy_memory_backend、hy_management_guards、hy_release_evolution、hy_overlay_batch、memory_identity、react_assets、console、hy_provider_transport、hy_sdk_observation。两组有20项重叠，不能把256与32相加当独立用例总数。源码导入已打印并核对来自本树src；没有前端构建、生产重启、远程CI、效果/性能/设备验收。

Z复跑时显式使用其工作树workdir和src；设置进程内 `LONGMEMORY_TEST_HY_PYTHON` 指向所有者既有V专属解释器，用主项目既有Python执行pytest：`tests/unit/methods/test_hy_layer_data.py tests/integration/test_hy_layer_data_sdk.py tests/integration/test_hy_release_management.py tests/integration/test_hy_memory_management_rpc.py`，给自己的新JUnit路径。须检查每组零skip、代码身份和新原语摘要，不可只据四字段proof重新填hash。SDK测试fixture为 `tests/fixtures/hy_layer_data_worker.py`，仅测试进程受控命令可加载，HTTP不接受模块/命令/路径；这些用例不是生产授权证明。

## 文档与最终交付边界

三篇新文档只在内存补登记后运行正式check_docs.audit，checked_documents=3、findings为空；未写manifest，不能称正式清单strict通过。源码关联候选没有unmapped；宽泛Hy主题关联出旧ADR/方法边界/运行与管理指南及历史报告，不以匹配当作全篇语义审计。新增只读契约和ADR补充旧管理接口，不重写历史证明/实机记录；主会话/Z按Y最终页面入口登记清单与同步指南新增浏览说明。文档检查机制没有修改，不需要其机制测试。

提交差异已检查精确文件归属、git diff --check；私钥/长Token等敏感模式扫描0命中，合成占位字符串不是真实凭据。所有运行/JUnit/合成库产物均在忽略范围，不提交Git。核心源码相对6d2df85没有再改，摘要独立复核仍为 `674fd264bb84d3f6ed7c39e0764fdfdc1be44254cfddbcab0d9de123fa3c1433`。

本轮软件候选不代表正式个人内容浏览已部署、图中旧数据可读、真实提取质量或设备验收。生产proof更新和配置写由主会话安排；主会话/Z登记三篇文档。原错误/失败收据、ignored测试目录和旧分支均保留。无剩余必要后端实施，冻结待独立审查，不自行归档。
