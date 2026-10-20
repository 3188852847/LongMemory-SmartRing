# AF：学校模型前缀缓存取证与网关观测

日期：2026-10-21。工作树 `local/worktrees/af-prefix-cache-20261021`，分支 `codex/af-prefix-cache-20261021`，起点 `a93258e903954525b88b7af79756aaffe2bd50d6`。独立会话仅提交自己的分支；未合入、未推送或部署日用，无新设备/语音体验验收。

## 结论及范围

学校当前已选 `DeepSeek-V4-Flash` 的六次合成流式调用全部完成，但**缓存是否支持、是否命中仍未确认**。六次均有常规 usage，无缓存命中/未命中字段；不能由字段缺失断言“不支持”，也不能由重复请求变快断言“缓存已命中”。已实现可上线审查的网关观测，不改角色、记忆、日期或消息布局，不打开假想缓存开关。决定见 [ADR-0199](../../adr/0199-provider-prefix-cache-evidence.md)。

第一里程碑已核对本工作树/分支 clean、主 Python 3.12.13、pytest 9.1.1、aiohttp 3.13.2；测试通过进程内 `src` 路径导入，`longmemory.__file__` 明确指向 AF 工作树。使用现有项目解释器作为只读工具，未安装或升级依赖，不使用其他发布证据树的 SDK。已读取本机通用、机器、Python、Node、GPU 规则；没有加载模型、使用 GPU 或操作串口。

主会话先批准文件所有权，再明确批准最多6次串行合成请求、每次32输出 tokens、零重试和专属免费实验账本。AF 未向其他会话发消息或开子会话；本记录与当前会话输出交主会话协调。

## 文件与接口

| 文件 | 实际变更 |
|---|---|
| [model_gateway.py](../../../src/longmemory/methods/hy_memory/model_gateway.py) | 原 `responses` 列表新增缓存证据和耗时；流式计首个过滤后非空白 content，记录固定结束原因；非流式 TTFT 留空 |
| [prefix_cache.py](../../../src/longmemory/methods/hy_memory/prefix_cache.py) | usage 白名单判定 `unknown/invalid/reported_miss/reported_hit`，不保存输入、不开缓存、不改变结算 |
| [benchmark_prefix_cache.py](../../../scripts/development/models/benchmark_prefix_cache.py) | 默认只显示计划；核验学校免费身份、隔离账本、6次硬上限的两组配对、无重试；不保存原始正文 |
| [test_hy_prefix_cache.py](../../../tests/unit/methods/test_hy_prefix_cache.py) | 真实本地 HTTP 替身、边界与错误停止、连接复用、角色/记忆/工具保留、过滤后计时、免费策略门 |
| [ADR-0199](../../adr/0199-provider-prefix-cache-evidence.md) | 证据语义、实验与迁移边界 |

`responses[*].cache` 形状为 `{state, source, hit_tokens, miss_tokens, completed}`；来源为 `deepseek_usage/compatible_usage/null`。两种 usage 同时出现须一致；负数、布尔值、缺半边或计数矛盾标 `invalid`，缺字段标 `unknown`。证据不参与业务门、预算折扣或重试。`model_ttft_ms` 是网关预算预留后至首个有效文本，未测用户停说、首句完整度或设备声音；`provider_elapsed_ms` 是本次调用经过本地转发的耗时，二者不能与其他阶段直接相加。

## 布局、连接与冷启动核查

- `provider_transport.py` 已按端点/凭据持有独占 aiohttp 会话、120秒 keepalive、首请求才初始化、无重试/重定向，不保存回答。AF 不再造一套连接池，也不发付费保活；本地 HTTP 测试确认完整读取后复用，第三次换新会话创建新连接。学校真实是否复用同一 TCP socket 未打包抓取，只能确认发送条件和使用了同一 transport 实例。
- `voice_response_policy.py` 在已有 system 后追加固定表达规则，保留角色语气；`voice_web_search.py:_instruction()` 包含精确当前时间，`_with_system_instruction()` 将规则合入首条 system。稳定角色前缀可能复用，但每轮时间变化会使后续历史不能完整匹配上一轮前缀。不能通过删日期、冻结时钟或再次添加尾部 system 来求命中；这两模块归其他任务，AF 未改。
- `adapters/llm/openai_compatible.py:generate_turn()` 顺序为固定 system、可选角色 system、user 记忆证据、原 user/assistant 历史、当前 user。记忆证据随检索变化时，其后的历史前缀也可能变化。将动态记忆移到历史之后会改变语义边界，未实施；交主会话按接口所有权评审，不能单凭本次六请求证明重排有效。
- 当前网关只为 Hy 原样追加中文记忆策略，并统一 `thinking=disabled`；语音继续经过既有 `FinalStream`，保留已合入的 system 顺序与显式推理过滤修复。测试覆盖记忆 user 与问题分开、工具 ID 配对、结构化 system 和原输入不变；不剥离普通无标签正文或猜测其为推理。
- 首次请求含 Python/aiohttp/传输初始化成本；第一组与第二组都用新的合成标识和 transport，但第二组已导入模块。没有做额外预热请求，也不把初始化前移当成本消失。

