# AI：两项专属语音资源 skip 的精确登记

2026-10-22。基线 `5d04d08d3cf4168d35012b3e8544f126a17b3a0e`，分支 `codex/ai-ci-owner-skip-fix-20261022`，代码提交 `588c069adf3a0d9bcfb8724f578a2d43fa41ad47`。ROOT 授权最小CI修复；仅改 [backend_resources.py](../../../scripts/ci/backend_resources.py) 及[质量门合成回归](../../../scripts/ci/test_backend_quality.py)。不改生产、测试用例或其skip条件、audit_report逻辑、工作流、依赖与下载策略，不操作日用或重启服务。

## 失败事实与两项边界

ROOT 提供的365e53f3远程run39794062112前端成功，后端pytest为4121 passed/271 skipped，但质量门拒绝未声明用例。AI仅读主会话已保存的 `local/archive/hy-advanced-release/eos-vad-release-20261022-01/quality-365-failure.log`，独立确认其中异常身份为 `tests.unit.development.test_direct_ws_v2 / test_actual_first_five_prebuffer_sends_do_not_overwrite`；未重复下载日志。pytest通过不等于整个后端job成功，旧远端结果也不属于本候选。

按[现有CI合同](../continuous-integration.md)，托管CI不下载本机固定SDK或专属Python3.10，跳过必须逐项登记。仅新增：

| 完整classname / testcase | 未改动的实际跳过条件 | 原因字符串 |
|---|---|---|
| `tests.unit.development.test_direct_ws_v2 / test_actual_first_five_prebuffer_sends_do_not_overwrite` | 主项目实体根下 `local/runtime/xiaozhi-esp32-server/.git` 不存在 | `owner-installed pinned SDK unavailable` |
| `tests.unit.development.test_voice_eos_vad_control / test_native_vad_eos_tail_real_wrappers_and_loopback` | 既有夹具定位的专属 `.venv/Scripts/python.exe` 不是文件 | `owner-installed websockets runtime unavailable` |

第二项是在新EOS测试源码中独立审查的同类门禁，不把较早365日志当作它已执行的远端证据。其原因名中的websockets runtime由现有用例沿用，实际skipif只检查该解释器文件；解释器存在但websockets缺失、SDK缺失/版本损坏等子进程失败仍是失败，不增加兜底skip。首五包用例在仓库存在但固定commit缺失时也仍失败，不把损坏资源当“未部署”。

清单274项变276项，旧项无删除、旧原因无变化。`audit_report`仍按完整classname及含全部参数的用例名查表，原因按原有固定子串合同核对；没有模块/前缀通配、允许任意参数或跳过错误报告的修改。

## 验证与收据

修前合成JUnit对这两个正确资源原因均报“未经声明”；收据在本树忽略路径 `data/test-tmp/ai-ci-owner-skip-baseline-20261022-01.json`。修后合成回归允许审定身份/原因，同时拒绝空原因、NumPy缺失、异常SDK原因，以及同模块未知用例、函数后缀、新参数和其他模块。原失败/collection error、缺主依赖、空报告和其他资源边界回归全部保留。

既有Python3.12.13运行质量门测试：pytest **9 passed、23 subtests passed，0.26秒**；JUnit展开为32项零失败/错误/跳过。工作流相同的 `python scripts/ci/test_backend_quality.py` 入口亦为9项OK。未运行全后端、重跑本机native或修改远端运行环境。

- JUnit：本树忽略路径 `data/test-tmp/ai-ci-owner-skip-20261022-01.xml`，SHA256 `1e5d9dd669b5b51cb5d2ebb9a5fd2b010b385b2023ad56a3e7565dbcab1078d1`。
- 精确新增集/零移除/零旧原因变化收据：`data/test-tmp/ai-ci-owner-skip-proof-20261022-01.json`，SHA256 `19866f4c0eee0ea38dfdf1bdf7cf1cc5b99ed1e1bd3ef4c374c2f36be396a66f`。
- 清单源码SHA256 `d18fbedadc73b08152dfcaac0e66ec700a2bc9c0ab785fb2acf29494194904c1`；审计测试源码 `63852702c22c6e96cb1e324e5de778e8d3d845e87e30550e545aeae85edd1068`。

原本机native的92项零跳过收据及摘要 `7c6cb47b2babe638d82937063fe637a31f3d7818048be4230c26ef08ed5c8874` 保留，两个新增身份与其中实际JUnit一致；本次未将它重写成新运行。EOS生产源码仍为 `fbd571deaa273c0abeae22d4633fec839d4f69e71506add081ee6d3e12f7aee6`，标签源码仍为 `7965faff9eecfffe0a1e846ae51a42e4788b10072a8083d229ea853c9ce7c9ca`。资源例外只说明CI环境边界，不证明声学或实机功能正常。

代码先冻结交ROOT安排AD独审，本记录和文档登记随后交付。窄记录严格文档检查及差异空白检查通过。远程CI待主会话推送后确认，本会话不合主或推送，也不把合成质量门通过写成远端通过。
