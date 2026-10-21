# AI：输入观测公共接线与诊断候选

日期2026-10-21，基线7fcddd4935f26b4d78a4beb9a8561f4768d668a3。
本候选只准备buffered模式的只读诊断，adaptive实机FAILED保持，不改端点/VAD/AEC/ASR阈值、预取策略或协议。
AG、AB、AE新实现与持久化草稿不纳入；ROOT负责停机、一致备份、部署和一次带观测实机。

## 固定交付与实际接线

- AD `cdac0699eb3717160d475308b3c98eeef3ac8427` 接为61c72383：仅[双工夹具/证据](AD-barge-in-source-duplex-20261021.md)。
  本树10项真实自有随机HTTP/WS及CPU Opus通过，18.88秒；VAD/ASR是替身，未复现场景根因。
- AC `b66a5e7bf00c3fab967617ce659d459448563005` 接为03121581：[只读helper/交接](AC-input-interruption-20261021.md)。
  安装器为install_voice_input_observation，getter为voice_input_observation_snapshot；不使用草稿旧别名install。
- AI仅接[公共启动](../../../scripts/development/xiaozhi/launch_with_memory.py)、
  [控制getter](../../../scripts/development/xiaozhi/device_control.py)及[网页桥投影](../../../src/longmemory/adapters/device_control/voice_input_observation.py)，不改AC/AD实现。

公共启动先核验既有控制快照15项源码指纹；固定上游HEAD为eb4b28c59ed7ed885258498cf757ce14352d620e，AI只读独立核对通过。
在服务端实例已构造、监听前，从其_asr获取真实类型，要求与已加载可信FunLocal类同一且继承固定ASR基类；
不额外导入/创建模型，不接受任意外部提供器。control动态包装先完成，再装观察器，最后进入原WS监听。
实际ASR子类与base都交给AC，保留预取别名；open_audio_channels在工作线程之前附着队列代理。
未知源码/提供器或诊断安装异常保留原服务启动，不重试业务；未附着只能报告not_observed，不能假称已采样。

device_control.status新增独立可选voice_input_observation，8767网页桥同步白名单投影，不增加前端UI。
固定14个顶层字段、44计数键、6个inflight阶段和有限flags；只接有限整数/布尔/枚举，未知字段或失效诊断投影为unavailable/null，
不让可选诊断错误阻断原设备状态。缺字段兼容旧桥；no_connection/not_observed/unavailable缺测均为null，observed/closed语义保持AC定义。
getter不创建状态、不缓存旧连接、不读音频/问题/身份；detach后不保留旧计数或AEC当live。

endpoint_packet_count是端点PCM缓存帧数，含预留/静音，不是网络包数；formal_audio_frames是正式任务列表元素数，
16个PCM帧可已合并成1个元素。只在AC已核验分支给端点证据，其他分支null；flags只代表当前/最近处理状态，不能回补失败口令历史。
所有计数是累计连接阶段，不是CPU时间。ROOT应在连接存在时一起保存natural_interruption及新字段的前后差值，不能只看最终断线快照。

## 实际检查与发布边界

当前真实helper、公共bootstrap/getter、已有ASR预取/输入计时、控制端和网页桥联合 **244通过/0skip/2.33秒**，
报告本树ignored data/test-tmp/ai-input-probe-combined-01.xml。
包含实际AC helper从当前ASR子类启动、预取别名的formal/speech单次计数、16端点帧/1任务元素、getter→网页投影、
失效/缺测/断线、安装顺序、原异常及取消；实际小智Python3.10.20子进程真实wait_for超时计为speech_timeout，异常原对象传播且未导入torch。
之前只有接口替身的104项不冒充本次真实helper验证；本次没有重跑旧benchmark75、171、350或全后端。

CI仅登记AD10项与实际3.10检查1项的精确资源例外；模拟解释器缺失后 **20通过/11精确skip/0.43秒，7 subtests通过**，
报告ai-input-observation-resource-01.xml；audit_report确认(20,11)，没有纯合成例外或模块通配。
测试只用固定方法快照/合成输入/自有回环端口，不运行声学模型、不读真实文本/音频、不操作日用服务、数据库、GPU或设备。

根因尚未定位。AD合成证明7/15帧可被长度门拒绝、abort背压可延后ASR但仍收包，不据此调阈值或认定实机原因。
ROOT部署仍保持buffered；先确认当前连接观测有效，再请所有者一次带诊断复测，失败则保留各边界差值。
该候选是诊断准备，不是行为修复或adaptive重新放行；AG/AB另队列，持久化stash继续保全。