## 获批真实实验结果

实际执行为北京时间2026-10-21 03:05:30–03:05:40，调度标识 `root-01a1534f-af-six-20261021`。仅只读加载主项目已选学校凭据和免费策略，核对 web/voice 同选 campus、精确模型与策略绑定身份。原免费账本仅由既有验证入口读策略身份；reserve/finish 全在 AF 专属实验账本。未使用原付费账本、未清除或解释历史 unknown、未改私有配置、未访问日用端口或现有连接。

每组合成输入3540字符，前端随机标识不同；每组三次的消息和参数完全一致。两次重复前各等待2秒，条件只是候选冷/热，不表示服务端缓存已清理或必然命中。没有个人历史、记忆、音频、工具或个人库写入。

| 组/条件 | TTFT ms | 本次完整耗时 ms | 输入/输出 tokens | 结束/有效短答 | 缓存计数 |
|---|---:|---:|---:|---|---|
| A 新前缀/新会话 | 511.300 | 527.127 | 2167 / 3 | stop / 符合 | 缺失 |
| A 重复/同会话 | 157.019 | 177.453 | 2167 / 3 | stop / 符合 | 缺失 |
| A 重复/新会话 | 149.876 | 172.149 | 2167 / 3 | stop / 符合 | 缺失 |
| B 新前缀/新会话 | 300.110 | 318.986 | 2166 / 3 | stop / 符合 | 缺失 |
| B 重复/同会话 | 157.792 | 180.620 | 2166 / 3 | stop / 符合 | 缺失 |
| B 重复/新会话 | 147.321 | 171.109 | 2166 / 3 | stop / 符合 | 缺失 |

6次全部 HTTP200、完整 usage/DONE、无截断、无空答案、无残留 unknown。合计输入12,999、输出18、总计13,017 tokens。个人成本按所有者免费确认记0；未查询余额、不套官方缓存价格、不产生另一份付费额度。每组仅1个新前缀候选和2个重复样本，不报告P95、显著性或日用加速比例。

缓存字段本身缺失，usage **并未缺失**；这两个事实分开报告。两组新前缀减同会话重复 TTFT 为354.281和142.318 ms；新会话重复分别又比同会话重复快7.143和10.471 ms。说明本批重复条件更快、单纯连接复用不足以解释所有观测，但缓存、排队、服务端/客户端冷启动等未隔离，不能归因。需学校提供计数透传或服务端证据才可确认；本轮额度已用完，不自动追加请求。

私有证据位于本工作树 `experiments/runs/af-prefix-cache-six-20261021/`，Git忽略：

- `summary.json`：SHA-256 `6dcc8cd8f4f19828658cf37bb9b9d27a2ded2a78de69b433a1394faab92a7aa0`。
- `campus-calls.sqlite3`：SHA-256 `00635733de23b0fdcfb1659a509d007ca08b80d403d76611ef54f58ce11e039c`。
- `source-provenance.json` 和 `executed-source/`：保留真实执行时3个自有源码快照和摘要；原摘要未覆盖后续仅本地验证的来源记录增强。真实执行后增加未来实验的自动代码摘要及畸形结束元数据保护，未重新请求学校。

原始提示/回答不落盘；报告只保存合成 payload 摘要、预期回答布尔、计数/状态/时间。账本内部包含验证过的免费策略，继续作为私有证据，不提交Git。

## 验证及交接

首轮定向测试120 passed。补充记忆/工具/日期保留、免费策略缺失拒绝后，网关/推理边界/传输/日用流及校园合成 HTTP 集成共 **134 passed、3 skipped（6.96秒）**。跳过为2个未显式指定小智Python/厂家源码的集成案例、1个缺隔离 Hy SDK 的案例；未借生产 SDK 树补跑。测试只用合成库和随机临时端口；已有推理边界测试保持通过。

新文档的清单归属交主会话/AI统一登记，AF不抢写公共 `documentation-manifest.json`。登记建议：topic `provider-prefix-cache-evidence`，authority 为本记录，sources 为本轮源码及专属测试，related 为 ADR-0199，状态 `reference`，review 只覆盖本轮已完成六请求与隔离验证，缓存支持/设备声音保留未验证。通过临时合成清单执行两份新文档的严格链接检查；该结果不表示共享清单已登记。

主会话可审查合入网关内存观测，继续保留现有持久连接；本轮没有需所有者下载的依赖/模型或GPU需求。若要扩展缓存证据，应先协调学校透传命中字段，再单独限定新样本；不要为采样牺牲角色/记忆正确性或开放后台写入。用户停说到首个有效回答声音、连续性、续说取消、插话残音和实机体验仍由其他任务/所有者验收，AF结果不代替它们。

## 第二阶段：候选真实网关宿主接口

首阶段提交 `e8ce66d2d7c373dfb27ee6f9b45f27c2e3928717` 已由主会话安排交AI组合；本次在同一分支追加，不改写历史。新增授权限定宿主网关/传输及专属测试，不给新真实调用额度。首阶段六次额度已结束，**第二阶段真实请求为0**；缓存支持状态继续未确认。

