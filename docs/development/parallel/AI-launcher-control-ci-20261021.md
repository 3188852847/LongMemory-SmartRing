# AI：启动器已运行请求超时测试的同步修正

日期：2026-10-21。基线 `2b58cb5d78693605d8b8f309fe30e71fbdcc65e1`，分支 `codex/ai-launcher-control-ci-20261021`，隔离树 `local/worktrees/ai-integration-review-20261021`。ROOT 转交 Quality `39611928357` / backend job `119262732031` 的公开合成日志；本轮只修测试前提，不操作生产、配置、个人库或设备。

## 远程证据与受控复现

原 CI 结果为 1 failed / 3896 passed / 257 skipped，354.49 秒。唯一失败为 [测试](../../../tests/unit/development/test_launcher_control.py) 的 `test_request_that_already_started_reports_unknown_outcome_on_timeout`：客户端 `recv` 抛 `TimeoutError: timed out`，被转换为 `launcher_control_unavailable`。同一日志还有 Tk Variable 析构的线程警告，但没有证据足以断定它就是这次停顿来源。完整日志由 ROOT 保留在主仓忽略目录 `local/archive/hy-advanced-release/signal-deploy-20261021T135435Z-013b84/quality-backend-job-final.log`。

[生产 control.py](../../../scripts/development/launcher/control.py) 在同一 pending 锁下区分三态：已完成返回原结果、仍排队则取消并返回 `launcher_busy`、已经 running 则返回 `launcher_action_outcome_unknown`。原测试只等 `_pending` 非空，未确认 dispatch 进入，就提交 polling；服务端等待只有50ms，另有测试自行设置的1秒客户端 socket 期限。两个独立时序条件会抢在待验证分支之前。

本树原样运行该模块五项全部通过（1.37 秒），未把一次通过当作排除问题。随后只在隔离进程内做两种受控调度，没有修改生产源码：

- 延后 polling，直到真实服务端的排队等待到期。原测试稳定断言失败，真实返回 `launcher_busy`；它误把“入队”当作“已运行”。回执 `data/test-tmp/ai-launcher-control-queue-race-repro-01.json`。
- 服务端已算出 `launcher_action_outcome_unknown`，但将发送推迟到原客户端1秒期限到期后。原测试复现 `launcher_control_unavailable`，原因为 `TimeoutError`，与远程错误链相同。回执 `ai-launcher-control-transport-timeout-repro-01.json`。这证明原测试混入传输调度约束，不宣称重现了远程机器的具体停顿来源。

## 最小修正与验证

只改原失败用例：以单个合成连接执行真实 `_serve`、验权解析、pending 锁/状态选择、`poll` 和 dispatch；明确等待 dispatch 进入并保持未完成，再由局部 Completion 返回逻辑等待到期。被测模块的 Event 工厂仅在该测试内替换，不修改全局 threading。没有把生产50ms或客户端超时加长；5秒仅为测试死锁保护，不决定业务超时分支。

断言保留结果未知、运行中状态、dispatch 恰好一次；释放后原操作正常完成，且不向已答复调用者发第二次响应。其余真实随机回环 TCP 测试保持原样，覆盖请求/响应、验权、操作白名单、真实排队超时及不得迟到执行。本用例不再用真实 socket 调度速度代替状态分支前提。

- 修后本模块 **5 passed，1.00 秒**，报告 `data/test-tmp/ai-launcher-control-after-01.xml`。
- 控制与面板延迟设置相关组 **26 passed，0 skipped，2.42 秒**，报告 `ai-launcher-control-related-01.xml`，包括原真实 TCP 用例与原 Tk 子进程用例。
- 仅在内存编译三个错误变体：running 误报 busy、超时取消 running 状态、重复 dispatch；新测试均明确拒绝，回执 `ai-launcher-control-contract-mutations-01.json`。没有修改生产文件或为通过而放宽断言。

本轮未重跑全后端、远程 CI 或管理证明；原 CI 失败记录保留，远程是否恢复需 ROOT 合入推送后再报告。`src/scripts` 生产源码及管理原语、已交付 proof 原字节未变，不重签无关证明。文档和清单仅登记本次故障与验证，不将“正常了”的实机反馈扩展为间歇打断彻底解决。
