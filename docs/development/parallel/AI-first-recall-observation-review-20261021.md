# AI：首次检索 v2 观测审查与部署候选

日期：2026-10-21。基线 `edc51f8b5b8ff669c1aa4d354f0ca436016de5da`，分支 `codex/ai-ab-first-query-observation-review-20261021`。本轮仅交付观测候选，不改变记忆检索、预算、归档、回执或声音行为。当前 buffered 实机打断失败仍由 AC/AD 查证，未在此候选中解决。

## 来源与审查结论

AB 设计 `3739d8857b35c3dc54b631e7a9d5e83f1c11a0dd` 接为 `6d368a07`，实现 `e4d62aae3197adc8a392c04abed661ff9448f690` 接为 `8b575b39`。协议见 [ADR-0202](../../adr/0202-first-recall-observation-negotiation.md)，原始软件与开销证据见 [AB 交付](AB-first-recall-observation-implementation-20261021.md)。这些历史检查与本次 AI 独立验证分开记录。

旧 v1 响应及阶段白名单保留；详情使用独立 v2 header 和日志。worker 显式声明支持后才启用，未知版本、旧端、坏包和异轮不破坏合法基础观测；缺项不填零。两个 header 值共用原 4096 字符预算，RPC 保持原长度限制，超额先舍弃可选详情。只有自有回环 embedding 端点获得匿名关联字段，不向供应商转发。

核对 SDK getter、原执行器 callback、网关锁、API 与 provider 后，可按既定 v2 先取证。七个详情阶段为嵌套墙钟边界，不能相加；`embed_client_get_ms.calls` 不代表新建客户端次数。首次 `with_raw_response` 资源初始化、SDK embedding 槽位等待、完整响应 body/parse 仍包含在 `embed_rpc_ms` 等外层计时，未拆成新阶段。若需要补测，另行协商版本或独立探针，不向 v2 严格解析器塞新键。

现有启动已预加载 BGE，且发生过 document 编码，不能把首次慢直接归因为冷模型加载。`memory_ready` 是累计边界，要与同轮 `memory_request_timing` 对照；随后 36ms 可能为向量缓存命中，不能当作相同工作量的热态对照。本轮没有真实日用首次采样，未定位 4–5 秒根因，也不承诺提速。

## 精确升级与可移植兼容检查

仅在 [setup.py](../../../scripts/development/xiaozhi/setup.py) 登记 ROOT 已核验批准的旧 provider 原始 SHA256 `7241a12e6fe9d8c250245cf781167555c7df53375ef643bc02ebcaf1a18240e9`。仍须显式 `allow_known_update`；同字节幂等不写，未知修改、旧版追加注释和未批准 CRLF 转换全部拒绝且保留目标。没有读取或写入实际安装副本。

兼容测试改用 c74 不可变公开 Git blob 的 LF 样本及硬编码摘要，不再因浅克隆缺历史对象跳过。这些样本是旧代码，不含私有配置：

| 样本 | 字节数 | SHA256 |
|---|---:|---|
| [provider](../../../tests/fixtures/xiaozhi_provider_c74.py.txt) | 28928 | `7241a12e6fe9d8c250245cf781167555c7df53375ef643bc02ebcaf1a18240e9` |
| [父进程](../../../tests/fixtures/hy_process_client_c74.py.txt) | 8722 | `4fc37e796571050ce0a3829303f24899339ff136608fba3550a323c9ec1d5c6d` |
| [v1 解析器](../../../tests/fixtures/hy_observation_c74.py.txt) | 3692 | `7129844923491ef62e6eadb11a02cbeaaf5969ed48bd0fbfd816dac9bacf90da` |

三项分别来自 `c74b88834683080d4dc4ee4b770f48707ff5b349` 的 `scripts/development/xiaozhi/longmemory_provider.py`、`src/longmemory/methods/hy_memory/process_client.py`、`src/longmemory/methods/hy_memory/observation.py`，由 `.gitattributes` 固定 LF。当前 provider/父进程/解析器不能冒充旧端兼容依据。

## 本次独立验证

所有导入明确指向本 AI 工作树；主 Python 3.12.13 运行测试，显式只读借用 V 树所有者已安装的 Hy SDK 与主项目小智 Python 3.10.20。合成库、临时目录和随机回环端口隔离，不连接日用端口、不调用声学或外部模型。

| 范围 | 实际结果 | 本树忽略目录 `data/test-tmp/` 报告 |
|---|---|---|
| 协商/取消/API/provider/安装器、固定 SDK 原执行器与自有网关 | 196 passed，0 skipped，11.50 秒 | `ai-ab-first-recall-review-01.xml` |
| 真实 Hy 与 Python 3.10 薄桥、旧父/新 worker、固定旧解析器、质量门 | 86 passed，7 subtests passed，0 skipped，25.83 秒 | `ai-ab-first-recall-cross-review-01.xml` |
| 既有进程与桥接契约 | 33 passed，0 skipped，0.63 秒 | `ai-ab-first-recall-process-review-01.xml` |
| 模拟 SDK 缺失及精确资源守卫 | 33 passed，3 skipped，7 subtests passed，0.31 秒；audit_report 为 (33, 3) | `ai-ab-first-recall-resource-review-01.xml` |

各组有重叠，不相加声称独立用例数。SDK 缺失仅新增两项精确资源登记：真实执行器取消用例和真实 SDK v2 首次召回用例；原网关 SDK 缺失项沿用，不放行模块或前缀。固定旧端测试没有历史对象缺失例外。

本树回执 `data/test-tmp/ai-ab-first-recall-review-receipt.json` 保存代码来源、报告摘要与文件原始字节摘要。未重跑 AB 的 642 项大组或性能开销实验，未以旧成功记录替代本次验证。

## ROOT 部署接力与未验收项

当前新 provider 为 31326 字节，原始 SHA256 `f425a3824f3771a16e7bd8df2b022376257c0d8f6673cd70c23d552a8943f717`；管理 RPC 身份为 `fc9d53ea2b90be3d9a80846b21eec9b389f2dbe4393b51d8956f3013fcd103e8`，与 AB 交付一致。setup/测试接力未改变这两个身份。

ROOT 合入最终字节后，按既有服务所有权、停机与一致备份流程核对实际旧 provider，再做显式升级；按最终源码身份重新取得管理证明，不能复用旧 proof 或绕过守卫。本会话未重签、部署或重启日用服务，未写私有配置、个人数据或设备。保持 buffered、候选与主动调度既有关闭状态；AG GPU、AE 双模型及持久化草稿不混入。

部署后，等待所有者真实首轮，对齐同一匿名轮次的基础/详情/整轮观测，明确缺失阶段、缓存条件及实际调用次数后再判断瓶颈。当前 P0 输入链仍未定位，AC/AD 证据与接口另行审查。