新增 [candidate_response.py](../../../src/longmemory/methods/hy_memory/candidate_response.py)、[专属测试](../../../tests/unit/methods/test_hy_candidate_response.py)，修改原 `model_gateway.py/provider_transport.py`。没有修改AE、AB、启动器或私有配置；原持久会话的同步接口保留。新增异步逐行句柄复用同一pump/队列/事件循环/会话，不建立第二套HTTP客户端；消费者通知用跨线程event唤醒，不轮询读取或为每行另开线程。

导出形状可直接供宿主装配层使用：

```python
binding = gateway.candidate_response_binding()
# {open_response: callable, model: 精确已选模型名, campus_free_verified: True}
handle = binding['open_response'](frozen_payload)
async with handle as response:
    # type(response.status) is int；response.content逐行异步迭代bytes
    async for line in response.content:
        pass  # 宿主候选消费者，不是正式字幕/播放
ack = await handle.wait_closed()
# {request_id, owned_upstream_exited: True, provider_compute_stopped: False,
#  ledger_finalized: bool, usage_settled: bool}
```

`handle.cancel()` 显式取消该候选自有上游任务并等待同一ack；`handle.aclose()` 幂等关闭，`gateway.cancel_candidate(handle.request_id)` 可按活动候选ID取消，正式attempt_id不在查找表。三者及 `wait_closed()` 限定同一宿主asyncio循环。创建句柄不取锁、不预留、不联网；进入时重新核对免费政策，按同一网关锁和账本 `reserve('answer')` 后才向原供应商池发出。付费、身份变化、裸布尔证明、错模型或超出256输出tokens均先拒绝。

请求保持冻结消息，首system和末user，不改动角色、时间或记忆边界；单choice、n=1、禁用思考、无tools、tool_choice=none、总输入最多32000字符。上游总时限10秒的timer直接取消该句柄；socket超时继续沿原设置，清理确认不使用假超时释放并发槽。包/行/总响应有界，拒绝工具/函数、非stop、缺DONE及非法usage；最终内容沿原 `FinalContent` 边界过滤。

只有完整stop/usage/DONE且消费者正常退出后，等自有pump实际 `task.done()` 及响应关闭，再按原策略finish和审计。取消时即使见过部分usage也保留unknown。`gateway_results.forwarded=false`，候选没有正式归档/字幕/播放。元数据不含消息、响应、角色内容、供应商错误正文或凭据。未结usage不是零token；ack不声明远端GPU停止。

隔离证据：34个专属测试通过，含实际本地HTTP连接复用、原账本/正式请求共池、身份与请求门、首头前/首片后取消、重复取消、按request_id显式取消、排队取消无迟到取锁、宿主关闭、总时限及unknown审计。延迟关闭测试在pump允许退出前明确断言网关锁仍持有、候选登记存在且 `wait_closed()` 未返回，之后才退锁。

其中3个测试以本地 `git show baedad5e5ce1f4da18bb3aefabeaeeecad954c78` 提取的AE自有源码快照运行，没有下载或修改AE文件。快照位于忽略目录 `data/test-tmp/af-ae-source-baedad5/`，由测试进程临时环境变量指定；组合树中缺该显式快照/AE源码时这3项应跳过，不能谎称已组合。实际 `VoicePreemptive/GatewayPreparationModel` 完整请求能ready并一次领取；首头前和首片后取消时 `aclose(.02)` 返回False，AE `active=1`、网关锁仍持有；允许上游退出后active归零、unknown仍为1，ready/hits为0。

AE `baedad5` 只接受小写模型名，因此该生命周期组合测试用绑定为小写名的合成免费政策验证；并没有把真实学校大写名偷偷换成别名。真实绑定返回 `DeepSeek-V4-Flash`，已通过主会话输出报告，须AE/AI接受精确名称后再组合。

真实启动边界已核对 [bootstrap_hy_daily.py](../../../src/longmemory/bootstrap_hy_daily.py) 的 `OwnedHyModels.gateway` 属于宿主，`voice_configuration()` 给小智的是回环模型配置，非可共享的Python对象。**宿主内部接口不等于跨进程接线完成**：本阶段未新增RPC/HTTP候选入口、未复制供应商密钥到小智、未导入主环境类到3.10进程。AI需协调受限宿主RPC及AE逐连接桥，把owner/connection/epoch与候选request_id绑定，取消ack由宿主实际退出后传递；普通客户端断开不能代替这个ack。真实无写快照仍须在宿主Hy边界取得。以上接力不由AF越界修改公共启动器或AB SDK。

第二阶段最终定向回归 **168 passed、3 skipped（7.85秒）**，3个跳过仍为未提供隔离小智/Hy SDK 的原集成项；AE源码快照的3个组合项实际执行通过。两份文档用临时公共清单严格检查通过，未改共享清单。原六请求账本/摘要保持原字节，未新增真实样本、联网获取、依赖安装、GPU或日用服务操作。
