# AI：公开 AEC 重放工具整合与证据复核

2026-10-22。基线 `7f170ff136f52079552c28f678126e7092340854`，整合分支 `codex/ai-public-aec-replay-integration-20261022`。本阶段仅接入已审查的公开语音离线诊断工具、边界测试和实验记录；不修改生产 AEC/VAD、阈值、私有配置、个人库或日用进程，不采集真人音频。Hann 窗单点消融另行审查，不阻塞本次工具交付。

## 提交与证据关系

| 来源提交 | 本分支接入提交 | 内容 |
|---|---|---|
| `e6c37372554321427f168fdf4a21371bbbd8108d` | `996aceff` | [离线工具](../../../scripts/development/xiaozhi/public_aec_replay.py)及[七项边界测试](../../../tests/unit/development/test_public_aec_replay.py) |
| `0e1c037bd483236cbe38118cff9d64d86b11f80d` | `0c600154` | [AC 固定来源、首次失败与成功结果记录](AC-public-aec-replay-20261022.md) |

AC 会话 `01a15ab0-0d29-7c31-a57b-702f28d8e164`；AI 审查会话 `01a15ab0-25a3-7380-b682-681441e8b403`。本提交另登记两份文档；ROOT 负责后续主分支整合、远程检查与推送，本记录不代表已经发布。

AI 只读复核 AC 保存的来源/夹具摘要、转换后 WAV 头、五组固定输入、500 行逐包记录及 282 次实际所选参考切片，汇总与原记录一致。首次失败与成功配置除 harness 摘要外相同，失败收据保留。原函数与插桩函数的逐包输出一致核对属于 AC 原运行证据，AI 未重新运行模型。

- 工具及冻结 `sources/harness.py` SHA256：`f5bae9147f166368d070c4c91fd290077a21964668e6a200701a21f3f6f84932`。
- 成功 summary SHA256：`4b538ed63bf5f4fc20b36e194bdc4372d3f6a3e3e330f73234a42e77376ce3dd`。
- 成功 config SHA256：`f69cfbdd1c28f75768b9495197fffc9e6b53068f6b9bd25fe4142a4eb5d235dc`。
- 首次失败 summary SHA256：`91a163a7410fc9bf1ea606bd3417620be3096a598178b1874b09eb591a57736f`。

原始音频和实验目录仍在 AC 工作树的忽略目录，准确路径与更多摘要见 AC 记录，不纳入 Git。父进程预算是全程 120 秒墙钟硬截止；worker 计算 CPU 数字不含导入，不能表述为操作系统完整 CPU 硬配额。

## 本次验证与限制

本工作树用已有主项目 Python 3.12.13 运行 `tests/unit/development/test_public_aec_replay.py`：**7 passed，0.22 秒**；测试断言导入本工作树工具。JUnit 保存在本树忽略路径 `data/test-tmp/ai-public-aec-integration-20261022-01.xml`。两份记录登记后通过 `check_docs.py --only … --strict`，`git diff --check` 通过。本次没有再次执行真实模型回放、联网、下载、安装或访问日用服务。

离线证据足以支持诊断工具的本次接入，不能确定现场根因或选择生产修复。双讲输入的 VAD 阳性包含远端贡献；模板近端区间包含停顿，两者都不能当近端召回真值。仅回声处理后仍有阳性，不能只凭 RMS 下降或更多阳性判断方案更好。Hann 窗后直接逆变换值得单点消融，但目前不是已证实故障；偏移 +120ms 也不是可发布修复。真人声场、完整 Opus、网络、固件与打断体验均未在本阶段验收。
