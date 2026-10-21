# AB：首次检索观测协商设计冻结

日期：2026-10-21。基线main `c74b88834683080d4dc4ee4b770f48707ff5b349`。隔离树沿用AB原树，新分支 `codex/ab-hy-first-recall-observation-20261021`；旧 `codex/ab-hy-l6-l7-20261021` 和四个已交付提交保留。本次按主会话后续指令收缩为设计/合成契约验证，待ROOT/AI审查，不实施或部署详情协议。

## 冻结内容

提议见 [ADR-0202](../../adr/0202-first-recall-observation-negotiation.md)，固定 [三向合成回执](AB-first-recall-observation-examples-20261021.json)，参考模型 `tests/fixtures/ab_first_recall_observation_contract.py`，测试 `tests/unit/methods/test_first_recall_observation_contract.py`。

选择独立v2详情包：原X-Memory-Observation的v1基础包原样保留；只有X-Memory-Observe=1、合法匿名关联、明确X-Memory-Observe-Detail=2与实际能力满足，才附加X-Memory-Observation-Detail。新版客户端连接旧服务时保留基础包，另记详情unavailable且observation=null；坏详情仅invalid，不吞基础包、不回显原文。详情缺阶段是未观测，不是0。基础日志不扩必填schema，另用memory_request_detail记录v2。

新增测点仅为已核实的客户端getter、回环HTTP响应头、现有embedding锁、原BGE encode、VDB执行器排队与原查询callback。没有Rust内部索引锁测点，不伪造该数值。SDK/网关能力也须协商，不能让新阶段默认对所有旧观测调用开启。

具体文件/函数、包含/排除的耗时和误差边界已列入ADR。输出粒度0.001ms不是准确度保证；当前没有观测开销实测和数值误差上限，不能给出未经测量的±ms承诺。缺失阶段为未观测；详情received只表示收到合法v2，不代表测量齐全或业务成功。

## 验证与限制

合成契约26 passed（0.17秒）。已执行不可变c74的服务端valid_snapshot与小智_observation_header，确认新stage混入v1会使旧解析器整包拒绝；三向协商的新服务基础头逐字相同。覆盖新→旧明确不可用、未知版本不自动开启、异轮/未知阶段/额外字段/非数字/NaN/超界拒绝且保留基础包、缺项不补0、无SDK能力不伪造空成功、200/400/409/503业务对象与状态不变，以及合成正常/异常/取消单次调用结果不变。

这是参考契约证明，不是HTTP/SDK/线程取消钩子的落地证明。没有启动SDK、真实模型、GPU或日用服务，没有访问API/个人库/私有配置，没有改预算或持久业务数据。示例毫秒值固定为合成输入，不是实测、性能结论或首次5.4秒归因。

两份设计文档的候选清单strict检查通过；共享documentation-manifest保持未改，候选放在本轮忽略测试目录，供ROOT合入审查时登记。设计提交只包含两份Markdown、合成示例JSON、参考fixture和其测试，不包含六个运行时草稿文件。

## 保留但不交付的运行时草稿

收到协商审查要求前曾修改六个文件：longmemory_provider.py、memory_runtime路由、model_gateway.py、observation.py、sdk_observation.py、worker.py。它们仍是**未提交的旧v1扩展草稿，不符合本次冻结的独立v2方案，不可合入或部署**。早先63项基础单元通过不代表这个旧方案已被批准。源码仍留当前隔离工作区，另保存可回退diff到忽略目录 `data/test-tmp/ab-first-recall-design-20261021-01/unreviewed-runtime-v1-draft.patch`，SHA256 `1e852b31fc06c342247119b69fae12cad4ae6f951666a71c3f010b88a4dcc2cb`。设计提交不包含这些运行时代码。

当前自有已安装provider hash由主会话给出为 `7241a12e6fe9d8c250245cf781167555c7df53375ef643bc02ebcaf1a18240e9`。本AB未修改消费副本或setup白名单。后续AI须对最终v2源码另验已批准版本升级、重复执行幂等、unknown拒绝与回退，不得把本次旧草稿hash当作批准目标。

## 后续审查与preset边界

ROOT/AI先审查v1/v2分离、能力协商与独立详情记录，批准后才能把保留草稿改成最终实现，补真实SDK＋本地替身网关、混合版本、异常/取消和隐私测试，再对最终源码重算proof。日用实际观测另由主会话协调，本分支不合并main、不推送、不向其它会话发消息。

严格preset“准备轮次但不检索”建议仅保留在ADR：原始用户归档、预算通知覆盖、turn/receipt、完成/取消、后续写入预算及角色声线绑定必须保留；不使用检索正文不等于可以删掉query_memory。它是后续独立设计，不扩场景、不改Memory Core，本阶段没有prepare_only或skip_recall实现。
