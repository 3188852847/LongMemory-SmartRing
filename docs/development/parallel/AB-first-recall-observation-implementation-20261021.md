# AB：首次检索v2观测最小实现

日期：2026-10-21。分支 `codex/ab-hy-first-recall-observation-20261021`，隔离树 `local/worktrees/ab-hy-l6-l7-20261021`。基线 `c74b88834683080d4dc4ee4b770f48707ff5b349`；设计冻结提交 `3739d8857b35c3dc54b631e7a9d5e83f1c11a0dd`。ROOT批准设计后明确授权续做最小落地，最终交AI审查，当前不部署。决定见 [ADR-0202](../../adr/0202-first-recall-observation-negotiation.md)，历史旧稿见 [设计记录](AB-first-recall-observation-design-20261021.md)。

## 改动与生效条件

原 `X-Memory-Observation`、v1阶段白名单和 `memory_request_timing` 记录保持原协议。只有既有合法基础观测加 `X-Memory-Observe-Detail: 2` 才允许详情；响应另用 `X-Memory-Observation-Detail`，小智另记 `memory_request_detail` 的received/unavailable/invalid，不扩基础必填结构。旧端、未知版本、坏包或异轮不影响合法基础记录。详情缺项表示未观测，不补0。

`observation.py` 分开校验/合并/序列化两个版本，关闭详情时不读取新测点时钟。单包4096字符，两包header值合计4096；超额只舍弃详情。`process_client.py` 只接受明确且已识别的worker能力声明，发送可选版本标记，未声明时关闭；`worker.py` 仅固定SDK钩子已应用时声明支持。RPC原2,000,000字符上限保留，可选请求标记/响应详情引发超额时先去掉详情。

`sdk_observation.py` 在独占worker内增加固定SDK getter与原VDB执行器callback包装，并核验 `utils/async_executor.py` 指纹；不修改SDK安装文件、不替换执行器、不新增业务调用。排队取消时不写虚假排队/后端0，运行中取消仅保留已发生的进入边界，迟到callback不再改返回观测。`worker.py` 只向既有受控embedding端点附加匿名关联与版本；`model_gateway.py` 只在已认证回环embedding请求启用v2，沿用原锁、encode与业务计数位置，不向供应商转发详情。

API路由只协商和加可选header。provider在解析业务body前保存合法数值头，因此409或坏body不会吞掉已收到的基础观测；不读取/记录HTTP错误正文、不重试。取消消费者的基础日志保留原语义，详情只在实际请求线程返回后记录，仍关联原轮次。预算、归档、receipt、完成/取消、角色/声线/TTS撤权均未调整。严格preset准备但不检索仍只是ADR中的独立后续建议。

## 软件证据

- 单元回归第一轮：585 passed / 1 skipped，12.43秒；跳过项硬编码要求本隔离树内的SDK源码，本树不复制或安装环境。真实SDK由下述显式路径单独验证。
- 真实SDK＋自有随机回环网关首次召回收到全部七阶段；假512维编码器、空合成库，外部模型尝试0。详情开/关的embedding调用次数与既有空召回/警告相同。首次测试错误假定空库没有warning，实际原链路为 `hy_recall_may_mutate_state`；修正测试为比较两模式原值，未改业务实现。
- 固定SDK原执行器验证正常、原异常、排队取消及运行中取消：每个callback只调用一次，原执行器对象未替换，取消继续传播，迟到不改旧轮观测。SDK安装源码六项固定指纹复核均相同。
- 实际API路由验证基础/详情开关、未知版本、200/409状态及原业务body；自有HTTP网关验证认证、版本、关联、相同embedding body与预算0。provider覆盖无详情、有效、异轮、未知阶段、NaN、额外字段、超长、坏业务body、HTTP错误与取消后迟到返回，坏原文不进入日志。
- 混合版本执行不可变c74父进程对新worker；新父进程缺失/未知能力时不传详情，新/新显式能力才传。原c74服务端与小智v1解析器对照仍通过。请求、响应和header超额仅舍弃可选详情的边界另测。
- 真实SDK/网关及轮次回归一轮56 passed / 1 skipped，32.62秒；该组包含48项小型协商测试。跳过的跨小智3.10薄桥测试未提供显式voice解释器，不使用Hy 3.12冒充。
- 最终合并执行相关单元、真实SDK/网关、provider/诊断和原小智桥接回归：**642 passed / 4 skipped，49.68秒**。四项分别要求本隔离树SDK源码、显式Hy＋voice解释器、固定小智上游源码、本树小智Python3.10；均未复制/安装缺失环境，未把跳过项计作通过。

