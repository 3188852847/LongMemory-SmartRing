# AD：Doubao四包节拍测试的观测时钟修复

2026-10-21；仅修改本测试及本文，未改生产client、日用配置/服务、GPU、真实API或固件。
执行工作树 `local/worktrees/ad-cosy-continuity-20261021`，分支`codex/ad-cosy-continuity-20261021`，
任务开始HEAD为`ff6ef6e6615017b14f1c91192a341e1b08410560`；没有cherry-pick主阶段、合并或推送。

## 来源与远程事实边界

主会话给出：候选Quality 39572671724全绿；相同f159的main CI 39574569518仅backend该项失败，
frontend/browser通过。本次未联网重查Actions，仅只读主会话保存的
`local/archive/hy-advanced-release/20261021T092143Z-5c5f6fa4-732b85/f159-main-quality-failure.log`。
该日志显示Windows Python3.12.13，失败为`test_session_audio_contract_and_pacing:97`：
`577.218 - 577.171 >= 0.055`不满足，backend为1 failed、3641 passed、236 skipped。
日志没有这次发送的perf_counter并行时间线或runner的get_clock_info，不能从本机推断远程唯一原因。

修改前以原始字节（不归一化换行）核对当前工作树与`f1595515`：

| 文件 | 同字节 | SHA256（两侧相同） |
|---|---|---|
| `scripts/development/xiaozhi/doubao_realtime/client.py` | 是 | `204820741be46ecd884ce9117228ecf1d093094007df5a15461b4f24fc08de07` |
| `tests/unit/development/test_doubao_realtime_client.py` | 是 | `ee1793c6ae6c680a9116a501d88d68a149ec2514abaee6f5d8aa8c03710fbe6a` |

生产`_audio_packet`默认用`time.perf_counter`，等待后重新核对deadline；FakeSocket却用`loop.time()`
观察发送。读取了机器通用、全局机器、Python规则及项目测试产物规则；使用既有主项目3.12.13解释器，
显式workdir指向AD，导入来源输出为AD脚本目录，不安装依赖或连接外部服务。

## 本机有界诊断

`time.get_clock_info`实际结果：

| 时钟 | implementation | resolution（秒） | monotonic / adjustable |
|---|---|---:|---|
| monotonic | GetTickCount64() | 0.015625 | true / false |
| perf_counter | QueryPerformanceCounter() | 0.0000001 | true / false |

当前ProactorEventLoop的`_clock_resolution=0.015625`。这里仅观察该属性，不修改loop或系统定时器。

修复前用同一FakeSocket子类在send入口并行记录两种时钟，串行24组四包合成输入；
每组仍核对4包、每包640字节及拼接等于原PCM补零至2560字节。perf首末跨度
60.3547–72.4472ms，24组均≥55ms；loop记录的跨度集合为62/63/78ms，也全部通过。
因此这批真实四包样本没有复现生产提前突发，也没有复现原测试失败；不能写成“24次都复现”。
示例一组perf偏移为[0,30.0006,45.3834,60.3547]ms，loop为[0,32,47,63]ms。

另做8组**纯计时相位探针**，不调用音频client：在loop刻度刚变化后，分别偏移0或8ms，
以一次60ms等待同时观测两种时钟；每相位4组。等待刻度有50ms硬上限，不改系统时钟或timer resolution。

| 起点目标相位 | perf实测跨度ms | loop实测跨度ms | 对55ms门的影响 |
|---|---:|---:|---|
| 刚过刻度，4组 | 60.0480–60.5553 | 46 / 47 | loop会误判不通过，perf通过 |
| 过刻度后约8ms，4组 | 60.4038–60.5228 | 62 | 两者通过 |

它直接证明本机低分辨率观测会因相位低估约60ms间隔，不是生产四包失败复现。
理想15.625ms向下量化的解释模型也得到：同一个60ms间隔，起点相位0可记为46.875ms，
相位7.8125ms可记为62.5ms。模型不是Windows实际取整实现的逐字节仿真；实际探针46/47与62已单独保留。
远程47ms与该机制相容，但远程QPC轨迹缺失，无法排除其调度/其他因素。

## 修复与验证

仅给测试增加`import time`，将FakeSocket.send的timestamp改为`time.perf_counter()`，
并注释Windows loop.time可能仅有15.6ms粒度。没有修改生产代码或事件循环的等待方式。
修改后测试SHA256为`fc9590d30aa5b919c71a2a3bf16d802372fa3bdad81edf7ea0a413e08be77cc4`。

- 保留原55ms首末跨度断言，保留真实时钟检查，没有retry、降低阈值或跳过测试。
- 4包/640字节/补零/会话形状断言全部保留。
- 早醒/一次迟醒、100包不累计漂移、大阻塞重置及最小包间距的原虚拟时钟断言全部保留。
- 与f159比较所有测试函数的AST（抽象语法树）相同；变更仅在FakeSocket观测及导入/注释。
- `python -B -X utf8 -m pytest tests/unit/development/test_doubao_realtime_client.py -q`：19 passed，0.88s。
- `git diff --check`通过；结束时再次核对生产client仍与f159同字节。

本次只说明测试测量前提及本地离线结果，不宣称远程CI已重跑通过、付费API/真实网络节拍或声音体验通过。
Doubao日用模式没有启用；由ROOT交AI复核、整合与安排后续CI。
