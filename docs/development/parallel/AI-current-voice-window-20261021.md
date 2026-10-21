# AI：当前声线三模式窗口审查与启动交接

日期：2026-10-21，基线c74b88834683080d4dc4ee4b770f48707ff5b349。
分支 `codex/ai-current-voice-window-review-20261021`；旧审查分支保留。未执行GPU窗口。

AD单笔ecf23d5a35f874a3f8e0e7e63dfaa86410462c1a接为57f24b9b；
预检记录6ad92094ced11078543607f1605bb4deb34449fd接为f980f54f。
驱动核心审查通过：相同两条公开全文、同一声线/模型实例、buffered与incremental真实请求差异、
adaptive复用既有缓冲；12测量+取消/复用14请求，失败不补跑。HTTP无seed功能，明确不受控随机，
不把Opus首帧或能量代理当物理首字。原44项测试通过后仍发现过零缺陷，该历史保持。

## 必要修正与边界

[驱动](../../../scripts/development/cosyvoice/benchmark_ad_three_modes.py)的能量代理现定义为：
24kHz PCM16连续120样本即5ms窗口，RMS≥200（约-44.3dBFS），且至少60个样本绝对幅值≥200。
跨解码帧保留滚动窗口；窗口未满无结论，每次请求新建EnergyGate。附加半窗占有率避免单个满幅尖峰
仅凭平方和达标，允许正常波形过零；该阈值没有听感/语义验收。旧反例见[AD预检](AD-three-mode-preflight-20261021.md)。

AI独占新增[窗口入口](../../../scripts/development/cosyvoice/run_ad_three_mode_window.py)，
AD驱动只测请求，窗口入口只管已授权单实例的启动/计划/退出，不负责停启日用或切模式。
默认计划不读声线、不联网、不启动进程。真实执行前须ROOT完成当前所有权/一致备份与日用停止、
复核固定源码/模型及新WDDM桌面背景收据；不沿用关闭窗口，不新增用户审批。

- 仅18774，自有模型/CPU进程先等待管道，再加入Windows Job才获许可。退出只清理该Job，不按名称或旧PID杀服务。
- 源码固定074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc，复用主项目CosyVoice3.10环境和既有模型；
  `profile_root`显式主项目，比较主档案的config/context与实际服务能力身份，摘要只在内存，缺档案不回退默认声线。
- 保留加载前HighQoS、fp16、hidden-only、默认model_streaming=false、force_buffered=false；v2按请求切增量。
- 离线网络保护，缓存只写本次新结果目录，WeText只读既有ASCII相对路径；不安装下载，不写共享配置、声线、参考音频或数据库。
- 从执行入口即开始同一个300秒单调时钟，包含资源核对、模型加载、两次既有暖机与14请求；两次暖机各15秒由父进程硬监管。
  服务端另限14次公开文本/无缓存/无草稿声线的v2入口，合计最多16次；没有额外试跑或种子假字段。
- 正常先经自有stdin请求退出，超时/失败由Job终止并查询active=0；Job核对另最多4秒。
  失败留固定stage/异常class/reason_code，不落异常正文；强制退出不是GPU kernel即时抢占证明，ROOT必须复查监听/GPU再恢复日用。

## ROOT的最少执行入口

工作目录为本AI隔离树。ROOT核对干净候选后，先运行 `--plan`；真实执行只运行一次窗口入口，
不能先手动启动模型或另跑AD驱动。主项目路径作为 `--production-root`；`--output`必须为本树experiments/results下新目录。

```powershell
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -B -X utf8 scripts/development/cosyvoice/run_ad_three_mode_window.py --plan
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -B -X utf8 scripts/development/cosyvoice/run_ad_three_mode_window.py --run --approval '<ROOT新资源收据绝对路径>' --production-root 'D:/03-项目/01-正式项目/智慧圆屏' --output 'experiments/results/ai-current-voice-<唯一窗口ID>'
```

收据schema_version=1、scope=`ai-current-voice-single-instance-window`、reviewed_by=`main_session`，
candidate_commit为本树精确HEAD、checkout为本树绝对路径、production_root为主项目绝对路径、window_id为新唯一标识，
url=`http://127.0.0.1:18774/v1/audio/stream`、max_seconds=300、physical_gpu_exclusive=false。
`production_stopped/other_gpu_model_workers_stopped/source_and_model_verified/current_profile_root_verified/single_model_instance`均须为true；
shared_desktop_baseline沿用gpu_window.py要求的本次实际已审查WDDM背景结构。
issued_at_utc/expires_at_utc均带时区，签发到执行不超过60秒，有效期不替整窗续期。
窗口入口从真实加载前起点和实际服务身份生成AD消费收据，自动在同一预算内调用驱动，不自动续跑。

只写本树忽略目录中的window-summary.jsonl、driver-resource-receipt.json及driver/summary.jsonl、运行缓存。
消费收据含本次进程映像/资源元数据，只留私有本机；不输出档案摘要、原音频或真实对话。
完整通过需驱动14行完整/取消/复用、独立线程退出与空闲证据，以及窗口清理树退出确认。
任何失败保留已经完成行和阶段，禁止剔除失败后批准模式。真实结果交AD解释、AI复核、ROOT发布；本轮不翻开关。

## 实际CPU验证

AD原件44项独立通过1.29秒。修正能量门及窗口最终专属联合 **75通过/0skip/2.13秒**，
报告为本树ignored `data/test-tmp/ai-ad-window-final-combined-01.xml`；包含正弦过零/静音/尖峰跨帧、
真实自有随机端口HTTP+现装CPU Opus、假模型声线注入/错误身份拒绝、两个独立期限、精确调用预算、
失败阶段脱敏，以及真实Windows Job清理其自有CPU进程与后代。没有启动模型、查询日用HTTP、停日用或访问私人声线。
未重复完整CI、171或350，不凭CPU检查声称真实GPU、当前声线性能或物理播放已通过。
CI清单仅登记两项真实CPU Opus参数用例和一项Windows Job用例的精确资源原因；无纯合成例外。
报告护栏7项及7 subtests通过；合并实际缺Opus模拟的2项skip与护栏报告，audit_report为(7,2)，正常CPU报告为(75,0)。