测试入口包括 `tests/unit/methods/test_first_recall_observation_runtime.py`、`tests/unit/entrypoints/test_first_recall_observation_api.py`、`tests/unit/development/test_memory_request_timing.py`、`tests/unit/development/test_first_recall_provider_upgrade.py`、`tests/integration/test_hy_memory_gateway.py`、`tests/integration/test_first_recall_gateway_negotiation.py` 和 `tests/integration/test_first_recall_sdk_executor.py`。SDK取消探针为 `tests/fixtures/ab_first_recall_sdk_executor.py`。

执行使用主项目Python3.12.13运行pytest，导入源码明确指向本AB树；只读借用V树内所有者已安装的SDK解释器。setup测试原收集缺少 `config_paths` 搜索路径，补本AB `scripts/development/xiaozhi` 到该次进程PYTHONPATH后通过；没有安装依赖或改全局环境。所有数据库在各次独立pytest目录，未连接日用端口。AD声线窗口期间暂停SDK和较大测试，收到关闭通知后恢复CPU验证。

## 合成开销范围

[开销实测回执](AB-first-recall-observation-overhead-20261021.json) 由 `tests/fixtures/ab_first_recall_overhead.py` 生成。三种模式各预备20次，轮换顺序，9批×60次，单个合成执行器与相同getter/embedding/backend调用次数。每次调用中位数：关闭56.922微秒、基础64.062微秒、详情75.733微秒；详情相对基础差11.671微秒。

这是轻量Python包装器和假二维编码器对照，不含真实SDK、HTTP、IPC或BGE，不是生产首轮耗时，也不能解释原5.4秒或承诺误差上限。七阶段是嵌套边界，不能相加，0.001ms只是输出粒度。Rust内部锁仍未单独观测。[设计示例JSON](AB-first-recall-observation-examples-20261021.json) 保持固定合成输入，未冒充本次测量。

## provider及proof接力

当前最终provider源码31326字节，原始字节SHA256：`f425a3824f3771a16e7bd8df2b022376257c0d8f6673cd70c23d552a8943f717`。源码位于 `scripts/development/xiaozhi/longmemory_provider.py`。原c74 Git blob实际SHA256为ROOT批准的旧版 `7241a12e6fe9d8c250245cf781167555c7df53375ef643bc02ebcaf1a18240e9`；换行转换后的字节不是同一身份。

使用实际setup安装器、临时合成小智目录与**仅测试模块内存**许可集合验证：旧7241需要显式known-update；升级后与最终provider字节完全一致；目标已相同幂等不写；unknown拒绝且字节保留。生产 `setup.py` 白名单没有新增7241，已安装provider没有读取/修改。本测试只证明升级机制可接力，不表示当前安装器已经允许真实7241升级。AI审查后仍需显式登记批准来源，核对最终文件原字节与回退件，不能静默覆盖。

最终源码组合的管理RPC（进程间调用）身份为 `fc9d53ea2b90be3d9a80846b21eec9b389f2dbe4393b51d8956f3013fcd103e8`。没有重签生产proof；涉及源码身份的日用proof由AI在合入最终字节后按原守卫核对，不用旧身份绕过校验。

旧v1草稿补丁仍在本AB忽略目录，SHA256复核为 `1e852b31fc06c342247119b69fae12cad4ae6f951666a71c3f010b88a4dcc2cb`，未删除或覆盖。它只用于历史回退；当前提交交付的是分离v2实现。

## 交付边界

只提交本分支；不merge main、不推送、不向其它会话发消息。未启动日用服务或GPU，未加载BGE、调用学校/供应商、读取个人库/声音/配置，未更改共享SDK、provider或proof；无网络下载或安装。当前仍待AI审查和由主会话协调的真实日用首轮观测，尚不能归因或声称修复5.4秒。

三份Markdown已用候选清单做strict检查，0 findings。工具要求候选位于公开工程目录，因此检查时仅创建本轮独占临时JSON，结束移回本AB忽略目录 `data/test-tmp/ab-first-recall-implementation-20261021-01/docs-check-manifest-public-checked-utf8.json`，输出为同目录 `docs-check-output-utf8.txt`。没有改共享documentation-manifest；ROOT合入时按候选登记。`git diff --check`通过，源码导入位置、provider/RPC身份、旧补丁与固定SDK源码指纹已独立复核。
